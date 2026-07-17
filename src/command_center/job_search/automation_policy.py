from __future__ import annotations

import re

from command_center.job_search.schemas import AutomationClass, AutomationResult, CanonicalJob, JobSearchConfig
from command_center.job_search.standing_answers import load_standing_answers, split_detected_phrases


_NEVER_AUTO_PHRASE_ALIASES = {
    "eeo": {
        "eeo",
        "equal employment opportunity",
        "race",
        "ethnicity",
        "gender identity",
        "sexual orientation",
    },
    "self_identification": {
        "self identification",
        "voluntary self identification",
        "self id",
    },
    "veteran_status": {"veteran", "veteran status"},
    "disability": {"disability", "disabled"},
    "work_authorization": {
        "work authorization",
        "authorized to work",
        "legally authorized",
        "eligible to work",
        "citizenship",
        "citizen status",
    },
    "sponsorship": {"sponsorship", "sponsor", "visa"},
    "legal_certification": {"legal certification"},
    "background_check": {"background check"},
}

_ALWAYS_SENSITIVE_MEMORY_PHRASES = {
    "ssn", "social security number", "password", "passcode",
    "one time password", "one time code", "otp",
    "multi factor authentication", "mfa", "captcha",
    "authentication token", "access token", "api key", "secret key",
    "government id", "government identifier", "passport number",
    "driver license number", "bank account", "routing number",
    "credit card number",
}

_CREDENTIAL_VALUE_PATTERNS = (
    r"\b(?:sk|rk)-(?:proj-)?[A-Za-z0-9_-]{16,}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    r"\bAKIA[A-Z0-9]{16}\b",
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
)


def _normalized(value: str) -> str:
    words = "".join(
        character if character.isalnum() else " "
        for character in value.casefold()
    )
    return " ".join(words.split())


def _is_never_auto_phrase(phrase: str, topics: list[str]) -> bool:
    candidate = _normalized(phrase)
    for topic in topics:
        normalized_topic = _normalized(topic)
        aliases = _NEVER_AUTO_PHRASE_ALIASES.get(topic, {normalized_topic})
        candidate_words = candidate.split()
        if any(
            (
                (alias_words := _normalized(alias).split())
                and any(
                    candidate_words[index:index + len(alias_words)] == alias_words
                    for index in range(
                        len(candidate_words) - len(alias_words) + 1)
                )
            )
            for alias in aliases
        ):
            return True
    return False


def _luhn_valid(digits: str) -> bool:
    if len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, value in enumerate(int(character) for character in digits):
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _looks_like_sensitive_value(text: str) -> bool:
    # High-confidence bare SSN shape. Unseparated nine-digit numbers are not
    # rejected here because they are commonly harmless application/job ids.
    if re.search(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)", text):
        return True
    # Card numbers can contain spaces or hyphens. Luhn validation keeps this
    # from rejecting arbitrary long numeric identifiers.
    for match in re.finditer(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return True
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in _CREDENTIAL_VALUE_PATTERNS
    )


def is_never_auto_question(text: str, topics: list[str]) -> bool:
    """Shared private-memory/automation sensitivity check.

    Question-library writes use the exact same configured topics and alias
    rules as classification, so a standing answer can never create a second,
    weaker interpretation of the never-auto policy.
    """
    if _is_never_auto_phrase(text, topics) or _looks_like_sensitive_value(text):
        return True
    candidate_words = _normalized(text).split()
    return any(
        (phrase_words := _normalized(phrase).split())
        and any(
            candidate_words[index:index + len(phrase_words)] == phrase_words
            for index in range(len(candidate_words) - len(phrase_words) + 1)
        )
        for phrase in _ALWAYS_SENSITIVE_MEMORY_PHRASES
    )


def classify_automation(job: CanonicalJob, config: JobSearchConfig) -> AutomationResult:
    """Portals/phrases from config are the DETECTION list; a detected phrase
    covered by a standing answer (profile/standing_answers.yml) is
    auto-answerable and recorded on the result instead of blocking. Only
    uncovered phrases (captcha/login walls, anything Geoff has not answered)
    still force manual review."""
    blockers: list[str] = []
    portal_lower = job.portal.lower()
    text = f"{job.description_text}\n{job.apply_url}\n{job.portal}".lower()

    from command_center.job_search.config import data_root
    answers = load_standing_answers(data_root(config))

    for portal in config.automation.manual_portals:
        if portal.lower() in portal_lower or portal.lower() in job.apply_url.lower():
            blockers.append(f"manual portal: {portal}")

    auto_answered, uncovered = split_detected_phrases(
        text, config.automation.manual_phrases, answers)
    # Standing answers may draft ordinary application answers, but they can
    # never weaken the explicit never-auto-answer contract.
    protected = {
        phrase for phrase in auto_answered
        if _is_never_auto_phrase(
            phrase, config.application_questions.never_auto_answer)
    }
    if protected:
        auto_answered = sorted(set(auto_answered) - protected)
        uncovered = sorted(set(uncovered) | protected)
    blockers.extend(f"manual phrase: {phrase}" for phrase in uncovered)

    # `reason` and `blockers` describe ONLY what stops automation. Auto-answered
    # questions are NOT blockers — they travel on their own `auto_answered`
    # field so the UI can present them as handled, never as a reason to stop.
    if blockers:
        return AutomationResult(
            value=AutomationClass.MANUAL_REQUIRED,
            reason="Manual review required because blocker(s) were detected.",
            confidence=0.95,
            blockers=sorted(set(blockers)),
            auto_answered=auto_answered,
            mvp_submit_disabled=True,
        )

    if "apply" not in text:
        return AutomationResult(
            value=AutomationClass.PREPARE_ONLY,
            reason="No clear low-risk application workflow was detected.",
            confidence=0.75,
            blockers=["unclear application workflow"],
            auto_answered=auto_answered,
            mvp_submit_disabled=True,
        )

    return AutomationResult(
        value=AutomationClass.BOT_POSSIBLE,
        reason="No blocking questions; MVP still prepares only and does not "
               "submit.",
        confidence=0.88,
        blockers=[],
        auto_answered=auto_answered,
        mvp_submit_disabled=True,
    )


def can_submit(config: JobSearchConfig) -> bool:
    return bool(config.job_search.auto_submit_enabled) and not config.job_search.submit_without_geoff_selection

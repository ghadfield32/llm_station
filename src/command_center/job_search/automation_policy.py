from __future__ import annotations

from command_center.job_search.schemas import AutomationClass, AutomationResult, CanonicalJob, JobSearchConfig
from command_center.job_search.standing_answers import load_standing_answers, split_detected_phrases


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
    blockers.extend(f"manual phrase: {phrase}" for phrase in uncovered)
    answered_note = (
        f" {len(auto_answered)} detected question(s) have standing answers: "
        + ", ".join(auto_answered) + "." if auto_answered else "")

    if blockers:
        return AutomationResult(
            value=AutomationClass.MANUAL_REQUIRED,
            reason="Manual review required because blocker(s) were detected."
                   + answered_note,
            confidence=0.95,
            blockers=sorted(set(blockers)),
            auto_answered=auto_answered,
            mvp_submit_disabled=True,
        )

    if "apply" not in text:
        return AutomationResult(
            value=AutomationClass.PREPARE_ONLY,
            reason="No clear low-risk application workflow was detected."
                   + answered_note,
            confidence=0.75,
            blockers=["unclear application workflow"],
            auto_answered=auto_answered,
            mvp_submit_disabled=True,
        )

    return AutomationResult(
        value=AutomationClass.BOT_POSSIBLE,
        reason="No blocking questions; MVP still prepares only and does not "
               "submit." + answered_note,
        confidence=0.88,
        blockers=[],
        auto_answered=auto_answered,
        mvp_submit_disabled=True,
    )


def can_submit(config: JobSearchConfig) -> bool:
    return bool(config.job_search.auto_submit_enabled) and not config.job_search.submit_without_geoff_selection


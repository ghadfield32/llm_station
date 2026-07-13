"""Hybrid location + language + employment gate for job scoring.

This module is pure classification: it inspects a canonical job against the
operator's `LocationFilter` / `LanguageFilter` and returns verdicts. `scoring`
turns those verdicts into score effects (hard-exclude vs. soft penalty) so the
ranking thresholds stay the single source of truth for what surfaces.

Hybrid policy:
  - CLEAR mismatch -> hard-excluded from suggestions (a known non-target
    location, an excluded work arrangement, or a required language you do not
    speak).
  - AMBIGUOUS -> soft penalty, still visible (unknown/national-only location,
    a merely-preferred language, or a noisy employment-type signal).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from command_center.job_search.schemas import (
    CanonicalJob,
    JobSearchConfig,
    RemoteType,
)

# 50 states + DC. Name -> USPS abbreviation.
US_STATES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
_ABBR_TO_NAME = {abbr: name for name, abbr in US_STATES.items()}

# Major metros -> state, so a city-only posting still resolves to a state.
US_METROS: dict[str, str] = {
    "philadelphia": "PA", "philly": "PA", "pittsburgh": "PA",
    "miami": "FL", "tampa": "FL", "orlando": "FL", "jacksonville": "FL",
    "phoenix": "AZ", "tucson": "AZ", "scottsdale": "AZ", "tempe": "AZ",
    "mesa": "AZ", "denver": "CO", "boulder": "CO", "colorado springs": "CO",
    "aurora": "CO", "seattle": "WA", "bellevue": "WA", "redmond": "WA",
    "tacoma": "WA", "spokane": "WA", "portland": "OR", "eugene": "OR",
    "salem": "OR", "beaverton": "OR", "hillsboro": "OR",
    "new york": "NY", "brooklyn": "NY", "manhattan": "NY", "nyc": "NY",
    "san francisco": "CA", "los angeles": "CA", "san diego": "CA",
    "san jose": "CA", "oakland": "CA", "austin": "TX", "dallas": "TX",
    "houston": "TX", "chicago": "IL", "boston": "MA", "atlanta": "GA",
}

_REMOTE_TOKENS = (
    "remote", "anywhere", "worldwide", "distributed", "work from home",
    "wfh", "fully remote", "remote-first", "remote first", "global",
)
_US_NATIONAL_TOKENS = (
    "united states", "usa", "u.s.a", "u.s.", "us", "america",
    "us-based", "us based", "united states of america",
)
# A clearly-non-US onsite signal (word-boundary matched against the location).
_FOREIGN_TOKENS = (
    "canada", "canadian", "mexico", "united kingdom", "uk", "england",
    "scotland", "ireland", "germany", "france", "spain", "portugal",
    "netherlands", "belgium", "poland", "romania", "ukraine", "india",
    "china", "japan", "singapore", "philippines", "australia", "brazil",
    "argentina", "colombia", "nigeria", "kenya", "south africa", "emea",
    "apac", "latam", "europe", "european", "asia", "africa",
)


def _has_word(text_lower: str, token: str) -> bool:
    return re.search(
        rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text_lower
    ) is not None


def _has_abbr(raw: str, abbr: str) -> bool:
    """A 2-letter state code as a standalone UPPERCASE token in the raw text
    (e.g. 'Denver, CO'). Case-sensitive on purpose so 'co'/'or'/'in' inside
    lowercase words never false-match."""
    return re.search(rf"(?<![A-Za-z]){abbr}(?![A-Za-z])", raw) is not None


def _looks_remote(low: str) -> bool:
    return any(_has_word(low, tok) for tok in _REMOTE_TOKENS)


def _looks_foreign(low: str) -> bool:
    return any(_has_word(low, tok) for tok in _FOREIGN_TOKENS)


def _country_match(low: str, countries: list[str]) -> bool:
    for country in countries:
        name = country.strip().lower()
        if not name:
            continue
        if name in {"united states", "usa", "us", "america",
                    "united states of america"}:
            if any(_has_word(low, tok) for tok in _US_NATIONAL_TOKENS):
                return True
        elif _has_word(low, name):
            return True
    return False


def named_us_states(raw: str) -> set[str]:
    """USPS abbreviations for every US state named in a location string.

    Handles the Washington DC vs. Washington-state ambiguity: a DC signal maps
    to DC and drops WA unless the text carries a WA-specific token (the 'WA'
    code or a WA metro like Seattle)."""
    low = raw.lower()
    found: set[str] = set()
    for metro, state in US_METROS.items():
        if _has_word(low, metro):
            found.add(state)
    for name, abbr in US_STATES.items():
        if _has_word(low, name):
            found.add(abbr)
    for abbr in _ABBR_TO_NAME:
        if _has_abbr(raw, abbr):
            found.add(abbr)
    dc_signal = (
        _has_abbr(raw, "DC")
        or _has_word(low, "district of columbia")
        or "d.c" in low
    )
    if dc_signal:
        found.add("DC")
        wa_specific = _has_abbr(raw, "WA") or any(
            _has_word(low, metro)
            for metro, state in US_METROS.items()
            if state == "WA"
        )
        if "WA" in found and not wa_specific:
            found.discard("WA")
    return found


def _resolve_targets(config: JobSearchConfig) -> tuple[set[str], set[str]]:
    """(target state abbreviations, free-text region tokens) from config."""
    state_abbrs: set[str] = set()
    free_tokens: set[str] = set()
    for region in config.locations.regions:
        r = region.strip().lower()
        if not r:
            continue
        if r in US_STATES:
            state_abbrs.add(US_STATES[r])
        elif r in US_METROS:
            state_abbrs.add(US_METROS[r])
            free_tokens.add(r)
        else:
            free_tokens.add(r)
    return state_abbrs, free_tokens


# --- location -------------------------------------------------------------
# verdicts: match | remote_ok | ambiguous | mismatch | arrangement_excluded
def evaluate_location(job: CanonicalJob, config: JobSearchConfig) -> tuple[str, str]:
    loc = config.locations
    allowed_arrangements = set(loc.remote_types_allowed)
    rt = job.remote_type
    if rt != RemoteType.UNKNOWN and rt not in allowed_arrangements:
        return ("arrangement_excluded",
                f"{rt.value} work arrangement is excluded by your filter")

    raw = (job.location or "").strip()
    low = raw.lower()
    if loc.remote_ok and (rt == RemoteType.REMOTE or _looks_remote(low)):
        return "remote_ok", "remote role accepted regardless of location"
    if loc.mode == "worldwide":
        return "match", "worldwide mode accepts any location"
    if not raw or low == "unknown":
        return "ambiguous", "posting location is unknown"

    state_abbrs, free_tokens = _resolve_targets(config)
    hit_free = next((tok for tok in free_tokens if _has_word(low, tok)), None)
    if hit_free:
        return "match", f"location matches your target region ({hit_free})"

    present_states = named_us_states(raw)
    target_present = present_states & state_abbrs
    if target_present:
        return ("match",
                f"location matches your target state "
                f"({', '.join(sorted(target_present))})")
    non_target = present_states - state_abbrs
    if non_target:
        return ("mismatch",
                f"onsite/hybrid in a non-target US state "
                f"({', '.join(sorted(non_target))})")
    if _looks_foreign(low) and not _country_match(low, loc.countries):
        return "mismatch", "onsite/hybrid outside your target countries"
    if _country_match(low, loc.countries) or any(
        _has_word(low, tok) for tok in _US_NATIONAL_TOKENS
    ):
        return "ambiguous", "national-only location; office not specified"
    return "ambiguous", "location could not be matched to your filter"


# --- language -------------------------------------------------------------
_KNOWN_LANGUAGES = (
    "spanish", "french", "german", "mandarin", "cantonese", "chinese",
    "japanese", "korean", "portuguese", "italian", "dutch", "russian",
    "arabic", "hindi", "polish", "swedish", "norwegian", "danish",
    "finnish", "turkish", "hebrew", "thai", "vietnamese", "tagalog",
    "ukrainian", "greek", "czech", "romanian", "hungarian", "indonesian",
    "malay", "bengali", "urdu", "farsi", "persian",
)
_REQUIRED_PATTERNS = (
    r"fluent (?:in |in written and spoken )?{lang}",
    r"fluency in {lang}", r"{lang} fluency", r"native {lang}",
    r"{lang} native", r"must speak {lang}", r"{lang} (?:is )?required",
    r"required[:\s]+{lang}", r"proficiency in {lang}", r"{lang} proficiency",
    r"bilingual (?:in )?{lang}", r"business[- ]level {lang}",
    r"{lang}[- ]speaking", r"professional working proficiency in {lang}",
)
_PREFERRED_PATTERNS = (
    r"{lang} (?:is )?(?:a )?plus", r"{lang} (?:is )?preferred",
    r"preferred[:\s]+{lang}", r"knowledge of {lang}",
    r"familiarity with {lang}", r"{lang} (?:is )?(?:a )?bonus",
    r"nice to have[:\s]+{lang}", r"{lang} (?:is )?(?:an )?advantage",
)


# verdicts: ok | preferred_gap | required_gap
def evaluate_languages(
    job: CanonicalJob, config: JobSearchConfig
) -> tuple[str, tuple[str, ...]]:
    lang_cfg = config.languages
    if not lang_cfg.require_spoken_for_apply:
        return "ok", ()
    spoken = {s.strip().lower() for s in lang_cfg.spoken}
    text = f"{job.role_title}\n{job.description_text}".lower()
    required: list[str] = []
    preferred: list[str] = []
    for lang in _KNOWN_LANGUAGES:
        if lang in spoken:
            continue
        if not re.search(rf"(?<![a-z]){lang}(?![a-z])", text):
            continue
        if any(re.search(p.format(lang=lang), text) for p in _REQUIRED_PATTERNS):
            required.append(lang)
        else:
            # a merely-preferred or bare mention is a soft signal, never a hard
            # exclude — we do not hide a job on an ambiguous language reference
            preferred.append(lang)
    if required:
        return "required_gap", tuple(sorted(set(required)))
    if preferred:
        return "preferred_gap", tuple(sorted(set(preferred)))
    return "ok", ()


# --- employment (soft only) ----------------------------------------------
_EMPLOYMENT_PATTERNS = {
    "internship": (r"\binternships?\b", r"\bintern\b"),
    "part_time": (r"\bpart[- ]time\b", r"\bparttime\b"),
    "contract": (r"\bcontract(?:or)?\b", r"\bc2c\b", r"\b1099\b",
                 r"\btemporary\b", r"\bseasonal\b", r"\bfreelance\b"),
}
_FULL_TIME_CUES = (r"\bfull[- ]time\b", r"\bfulltime\b", r"\bpermanent\b",
                   r"\bfte\b")


# verdicts: ok | mismatch
def evaluate_employment(
    job: CanonicalJob, config: JobSearchConfig
) -> tuple[str, str]:
    allowed = {e.strip().lower() for e in config.locations.employment_types_allowed}
    if not allowed:
        return "ok", ""
    text = f"{job.role_title}\n{job.description_text}".lower()
    if any(re.search(p, text) for p in _FULL_TIME_CUES) and "full_time" in allowed:
        return "ok", ""
    for family, patterns in _EMPLOYMENT_PATTERNS.items():
        if family in allowed:
            continue
        if any(re.search(p, text) for p in patterns):
            return ("mismatch",
                    f"posting reads as {family.replace('_', ' ')}, "
                    f"outside your employment filter")
    return "ok", ""


@dataclass(frozen=True)
class FilterEvaluation:
    location: str
    location_reason: str
    language: str
    language_gaps: tuple[str, ...]
    employment: str
    employment_reason: str

    @property
    def hard_excluded(self) -> bool:
        return (
            self.location in {"mismatch", "arrangement_excluded"}
            or self.language == "required_gap"
        )


def evaluate_filters(job: CanonicalJob, config: JobSearchConfig) -> FilterEvaluation:
    location, location_reason = evaluate_location(job, config)
    language, language_gaps = evaluate_languages(job, config)
    employment, employment_reason = evaluate_employment(job, config)
    return FilterEvaluation(
        location=location,
        location_reason=location_reason,
        language=language,
        language_gaps=language_gaps,
        employment=employment,
        employment_reason=employment_reason,
    )

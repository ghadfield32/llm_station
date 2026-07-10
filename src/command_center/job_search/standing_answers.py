"""Geoff's standing answers to common application questions.

profile/standing_answers.yml is the adjustable source of truth. A manual
phrase detected in a posting that is `covers`-ed by a standing answer becomes
an auto-answerable question (rendered into the packet's
application_answers.md) instead of a manual blocker — captcha/login walls and
anything without a standing answer still route to manual review.

Answers are rendered DETERMINISTICALLY (never through the model): these are
compliance answers that must be exact, not paraphrased.
"""
from __future__ import annotations

from pathlib import Path

import yaml

STANDING_ANSWERS_FILENAME = "standing_answers.yml"
ANSWERS_MATERIAL_FILENAME = "application_answers.md"


def standing_answers_path(base: Path) -> Path:
    return base / "profile" / STANDING_ANSWERS_FILENAME


def load_standing_answers(base: Path) -> list[dict]:
    """Parsed answers list; [] when the file is absent (recorded honestly —
    every covered phrase then stays a manual blocker)."""
    path = standing_answers_path(base)
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("answers") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("topic")]


def save_standing_answers(base: Path, answers: list[dict]) -> Path:
    """Persist the (validated) answers list back to the profile file."""
    path = standing_answers_path(base)
    payload = {
        "schema_version": "command-center.job-search.standing-answers.v1",
        "answers": answers,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")
    return path


def covered_phrases(answers: list[dict]) -> set[str]:
    """Lower-cased manual phrases neutralized by a standing answer."""
    out: set[str] = set()
    for row in answers:
        for phrase in (row.get("covers") or []):
            out.add(str(phrase).lower())
    return out


def split_detected_phrases(
    text: str, manual_phrases: list[str], answers: list[dict],
) -> tuple[list[str], list[str]]:
    """One detection implementation for classification AND re-rendering:
    (covered_hits, uncovered_hits) of manual phrases present in `text`."""
    lowered = text.lower()
    covered = covered_phrases(answers)
    covered_hits: list[str] = []
    uncovered_hits: list[str] = []
    for phrase in manual_phrases:
        if phrase.lower() in lowered:
            if phrase.lower() in covered:
                covered_hits.append(phrase)
            else:
                uncovered_hits.append(phrase)
    return sorted(set(covered_hits)), sorted(set(uncovered_hits))


def _salary_answer(row: dict, *, salary_max: int | None,
                   salary_text: str | None, currency: str | None) -> str:
    """The salary rule: target the upper end of the posted range when the
    posting names one; otherwise Geoff's standing range."""
    fallback = str(row.get("answer") or "")
    if row.get("answer_rule") != "upper_end_of_posted_range_else_answer":
        return fallback
    if salary_max:
        symbol = ("$" if not currency or currency.upper() in ("USD", "$")
                  else f"{currency} ")
        return (f"Targeting the upper end of the posted range "
                f"(~{symbol}{salary_max:,.0f}).")
    posted = (salary_text or "").strip()
    if posted:
        return (f"Targeting the upper end of the posted range ({posted}).")
    return fallback


def render_application_answers(
    answers: list[dict],
    *,
    salary_max: int | None = None,
    salary_text: str | None = None,
    currency: str | None = None,
    detected_phrases: list[str] | None = None,
) -> str:
    """application_answers.md: every standing answer (these questions appear
    on most portals), with the ones actually detected in THIS posting flagged.
    Deterministic rendering — reviewable and editable per application."""
    if not answers:
        return (
            "# Application Answers\n\n"
            "No standing answers on file (profile/standing_answers.yml is "
            "missing or empty) — every detected question routes to Geoff.\n")
    detected = {str(p).lower() for p in (detected_phrases or [])}
    lines = [
        "# Application Answers",
        "",
        "Geoff's standing answers, rendered for this application. Questions",
        "detected in this posting are marked **(asked in this posting)**.",
        "Edit per-application here, or change the defaults in",
        "profile/standing_answers.yml (Jobs settings drawer).",
        "",
    ]
    for row in answers:
        covers = {str(p).lower() for p in (row.get("covers") or [])}
        asked = bool(covers & detected)
        marker = " **(asked in this posting)**" if asked else ""
        if row.get("topic") == "salary_expectation":
            answer = _salary_answer(row, salary_max=salary_max,
                                    salary_text=salary_text,
                                    currency=currency)
        else:
            answer = str(row.get("answer") or "")
        lines.append(f"## {row.get('question', row['topic'])}{marker}")
        lines.append(answer)
        lines.append("")
    return "\n".join(lines)

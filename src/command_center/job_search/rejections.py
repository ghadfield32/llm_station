"""Capture why Geoff rejects a job, then turn the pattern into concrete
filter/scoring suggestions.

Every move to the "Rejected / Skip" lane can record a reason code + note into
an append-only JSONL under the (gitignored) data root. `rejection_report`
aggregates those reasons and, crucially, re-runs the location/language filter
on each rejection to tell "filter caught it" (working as intended) apart from
"filter let it through" (a gap worth tightening) - so the report proposes
specific changes to the search config and scoring, not vague advice.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from command_center.job_search.config import data_root, load_config
from command_center.job_search.geo_language import (
    evaluate_languages,
    evaluate_location,
)
from command_center.job_search.schemas import (
    CanonicalJob,
    JobSearchConfig,
    RemoteType,
)

# reason code -> human label. Kept small and stable so the UI can render a
# fixed picker and the report can map codes to concrete actions.
REASON_CODES: dict[str, str] = {
    "location": "Location / geography wrong",
    "remote": "Work arrangement wrong (remote/hybrid/onsite)",
    "language": "Language requirement I don't meet",
    "seniority": "Seniority mismatch (too junior / too senior)",
    "salary": "Salary too low or not listed",
    "domain": "Wrong domain / industry",
    "role_type": "Wrong kind of work",
    "company": "Company-specific reason",
    "duplicate": "Duplicate / already applied",
    "stale": "Posting expired or stale",
    "low_fit": "Low overall fit",
    "other": "Other (see note)",
}

REJECTIONS_SCHEMA = "command-center.job-search.rejections.v1"


def rejections_path(root: Path) -> Path:
    return root / "rejections" / "rejections.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_rejection(
    root: Path,
    *,
    job_key: str,
    reason_code: str,
    card_id: str | None = None,
    company: str | None = None,
    role_title: str | None = None,
    location: str | None = None,
    remote_type: str | None = None,
    fit_score: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Append one rejection record. Unknown reason codes are rejected so the
    report's code->suggestion mapping never silently loses a rejection."""
    code = (reason_code or "other").strip().lower()
    if code not in REASON_CODES:
        raise ValueError(
            f"unknown reason_code {reason_code!r}; use one of {sorted(REASON_CODES)}"
        )
    record = {
        "schema_version": REJECTIONS_SCHEMA,
        "ts": _now(),
        "job_key": job_key,
        "card_id": card_id,
        "company": company,
        "role_title": role_title,
        "location": location,
        "remote_type": remote_type,
        "fit_score": fit_score,
        "reason_code": code,
        "note": (note or "").strip() or None,
    }
    path = rejections_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def load_rejections(root: Path) -> list[dict[str, Any]]:
    path = rejections_path(root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # a truncated/corrupt trailing line must not sink the whole report
            continue
    return rows


def _job_from_rejection(row: dict[str, Any]) -> CanonicalJob | None:
    """A minimal CanonicalJob rebuilt from a rejection record, enough to re-run
    the location/language filter. Returns None when there is nothing to test."""
    location = row.get("location")
    if not location and not row.get("remote_type"):
        return None
    rt = str(row.get("remote_type") or "unknown").lower()
    remote = rt if rt in {r.value for r in RemoteType} else "unknown"
    return CanonicalJob(
        job_key=str(row.get("job_key") or "unknown"),
        company=str(row.get("company") or "Unknown"),
        role_title=str(row.get("role_title") or "Unknown"),
        normalized_company="",
        normalized_role="",
        location=str(location or "Unknown"),
        remote_type=RemoteType(remote),
        apply_url="local://rejection",
        description_text=str(row.get("note") or ""),
        last_seen_at=datetime.now(timezone.utc),
    )


def _filter_would_have_caught(
    row: dict[str, Any], config: JobSearchConfig
) -> bool | None:
    """Did the current filter already hard-exclude this location? True = the
    filter caught it (rejection confirms the filter), False = the filter let it
    through (a gap), None = not enough info to tell."""
    job = _job_from_rejection(row)
    if job is None:
        return None
    verdict, _ = evaluate_location(job, config)
    lang_verdict, _ = evaluate_languages(job, config)
    return verdict in {"mismatch", "arrangement_excluded"} or lang_verdict == "required_gap"


def _suggestions(
    rows: list[dict[str, Any]], config: JobSearchConfig
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        code = str(row.get("reason_code") or "other")
        counts[code] = counts.get(code, 0) + 1
    total = len(rows)
    out: list[dict[str, Any]] = []

    def add(priority: str, area: str, text: str, evidence: Any) -> None:
        out.append({"priority": priority, "area": area,
                    "suggestion": text, "evidence": evidence})

    # location / remote: separate "filter gap" from "filter working"
    geo_rows = [r for r in rows
                if r.get("reason_code") in {"location", "remote"}]
    if geo_rows:
        gaps = [r for r in geo_rows if _filter_would_have_caught(r, config) is False]
        gap_locs = sorted({str(r.get("location") or "?") for r in gaps})
        if gaps:
            add("high", "locations",
                f"{len(gaps)} location/arrangement rejections were NOT caught by "
                f"your current filter - tighten it. Locations seen: "
                f"{', '.join(gap_locs[:10])}. Consider narrowing "
                f"locations.regions/countries or removing an over-broad allow.",
                {"uncaught_locations": gap_locs,
                 "config_path": "locations.regions"})
        else:
            add("low", "locations",
                f"All {len(geo_rows)} location rejections were already "
                f"hard-excluded by your filter - it is doing its job; these are "
                f"likely stale cards from before the filter tightened.",
                {"count": len(geo_rows)})

    lang_rows = [r for r in rows if r.get("reason_code") == "language"]
    if lang_rows:
        gaps = [r for r in lang_rows
                if _filter_would_have_caught(r, config) is False]
        if gaps:
            add("high", "languages",
                f"{len(gaps)} language rejections slipped through - the posting's "
                f"requirement wasn't detected. Add the language phrasing to "
                f"geo_language required patterns, or add it to languages.spoken "
                f"if you actually speak it.",
                {"count": len(gaps),
                 "spoken": config.languages.spoken})

    if counts.get("salary", 0):
        add("medium", "scoring",
            f"{counts['salary']} rejections were salary-related. Raise "
            f"ranking.missing_salary_penalty, or add a minimum-salary gate to "
            f"scoring (not implemented yet - a programming change).",
            {"count": counts["salary"],
             "current_missing_salary_penalty":
                 config.ranking.missing_salary_penalty})

    if counts.get("seniority", 0):
        add("medium", "scoring",
            f"{counts['seniority']} rejections were seniority mismatches. There "
            f"is no seniority gate today - consider a negative-title list "
            f"(e.g. intern/principal) in job_categories or scoring.",
            {"count": counts["seniority"]})

    if counts.get("role_type", 0) or counts.get("domain", 0):
        n = counts.get("role_type", 0) + counts.get("domain", 0)
        add("medium", "job_categories",
            f"{n} rejections were wrong role/domain. Re-tune job_categories "
            f"keywords and role_focus so the daily search stops surfacing them.",
            {"role_type": counts.get("role_type", 0),
             "domain": counts.get("domain", 0)})

    low_fit = [r for r in rows if r.get("reason_code") == "low_fit"]
    surfaced_low = [r for r in low_fit
                    if isinstance(r.get("fit_score"), int)
                    and r["fit_score"] >= config.ranking.min_score_to_show]
    if surfaced_low:
        add("medium", "ranking",
            f"{len(surfaced_low)} low-fit rejections scored at/above your "
            f"{config.ranking.min_score_to_show} show bar - consider raising "
            f"ranking.min_score_to_show.",
            {"scores": sorted(r["fit_score"] for r in surfaced_low)})

    if not out and total:
        add("low", "general",
            f"{total} rejections recorded, no dominant pattern yet - keep "
            f"tagging reasons to build a signal.", {"total": total})
    return out


def rejection_report(root: Path | None = None,
                     cfg: JobSearchConfig | None = None) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    rows = load_rejections(base)
    counts: dict[str, int] = {}
    for row in rows:
        code = str(row.get("reason_code") or "other")
        counts[code] = counts.get(code, 0) + 1
    return {
        "operation": "rejection_report",
        "total_rejections": len(rows),
        "counts_by_reason": dict(sorted(counts.items(),
                                        key=lambda kv: (-kv[1], kv[0]))),
        "reason_labels": REASON_CODES,
        "suggestions": _suggestions(rows, config),
        "source": str(rejections_path(base)),
        "writes_performed": False,
    }

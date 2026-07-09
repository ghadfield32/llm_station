from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal

import httpx
import yaml

from command_center.job_search.config import data_root, ensure_data_dirs, load_config

LiveSource = Literal["jobicy", "remoteok", "remotive"]

JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


@dataclass(frozen=True)
class LivePosting:
    source: LiveSource
    source_id: str
    company: str
    role_title: str
    apply_url: str
    description_text: str
    location: str | None = None
    remote_type: str = "remote"
    portal: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    raw_tags: tuple[str, ...] = ()


def _clean_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "job"


def _int_or_none(value: Any) -> int | None:
    if value in {None, "", 0, "0"}:
        return None
    try:
        parsed = int(float(str(value).replace(",", "")))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _salary_text(minimum: int | None, maximum: int | None, currency: str | None) -> str | None:
    if minimum is None and maximum is None:
        return None
    prefix = "$" if (currency or "").upper() == "USD" else ""
    if minimum is not None and maximum is not None:
        return f"{prefix}{minimum:,} - {prefix}{maximum:,}"
    value = minimum if minimum is not None else maximum
    return f"{prefix}{value:,}"


def _posting_markdown(posting: LivePosting) -> str:
    frontmatter = {
        "source": posting.source,
        "source_id": posting.source_id,
        "company": posting.company,
        "role_title": posting.role_title,
        "location": posting.location,
        "remote_type": posting.remote_type,
        "portal": posting.portal or posting.source.title(),
        "apply_url": posting.apply_url,
        "salary_text": posting.salary_text,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "currency": posting.currency,
    }
    frontmatter = {key: value for key, value in frontmatter.items() if value not in {None, ""}}
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + posting.description_text + "\n"


def _skip_reason(record: dict[str, Any], missing: Iterable[str]) -> dict[str, Any]:
    return {
        "source_id": str(record.get("id") or record.get("source_id") or ""),
        "reason": "missing required fields: " + ", ".join(missing),
    }


def parse_jobicy_jobs(payload: dict[str, Any]) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    postings: list[LivePosting] = []
    skipped: list[dict[str, Any]] = []
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("Jobicy payload is missing a jobs list")
    for record in jobs:
        if not isinstance(record, dict):
            skipped.append({"source_id": "", "reason": "record is not an object"})
            continue
        company = str(record.get("companyName") or "").strip()
        title = str(record.get("jobTitle") or "").strip()
        url = str(record.get("url") or "").strip()
        missing = [name for name, value in {"companyName": company, "jobTitle": title, "url": url}.items() if not value]
        if missing:
            skipped.append(_skip_reason(record, missing))
            continue
        salary_min = _int_or_none(record.get("annualSalaryMin"))
        salary_max = _int_or_none(record.get("annualSalaryMax"))
        currency = str(record.get("salaryCurrency") or "").strip() or None
        description = _clean_html(record.get("jobDescription") or record.get("jobExcerpt"))
        if not description:
            skipped.append(_skip_reason(record, ["jobDescription"]))
            continue
        postings.append(
            LivePosting(
                source="jobicy",
                source_id=str(record.get("id") or url),
                company=company,
                role_title=title,
                apply_url=url,
                description_text=description,
                location=str(record.get("jobGeo") or "").strip() or None,
                salary_text=_salary_text(salary_min, salary_max, currency),
                salary_min=salary_min,
                salary_max=salary_max,
                currency=currency,
                raw_tags=tuple(str(tag) for tag in record.get("jobIndustry") or []),
            )
        )
    return postings, skipped


def parse_remoteok_jobs(payload: list[dict[str, Any]]) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    postings: list[LivePosting] = []
    skipped: list[dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, dict) or "legal" in record:
            continue
        company = str(record.get("company") or "").strip()
        title = str(record.get("position") or "").strip()
        url = str(record.get("url") or "").strip()
        missing = [name for name, value in {"company": company, "position": title, "url": url}.items() if not value]
        if missing:
            skipped.append(_skip_reason(record, missing))
            continue
        description = _clean_html(record.get("description"))
        if not description:
            skipped.append(_skip_reason(record, ["description"]))
            continue
        salary_min = _int_or_none(record.get("salary_min"))
        salary_max = _int_or_none(record.get("salary_max"))
        postings.append(
            LivePosting(
                source="remoteok",
                source_id=str(record.get("id") or url),
                company=company,
                role_title=title,
                apply_url=url,
                description_text=description,
                location=str(record.get("location") or "").strip() or None,
                salary_text=_salary_text(salary_min, salary_max, "USD"),
                salary_min=salary_min,
                salary_max=salary_max,
                currency="USD" if salary_min or salary_max else None,
                raw_tags=tuple(str(tag) for tag in record.get("tags") or []),
            )
        )
    return postings, skipped


def parse_remotive_jobs(payload: dict[str, Any]) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    postings: list[LivePosting] = []
    skipped: list[dict[str, Any]] = []
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("Remotive payload is missing a jobs list")
    for record in jobs:
        if not isinstance(record, dict):
            skipped.append({"source_id": "", "reason": "record is not an object"})
            continue
        company = str(record.get("company_name") or "").strip()
        title = str(record.get("title") or "").strip()
        url = str(record.get("url") or "").strip()
        missing = [name for name, value in {"company_name": company, "title": title, "url": url}.items() if not value]
        if missing:
            skipped.append(_skip_reason(record, missing))
            continue
        description = _clean_html(record.get("description"))
        if not description:
            skipped.append(_skip_reason(record, ["description"]))
            continue
        salary_text = str(record.get("salary") or "").strip() or None
        postings.append(
            LivePosting(
                source="remotive",
                source_id=str(record.get("id") or url),
                company=company,
                role_title=title,
                apply_url=url,
                description_text=description,
                location=str(record.get("candidate_required_location") or "").strip() or None,
                portal="Remotive",
                salary_text=salary_text,
                raw_tags=tuple(
                    str(tag)
                    for tag in [
                        record.get("category"),
                        record.get("job_type"),
                    ]
                    if tag
                ),
            )
        )
    return postings, skipped


def fetch_jobicy(
    tag: str | None = None,
    *,
    industry: str | None = None,
    count: int,
    timeout: float = 20.0,
) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    params: dict[str, str | int] = {"count": count}
    if tag:
        params["tag"] = tag
    if industry:
        params["industry"] = industry
    with httpx.Client(timeout=timeout, headers={"User-Agent": "llm-station-job-search/1.0"}) as client:
        response = client.get(JOBICY_URL, params=params)
        response.raise_for_status()
        return parse_jobicy_jobs(response.json())


def fetch_remoteok(*, timeout: float = 20.0) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    with httpx.Client(timeout=timeout, headers={"User-Agent": "llm-station-job-search/1.0"}) as client:
        response = client.get(REMOTEOK_URL)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("RemoteOK payload is not a list")
        return parse_remoteok_jobs(payload)


def fetch_remotive(search: str, *, timeout: float = 20.0) -> tuple[list[LivePosting], list[dict[str, Any]]]:
    with httpx.Client(timeout=timeout, headers={"User-Agent": "llm-station-job-search/1.0"}) as client:
        response = client.get(REMOTIVE_URL, params={"search": search})
        response.raise_for_status()
        return parse_remotive_jobs(response.json())


def _jobicy_query_error(exc: httpx.HTTPStatusError) -> dict[str, Any]:
    response = exc.response
    body = response.text.strip()
    return {
        "source_id": "",
        "reason": f"jobicy query failed: HTTP {response.status_code}",
        "status_code": response.status_code,
        "body": body[:500],
    }


def write_posting(posting: LivePosting, *, root: Path, run_date: date | None = None) -> Path:
    day = run_date or date.today()
    folder = root / "source_cache" / "live_postings" / f"{posting.source}_{day.isoformat()}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_slug(posting.company)}_{_slug(posting.role_title)}_{_slug(posting.source_id)[:16]}.md"
    path.write_text(_posting_markdown(posting), encoding="utf-8")
    return path


def discover_live_postings(
    *,
    sources: Iterable[LiveSource],
    tags: Iterable[str],
    industries: Iterable[str] = (),
    count: int,
    root: Path | None = None,
    write: bool = True,
    run_date: date | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    base = root or data_root(cfg)
    ensure_data_dirs(base)
    all_postings: list[LivePosting] = []
    skipped: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    tag_list = list(tags)
    industry_list = list(industries)

    for source in sources:
        if source == "jobicy":
            for tag in tag_list:
                try:
                    postings, source_skipped = fetch_jobicy(tag, count=count)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {400, 404}:
                        raise
                    error = _jobicy_query_error(exc)
                    source_rows.append({
                        "source": source,
                        "query_type": "tag",
                        "tag": tag,
                        "postings": 0,
                        "skipped": 1,
                        "error": error["reason"],
                    })
                    skipped.append({"source": source, "tag": tag, **error})
                    continue
                source_rows.append({
                    "source": source,
                    "query_type": "tag",
                    "tag": tag,
                    "postings": len(postings),
                    "skipped": len(source_skipped),
                })
                skipped.extend({"source": source, "tag": tag, **row} for row in source_skipped)
                for posting in postings:
                    if posting.apply_url not in seen_urls:
                        seen_urls.add(posting.apply_url)
                        all_postings.append(posting)
            for industry in industry_list:
                try:
                    postings, source_skipped = fetch_jobicy(industry=industry, count=count)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {400, 404}:
                        raise
                    error = _jobicy_query_error(exc)
                    source_rows.append({
                        "source": source,
                        "query_type": "industry",
                        "industry": industry,
                        "postings": 0,
                        "skipped": 1,
                        "error": error["reason"],
                    })
                    skipped.append({"source": source, "industry": industry, **error})
                    continue
                source_rows.append({
                    "source": source,
                    "query_type": "industry",
                    "industry": industry,
                    "postings": len(postings),
                    "skipped": len(source_skipped),
                })
                skipped.extend({"source": source, "industry": industry, **row} for row in source_skipped)
                for posting in postings:
                    if posting.apply_url not in seen_urls:
                        seen_urls.add(posting.apply_url)
                        all_postings.append(posting)
        elif source == "remoteok":
            postings, source_skipped = fetch_remoteok()
            source_rows.append({"source": source, "tag": None, "postings": len(postings), "skipped": len(source_skipped)})
            skipped.extend({"source": source, **row} for row in source_skipped)
            for posting in postings:
                if posting.apply_url not in seen_urls:
                    seen_urls.add(posting.apply_url)
                    all_postings.append(posting)
        elif source == "remotive":
            searches = tag_list or [""]
            for search in searches:
                postings, source_skipped = fetch_remotive(search)
                source_rows.append({
                    "source": source,
                    "query_type": "search",
                    "search": search,
                    "postings": len(postings),
                    "skipped": len(source_skipped),
                })
                skipped.extend({"source": source, "search": search, **row} for row in source_skipped)
                for posting in postings:
                    if posting.apply_url not in seen_urls:
                        seen_urls.add(posting.apply_url)
                        all_postings.append(posting)
        else:
            raise RuntimeError(f"unsupported live source: {source}")

    paths = [write_posting(posting, root=base, run_date=run_date) for posting in all_postings] if write else []
    return {
        "sources": source_rows,
        "postings_found": len(all_postings),
        "posting_paths": [str(path) for path in paths],
        "skipped": skipped,
    }

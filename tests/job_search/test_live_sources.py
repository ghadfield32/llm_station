from __future__ import annotations

from datetime import date

import httpx
import pytest

from command_center.job_search.live_sources import (
    discover_live_postings,
    parse_jobicy_jobs,
    parse_remotive_jobs,
    parse_remoteok_jobs,
)


def test_parse_jobicy_jobs_requires_real_application_fields():
    postings, skipped = parse_jobicy_jobs(
        {
            "jobs": [
                {
                    "id": 123,
                    "companyName": "Meta",
                    "jobTitle": "Data Scientist",
                    "url": "https://jobicy.com/jobs/123-data-scientist",
                    "jobGeo": "Anywhere",
                    "jobDescription": "<p>Python, SQL, experimentation.</p>",
                    "annualSalaryMin": "150000",
                    "annualSalaryMax": "190000",
                    "salaryCurrency": "USD",
                    "jobIndustry": ["Data Science"],
                },
                {"id": 456, "companyName": "", "jobTitle": "Broken"},
            ]
        }
    )

    assert len(postings) == 1
    assert postings[0].company == "Meta"
    assert postings[0].salary_text == "$150,000 - $190,000"
    assert "Python, SQL" in postings[0].description_text
    assert skipped[0]["reason"] == "missing required fields: companyName, url"


def test_parse_remoteok_jobs_skips_legal_header_and_bad_records():
    postings, skipped = parse_remoteok_jobs(
        [
            {"legal": "terms"},
            {
                "id": 789,
                "company": "Brigit",
                "position": "Lead Data Scientist",
                "url": "https://remoteok.com/remote-jobs/789",
                "description": "<p>Python and ML leadership.</p>",
                "location": "USA",
                "salary_min": 180000,
                "salary_max": 220000,
                "tags": ["python"],
            },
            {"id": 790, "company": "Missing URL", "position": "Analyst"},
        ]
    )

    assert len(postings) == 1
    assert postings[0].source == "remoteok"
    assert postings[0].currency == "USD"
    assert skipped[0]["reason"] == "missing required fields: url"


def test_parse_remotive_jobs_requires_real_application_fields():
    postings, skipped = parse_remotive_jobs(
        {
            "jobs": [
                {
                    "id": 2090986,
                    "company_name": "Lemon.io",
                    "title": "Senior AI Engineer",
                    "url": "https://remotive.com/remote-jobs/artificial-intelligence/senior-ai-engineer-2090986",
                    "description": "<p>Python, LLMs, production ML.</p>",
                    "candidate_required_location": "Northern America",
                    "category": "Artificial Intelligence",
                    "salary": "$120k-$180k",
                },
                {"id": 2, "company_name": "", "title": "Broken"},
            ]
        }
    )

    assert len(postings) == 1
    assert postings[0].source == "remotive"
    assert postings[0].portal == "Remotive"
    assert postings[0].salary_text == "$120k-$180k"
    assert "production ML" in postings[0].description_text
    assert skipped[0]["reason"] == "missing required fields: company_name, url"


def test_discover_live_postings_writes_deduped_markdown(tmp_path, monkeypatch):
    def fake_fetch_jobicy(tag: str, *, count: int, timeout: float = 20.0):
        del tag, count, timeout
        return parse_jobicy_jobs(
            {
                "jobs": [
                    {
                        "id": 123,
                        "companyName": "Meta",
                        "jobTitle": "Data Scientist",
                        "url": "https://jobicy.com/jobs/123-data-scientist",
                        "jobDescription": "Python, SQL, experimentation.",
                    }
                ]
            }
        )

    monkeypatch.setattr("command_center.job_search.live_sources.fetch_jobicy", fake_fetch_jobicy)

    result = discover_live_postings(
        sources=["jobicy"],
        tags=["python", "sql"],
        count=10,
        root=tmp_path,
        write=True,
        run_date=date(2026, 7, 9),
    )

    assert result["postings_found"] == 1
    assert len(result["posting_paths"]) == 1
    path = tmp_path / "source_cache" / "live_postings" / "jobicy_2026-07-09"
    assert path.exists()
    assert "apply_url: https://jobicy.com/jobs/123-data-scientist" in path.joinpath(
        "meta_data_scientist_123.md"
    ).read_text(encoding="utf-8")


def test_discover_live_postings_supports_remotive_searches(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_fetch_remotive(search: str, *, timeout: float = 20.0):
        del timeout
        calls.append(search)
        return parse_remotive_jobs(
            {
                "jobs": [
                    {
                        "id": 2090986,
                        "company_name": "Lemon.io",
                        "title": "Senior AI Engineer",
                        "url": "https://remotive.com/remote-jobs/artificial-intelligence/senior-ai-engineer-2090986",
                        "description": "Python, LLMs, production ML.",
                    }
                ]
            }
        )

    monkeypatch.setattr("command_center.job_search.live_sources.fetch_remotive", fake_fetch_remotive)

    result = discover_live_postings(
        sources=["remotive"],
        tags=["data", "ai"],
        count=10,
        root=tmp_path,
        write=False,
    )

    assert calls == ["data", "ai"]
    assert result["postings_found"] == 1
    assert result["sources"] == [
        {"source": "remotive", "query_type": "search", "search": "data", "postings": 1, "skipped": 0},
        {"source": "remotive", "query_type": "search", "search": "ai", "postings": 1, "skipped": 0},
    ]


def test_discover_live_postings_supports_jobicy_industries(tmp_path, monkeypatch):
    calls: list[tuple[str | None, str | None]] = []

    def fake_fetch_jobicy(
        tag: str | None = None,
        *,
        industry: str | None = None,
        count: int,
        timeout: float = 20.0,
    ):
        del count, timeout
        calls.append((tag, industry))
        return parse_jobicy_jobs(
            {
                "jobs": [
                    {
                        "id": 3037,
                        "companyName": "Analytics Co",
                        "jobTitle": "Analytics Engineer",
                        "url": f"https://jobicy.com/jobs/{industry}-analytics-engineer",
                        "jobDescription": "Python, SQL, dbt, Airflow.",
                    }
                ]
            }
        )

    monkeypatch.setattr("command_center.job_search.live_sources.fetch_jobicy", fake_fetch_jobicy)

    result = discover_live_postings(
        sources=["jobicy"],
        tags=[],
        industries=["data-science", "engineering"],
        count=10,
        root=tmp_path,
        write=False,
    )

    assert calls == [(None, "data-science"), (None, "engineering")]
    assert result["postings_found"] == 2
    assert result["sources"] == [
        {
            "source": "jobicy",
            "query_type": "industry",
            "industry": "data-science",
            "postings": 1,
            "skipped": 0,
        },
        {
            "source": "jobicy",
            "query_type": "industry",
            "industry": "engineering",
            "postings": 1,
            "skipped": 0,
        },
    ]


def test_discover_live_postings_records_invalid_jobicy_tag_and_continues(tmp_path, monkeypatch):
    def fake_fetch_jobicy(
        tag: str | None = None,
        *,
        industry: str | None = None,
        count: int,
        timeout: float = 20.0,
    ):
        del industry, count, timeout
        if tag == "bad-tag":
            request = httpx.Request("GET", "https://jobicy.com/api/v2/remote-jobs?tag=bad-tag")
            response = httpx.Response(404, request=request, text='{"success":false,"error":"bad tag"}')
            raise httpx.HTTPStatusError("bad tag", request=request, response=response)
        return parse_jobicy_jobs(
            {
                "jobs": [
                    {
                        "id": 123,
                        "companyName": "Meta",
                        "jobTitle": "Data Scientist",
                        "url": "https://jobicy.com/jobs/123-data-scientist",
                        "jobDescription": "Python, SQL, experimentation.",
                    }
                ]
            }
        )

    monkeypatch.setattr("command_center.job_search.live_sources.fetch_jobicy", fake_fetch_jobicy)

    result = discover_live_postings(
        sources=["jobicy"],
        tags=["bad-tag", "python"],
        count=10,
        root=tmp_path,
        write=False,
    )

    assert result["postings_found"] == 1
    assert result["sources"][0]["error"] == "jobicy query failed: HTTP 404"
    assert result["skipped"][0]["tag"] == "bad-tag"


def test_jobicy_payload_must_have_jobs_list():
    with pytest.raises(RuntimeError, match="jobs list"):
        parse_jobicy_jobs({"unexpected": []})

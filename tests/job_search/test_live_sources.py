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


def test_get_json_retries_on_429_then_succeeds(monkeypatch):
    """The daily discovery fires one request per keyword tag; a 429 must be
    waited-out and retried (honoring Retry-After), not aborted."""
    from command_center.job_search import live_sources as ls

    calls = {"n": 0}

    class _Resp:
        def __init__(self, code, data=None, headers=None):
            self.status_code = code
            self._data = data or {}
            self.headers = headers or {}
            self.text = ""

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("x", request=None, response=self)

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(429, headers={"Retry-After": "0"})
            return _Resp(200, {"jobs": []})

    monkeypatch.setattr(ls.httpx, "Client", _Client)
    monkeypatch.setattr(ls.time, "sleep", lambda *a: None)
    out = ls._get_json("http://x")
    assert calls["n"] == 2          # retried once after the 429
    assert out == {"jobs": []}


def test_get_json_raises_after_persistent_429(monkeypatch):
    from command_center.job_search import live_sources as ls

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "0"}
        text = ""

        def raise_for_status(self):
            raise httpx.HTTPStatusError("x", request=None, response=self)

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            return _Resp()

    monkeypatch.setattr(ls.httpx, "Client", _Client)
    monkeypatch.setattr(ls.time, "sleep", lambda *a: None)
    with pytest.raises(httpx.HTTPStatusError):
        ls._get_json("http://x", max_retries=3)

"""Board-owned Growth OS inputs and provenance-labelled research enrichment."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.parse

import pytest
import yaml
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "growth_os"))
# feedparser is a Growth OS container dependency, not a root test dependency.
# This unit exercises only the pure link classifier.
sys.modules.setdefault("feedparser", SimpleNamespace())

from growthos.config import (  # noqa: E402
    ProjectsConfig, load_config, load_research_projects,
)
from growthos.enrich import _input_sha256, suggest  # noqa: E402
from growthos.models import CuratedItem  # noqa: E402
from growthos.score import rank_and_trim  # noqa: E402
from growthos.sources.arxiv import (  # noqa: E402
    _build_query, _source_links, fetch as fetch_arxiv,
)
from growthos.sources.github import (  # noqa: E402
    fetch as fetch_github, github_query_for_topic,
)


def test_research_fit_uses_the_same_repo_registry_as_cockpit_onboarding():
    autonomy = yaml.safe_load(
        (ROOT / "configs" / "autonomy.yaml").read_text(encoding="utf-8"))
    expected = [
        row["repo_id"] for row in autonomy["repo_manifests"]
    ]

    projects = load_research_projects(ROOT / "configs" / "autonomy.yaml")

    assert [project.name for project in projects] == expected
    assert all(project.remote_url for project in projects)
    assert all(project.location_ref for project in projects)


@pytest.mark.parametrize(
    "projects",
    [
        [],
        [{"name": "same", "repo": "a"}, {"name": "same", "repo": "b"}],
        [{"name": "x" * 121, "repo": "a"}],
    ],
)
def test_observation_project_registry_cannot_exceed_analysis_contract(projects):
    with pytest.raises(ValueError):
        ProjectsConfig.model_validate({
            "schema_version": "growthos.projects.v1",
            "projects": projects,
        })


def _domain_copy(tmp_path: Path) -> tuple[Path, dict]:
    data = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    path = tmp_path / "domain_surfaces.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path, data


def test_growthos_resolves_paper_and_repo_inputs_from_board_registry(tmp_path):
    path, _ = _domain_copy(tmp_path)

    config = load_config(
        ROOT / "growth_os" / "config" / "sources.yaml",
        domain_surfaces_path=path,
    )

    expected_topics = [
        "Bayesian forecasting",
        "Sports analytics",
        "Player tracking computer vision",
        "LLM agents",
        "MLOps and feature stores",
    ]
    assert config.sources.arxiv.review_topics == expected_topics
    assert config.sources.github.review_topics == expected_topics
    assert config.sources.github.top_n == 10


def test_readable_topics_compile_to_provider_syntax_only_inside_adapters(tmp_path):
    path, _ = _domain_copy(tmp_path)
    config = load_config(
        ROOT / "growth_os" / "config" / "sources.yaml",
        domain_surfaces_path=path,
    )

    arxiv_query = _build_query(config.sources.arxiv)
    assert "all:bayesian AND all:forecasting" in arxiv_query
    assert "all:Bayesian" not in config.sources.arxiv.review_topics
    assert github_query_for_topic("Agent evaluation") == (
        "agent evaluation in:name,description,readme")


class _FailedSourceResponse:
    text = "upstream failure"

    def raise_for_status(self):
        request = httpx.Request("GET", "https://source.test")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError(
            "source unavailable", request=request, response=response)


def test_source_adapter_failures_propagate_instead_of_claiming_empty_success(
    monkeypatch, tmp_path,
):
    path, _ = _domain_copy(tmp_path)
    config = load_config(
        ROOT / "growth_os" / "config" / "sources.yaml",
        domain_surfaces_path=path,
    )
    monkeypatch.setattr(
        "growthos.sources.arxiv.httpx.get",
        lambda *_args, **_kwargs: _FailedSourceResponse(),
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_arxiv(config.sources.arxiv)

    monkeypatch.setattr(
        "growthos.sources.github.httpx.get",
        lambda *_args, **_kwargs: _FailedSourceResponse(),
    )
    with pytest.raises(RuntimeError, match="GitHub research queries failed"):
        fetch_github(config.sources.github)


class _GithubResponse:
    def __init__(self, item: dict):
        self.item = item

    def raise_for_status(self):
        return None

    def json(self):
        return {"items": [self.item]}


def test_github_deduplicates_repos_and_keeps_every_matching_review_topic(
    monkeypatch, tmp_path,
):
    path, _ = _domain_copy(tmp_path)
    config = load_config(
        ROOT / "growth_os" / "config" / "sources.yaml",
        domain_surfaces_path=path,
    )
    cfg = config.sources.github.model_copy(update={
        "review_topics": ["Agent evaluation", "LLM agents"],
    })
    item = {
        "html_url": "https://github.com/example/agent-eval",
        "name": "agent-eval",
        "description": "Evaluate LLM agents.",
        "topics": ["agents", "evaluation"],
        "updated_at": "2026-07-16T12:00:00Z",
        "pushed_at": "2026-07-16T12:00:00Z",
        "owner": {"login": "example"},
        "stargazers_count": 100,
        "forks_count": 10,
        "open_issues_count": 2,
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "default_branch": "main",
        "archived": False,
        "homepage": "https://example.org/agent-eval",
    }
    monkeypatch.setattr(
        "growthos.sources.github.httpx.get",
        lambda *_args, **_kwargs: _GithubResponse(item),
    )

    rows = fetch_github(cfg)

    assert len(rows) == 1
    assert rows[0].extra["review_topics"] == ["Agent evaluation", "LLM agents"]


def test_arxiv_isolates_topic_queries_paces_requests_and_merges_membership(
    monkeypatch, tmp_path,
):
    path, _ = _domain_copy(tmp_path)
    config = load_config(
        ROOT / "growth_os" / "config" / "sources.yaml",
        domain_surfaces_path=path,
    )
    cfg = config.sources.arxiv.model_copy(update={
        "categories": ["cs.AI"],
        "review_topics": ["Agent evaluation", "LLM agents"],
    })
    entry = SimpleNamespace(
        id="https://arxiv.org/abs/2607.12345",
        title="A reusable software toolkit",
        summary="A controlled systems study.",
        published_parsed=(*date.today().timetuple()[:3], 0, 0, 0),
        authors=[SimpleNamespace(name="A. Researcher")],
        tags=[SimpleNamespace(term="cs.AI")],
        links=[],
    )
    urls = []
    sleeps = []

    class Response:
        text = "valid atom"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "growthos.sources.arxiv.httpx.get",
        lambda url, **_kwargs: urls.append(url) or Response(),
    )
    monkeypatch.setattr(
        "growthos.sources.arxiv.feedparser.parse",
        lambda _raw: SimpleNamespace(bozo=False, entries=[entry]),
        raising=False,
    )
    monkeypatch.setattr(
        "growthos.sources.arxiv.time.sleep", lambda seconds: sleeps.append(seconds))

    rows = fetch_arxiv(cfg)

    assert len(urls) == 3
    queries = [
        urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["search_query"][0]
        for url in urls
    ]
    assert queries == [
        "(cat:cs.AI)",
        "all:agent AND all:evaluation",
        "all:llm AND all:agents",
    ]
    assert sleeps == [3, 3]
    assert len(rows) == 1
    assert rows[0].extra["review_topics"] == ["Agent evaluation", "LLM agents"]


def test_selected_review_topic_remains_eligible_outside_static_profile():
    item = CuratedItem(
        kind="repo", external_id="new-topic", title="Novel compiler tooling",
        url="https://github.com/example/new-topic",
        extra={"review_topics": ["Compiler verification"]},
    )
    old_one = CuratedItem(
        kind="repo", external_id="old-one", title="Old profile favorite",
        url="https://github.com/example/old-one",
    )
    old_two = CuratedItem(
        kind="repo", external_id="old-two", title="Another profile favorite",
        url="https://github.com/example/old-two",
    )

    def scorer(rows):
        for row in rows:
            row.score = {"old-one": 10.0, "old-two": 9.0}.get(row.external_id, 0.0)

    kept = rank_and_trim(
        [old_one, old_two, item], scorer, 2)

    assert item in kept
    assert old_one in kept
    assert old_two not in kept
    assert item.score > 0


def test_ranking_reserves_one_candidate_for_every_available_review_topic():
    items = [
        CuratedItem(
            kind="repo", external_id=f"repo-{index}", title=f"Repo {index}",
            url=f"https://github.com/example/repo-{index}",
            extra={"review_topics": [topic]},
        )
        for index, topic in enumerate(("Topic one", "Topic two", "Topic three"), 1)
    ]

    kept = rank_and_trim(
        items,
        lambda rows: [setattr(row, "score", float(4 - i)) for i, row in enumerate(rows, 1)],
        3,
    )

    assert {row.extra["review_topics"][0] for row in kept} == {
        "Topic one", "Topic two", "Topic three"}


def test_enabled_source_top_n_must_cover_every_configured_topic(tmp_path):
    path, data = _domain_copy(tmp_path)
    paper = next(row for row in data["domains"] if row["domain_id"] == "paper")
    paper["intake"]["parameters"].update({
        "top_n": 2,
        "review_topics": ["Topic one", "Topic two", "Topic three"],
    })
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="cover all configured review_topics"):
        load_config(
            ROOT / "growth_os" / "config" / "sources.yaml",
            domain_surfaces_path=path,
        )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda params: params.update(categories=["cs.LG", "cs.LG"]), "unique"),
        (lambda params: params.update(categories=["cs.LG OR all:agent"]), "category ids"),
        (lambda params: params.update(top_n=0), "at least 1"),
    ],
)
def test_growthos_rejects_unsafe_or_ambiguous_source_parameters(
    tmp_path, mutation, message,
):
    path, data = _domain_copy(tmp_path)
    paper = next(row for row in data["domains"] if row["domain_id"] == "paper")
    mutation(paper["intake"]["parameters"])
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(
            ROOT / "growth_os" / "config" / "sources.yaml",
            domain_surfaces_path=path,
        )


def test_growthos_fails_closed_for_missing_or_duplicate_input_authority(tmp_path):
    path, data = _domain_copy(tmp_path)
    paper = next(
        row for row in data["domains"] if row["domain_id"] == "paper")
    paper["intake"]["producer"] = "manual"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one 'growth_os_arxiv'"):
        load_config(
            ROOT / "growth_os" / "config" / "sources.yaml",
            domain_surfaces_path=path,
        )

    _, moved = _domain_copy(tmp_path)
    paper = next(row for row in moved["domains"] if row["domain_id"] == "paper")
    target = next(
        row for row in moved["domains"] if row["domain_id"] == "generic_task")
    target["intake"] = paper["intake"]
    paper["intake"] = {
        "producer": "manual",
        "mode": "manual",
        "summary": "Wrong owner test",
        "schedule": "on demand",
        "source_refs": [],
        "parameters": {},
        "editable": True,
    }
    path.write_text(yaml.safe_dump(moved, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="must be owned by domain 'paper'"):
        load_config(
            ROOT / "growth_os" / "config" / "sources.yaml",
            domain_surfaces_path=path,
        )

    duplicate = tmp_path / "sources.yaml"
    duplicate.write_text(
        yaml.safe_dump({"sources": {
            "signals": {"enabled": False},
            "arxiv": {"queries": ["silently competing authority"]},
        }}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="owned by configs/domain_surfaces.yaml"):
        load_config(duplicate, domain_surfaces_path=ROOT / "configs" / "domain_surfaces.yaml")


def test_arxiv_source_links_are_source_derived_and_split_code_hosts():
    entry = SimpleNamespace(
        links=[
            SimpleNamespace(href="https://arxiv.org/abs/2607.00001"),
            SimpleNamespace(href="https://github.com/example/paper-code"),
            SimpleNamespace(href="https://example.org/project"),
        ],
        arxiv_comment="Code mirror: https://gitlab.com/example/paper-code.",
    )

    code, related = _source_links(entry, "https://arxiv.org/abs/2607.00001")

    assert code == [
        "https://github.com/example/paper-code",
        "https://gitlab.com/example/paper-code",
    ]
    assert related == [
        "https://github.com/example/paper-code",
        "https://example.org/project",
        "https://gitlab.com/example/paper-code",
    ]


class _Response:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": self._content}}


class _Client:
    def __init__(self, content: str):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, *_args, **_kwargs):
        return _Response(self.content)


class _SequenceClient:
    def __init__(self, contents: list[str]):
        self.contents = iter(contents)
        self.payloads: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, *_args, **kwargs):
        self.payloads.append(kwargs["json"])
        return _Response(next(self.contents))


def _valid_analysis(**overrides) -> dict:
    value = {
        "useful_for_us": "Useful for evaluating llm_station agent traces.",
        "pros": ["Has a bounded evaluation protocol"],
        "cons": ["Repository compatibility is not yet verified"],
        "key_details": ["Compares tool-use traces"],
        "implementation_notes": ["Start with one offline trace fixture"],
        "work_areas": ["Agent evaluation"],
        "use_cases": ["Trace reliability testing"],
        "research_priority": "high",
        "relevance_score": 94,
        "potential_impact_score": 84,
        "implementation_readiness_score": 72,
        "evidence_confidence_score": 78,
        "estimated_effort": "small",
        "project_fits": [{
            "project": "llm_station",
            "fit_score": 94,
            "item_evidence": "The paper evaluates tool-using agent traces.",
            "project_capability": "LLM and agent model routing and evaluation",
            "why": "The paper evaluates tool-using agent traces.",
            "suggested_application": "Add one offline agent trace benchmark.",
        }],
    }
    value.update(overrides)
    return value


def test_research_analysis_is_structured_labelled_and_does_not_invent_links(
    monkeypatch,
):
    item = CuratedItem(
        kind="paper",
        external_id="2607.00001",
        title="Auditable agents",
        url="https://arxiv.org/abs/2607.00001",
        summary="A controlled evaluation of tool-using agents.",
        topics=["cs.AI"],
        extra={
            "code_links": ["https://github.com/example/auditable-agents"],
            "related_links": ["https://example.org/auditable-agents"],
            "analysis_error_code": "old_failure",
        },
    )
    content = json.dumps(_valid_analysis())
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client",
        lambda **_kwargs: _Client(content),
    )
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    completed = suggest(
        [item],
        "http://ollama.test",
        "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    )

    assert completed == 1
    assert item.extra["analysis_status"] == "complete"
    assert item.extra["analysis_origin"] == "local_model"
    assert item.extra["analysis_model"] == "resolved-local-model"
    assert len(item.extra["analysis_input_sha256"]) == 64
    assert "analysis_error_code" not in item.extra
    assert item.extra["pros"] == ["Has a bounded evaluation protocol"]
    assert item.extra["relevance_score"] == 94
    assert item.extra["best_project"] == "llm_station"
    assert item.extra["best_project_fit_score"] == 94
    assert item.extra["applicable_projects"] == ["llm_station"]
    assert "llm_station · 94/100" in item.extra["project_fit_summary"]
    assert item.extra["analysis_schema_version"] == (
        "growthos.research-analysis.v5")
    assert item.extra["code_links"] == [
        "https://github.com/example/auditable-agents"]
    assert item.extra["related_links"] == [
        "https://example.org/auditable-agents"]


def test_research_priority_is_calibrated_from_scores(monkeypatch):
    item = CuratedItem(
        kind="paper",
        external_id="2607.00002",
        title="Weakly aligned result",
        url="https://arxiv.org/abs/2607.00002",
        summary="A result outside the registered projects' main work.",
    )
    content = json.dumps(_valid_analysis(
        research_priority="high",
        relevance_score=10,
        potential_impact_score=40,
        implementation_readiness_score=20,
        evidence_confidence_score=60,
        project_fits=[{
            "project": "llm_station",
            "fit_score": 10,
            "item_evidence": "The result is outside the registered work.",
            "project_capability": "no direct match",
            "why": "The supplied summary establishes no direct integration seam.",
            "suggested_application": "Keep as background reading only.",
        }],
    ))
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client",
        lambda **_kwargs: _Client(content),
    )
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 1
    assert item.extra["research_priority"] == "watch"


def test_unavailable_enrichment_is_loud_and_preserves_source_metadata():
    item = CuratedItem(
        kind="repo",
        external_id="https://github.com/example/repo",
        title="repo",
        url="https://github.com/example/repo",
        extra={"code_links": ["https://github.com/example/repo"]},
    )

    assert suggest(
        [item], "", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 0
    assert item.extra["analysis_status"] == "unavailable"
    assert item.extra["analysis_error_code"] == "ollama_not_configured"
    assert item.extra["code_links"] == ["https://github.com/example/repo"]


def test_schema_invalid_analysis_gets_one_grounded_corrective_retry(monkeypatch):
    item = CuratedItem(
        kind="repo", external_id="https://github.com/example/taipy",
        title="taipy", url="https://github.com/example/taipy",
        summary="A Python application framework.",
    )
    invalid = json.dumps(_valid_analysis(
        useful_for_us="Could support internal data applications.",
        pros=["Python integration"],
        cons=["   "],
        key_details=["Application framework"],
        implementation_notes=["Evaluate with one offline prototype"],
    ))
    valid = json.dumps(_valid_analysis(
        useful_for_us="Could support internal data applications.",
        pros=["Python integration"],
        cons=["Compatibility with the current stack is unverified"],
        key_details=["Application framework"],
        implementation_notes=["Evaluate with one offline prototype"],
    ))
    client = _SequenceClient([invalid, valid])
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 1
    assert len(client.payloads) == 2
    retry_prompt = client.payloads[1]["messages"][0]["content"]
    assert "previous response failed" in retry_prompt
    assert "every required array" in retry_prompt
    assert item.extra["analysis_status"] == "complete"
    assert item.extra["cons"] == [
        "Compatibility with the current stack is unverified"]
    assert item.extra["analysis_input_sha256"] == _input_sha256(
        item, model="resolved-local-model", prompt=retry_prompt)


def test_analysis_retries_until_every_registered_folder_has_explained_fit(
    monkeypatch,
):
    item = CuratedItem(
        kind="paper", external_id="2607.0042", title="Folder-aware research",
        url="https://arxiv.org/abs/2607.0042",
        summary="A controlled agent trace evaluation.",
    )
    missing_folder = _valid_analysis(project_fits=[{
        "project": "unknown_project",
        "fit_score": 92,
        "item_evidence": "The paper discusses evaluation.",
        "project_capability": "no direct match",
        "why": "It sounds relevant.",
        "suggested_application": "Try it.",
    }])
    valid = _valid_analysis()
    client = _SequenceClient([
        json.dumps(missing_folder), json.dumps(valid),
    ])
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 1
    assert len(client.payloads) == 2
    assert "cover exactly these registered projects" in (
        client.payloads[1]["messages"][0]["content"])
    assert [fit["project"] for fit in item.extra["project_fits"]] == [
        "llm_station"]


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("relevance_score", "91"),
        ("potential_impact_score", True),
        ("implementation_readiness_score", 72.0),
        ("project_fit_score", "94"),
    ],
)
def test_analysis_strict_scores_trigger_corrective_retry(
    monkeypatch, field, invalid_value,
):
    item = CuratedItem(
        kind="repo", external_id="https://github.com/example/strict",
        title="strict", url="https://github.com/example/strict",
    )
    invalid = _valid_analysis()
    if field == "project_fit_score":
        invalid["project_fits"][0]["fit_score"] = invalid_value
    else:
        invalid[field] = invalid_value
    client = _SequenceClient([
        json.dumps(invalid), json.dumps(_valid_analysis()),
    ])
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 1
    assert len(client.payloads) == 2
    assert item.extra["relevance_score"] == 94
    assert item.extra["project_fits"][0]["fit_score"] == 94


def test_analysis_strict_score_failure_is_bounded(monkeypatch):
    item = CuratedItem(
        kind="repo", external_id="https://github.com/example/strict-failure",
        title="strict-failure",
        url="https://github.com/example/strict-failure",
    )
    invalid = _valid_analysis(relevance_score="91")
    client = _SequenceClient([json.dumps(invalid), json.dumps(invalid)])
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 0
    assert len(client.payloads) == 2
    assert item.extra["analysis_status"] == "failed"
    assert item.extra["analysis_error_code"] == "invalid_analysis_response"


def test_schema_invalid_analysis_stops_after_one_corrective_retry(monkeypatch):
    item = CuratedItem(
        kind="repo", external_id="https://github.com/example/repo",
        title="repo", url="https://github.com/example/repo",
    )
    invalid = json.dumps(_valid_analysis(
        useful_for_us="Potentially useful.",
        pros=[""],
        cons=["One tradeoff"],
        key_details=["One detail"],
        implementation_notes=["One experiment"],
    ))
    client = _SequenceClient([invalid, invalid])
    monkeypatch.setattr(
        "growthos.enrich.httpx.Client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "growthos.enrich.project_context",
        lambda: ("Registered projects: llm_station.", ["llm_station"]),
    )

    assert suggest(
        [item], "http://ollama.test", "resolved-local-model",
        now_iso="2026-07-16T12:00:00+00:00",
    ) == 0
    assert len(client.payloads) == 2
    assert item.extra["analysis_status"] == "failed"
    assert item.extra["analysis_error_code"] == "invalid_analysis_response"
    retry_prompt = client.payloads[1]["messages"][0]["content"]
    assert item.extra["analysis_input_sha256"] == _input_sha256(
        item, model="resolved-local-model", prompt=retry_prompt)


def test_analysis_input_digest_covers_exact_prompt_model_and_schema():
    item = CuratedItem(
        kind="paper", external_id="2607.1", title="Digest",
        url="https://arxiv.org/abs/2607.1")
    baseline = _input_sha256(
        item, model="model-a", prompt="Project context A\nItem A")

    assert baseline == _input_sha256(
        item, model="model-a", prompt="Project context A\nItem A")
    assert baseline != _input_sha256(
        item, model="model-b", prompt="Project context A\nItem A")
    assert baseline != _input_sha256(
        item, model="model-a", prompt="Project context B\nItem A")

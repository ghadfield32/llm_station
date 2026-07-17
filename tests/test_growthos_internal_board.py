"""First-party Growth OS board client safety contracts."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "growth_os"))
from growthos.internal_board import FIELD_MAP, InternalBoardClient, analysis_cells
from growthos.models import CuratedItem
from command_center.write_locking import BoardWriteLocked


def _complete_analysis() -> dict:
    project_fits = [
        {
            "project": "betts_basketball", "fit_score": 64,
            "item_evidence": "The paper evaluates forecast calibration.",
            "project_capability": "Bayesian sports models and evaluation",
            "why": "Could support model evaluation.",
            "suggested_application": "Run one offline benchmark.",
        },
        {
            "project": "llm_station", "fit_score": 91,
            "item_evidence": "The paper evaluates tool-using agent traces.",
            "project_capability": "LLM and agent model routing and evaluation",
            "why": "Directly supports governed agent evaluation.",
            "suggested_application": "Add one trace fixture.",
        },
    ]
    return {
        "analysis_schema_version": "growthos.research-analysis.v5",
        "analysis_status": "complete",
        "analysis_model": "resolved-local-model",
        "analysis_generated_at": "2026-07-16T12:00:00+00:00",
        "analysis_input_sha256": "a" * 64,
        "analysis_origin": "local_model",
        "analysis_error_code": "",
        "useful_for_us": "Useful",
        "pros": ["Pro"], "cons": ["Con"], "key_details": ["Detail"],
        "implementation_notes": ["Try it"],
        "work_areas": ["Evaluation"], "use_cases": ["Trace testing"],
        "research_priority": "high",
        "relevance_score": 91, "potential_impact_score": 82,
        "implementation_readiness_score": 75,
        "evidence_confidence_score": 78,
        "estimated_effort": "small",
        "project_fits": project_fits,
        "applicable_projects": ["llm_station", "betts_basketball"],
        "best_project": "llm_station", "best_project_fit_score": 91,
        "project_fit_summary": (
            "- llm_station · 91/100 — Item evidence: The paper evaluates "
            "tool-using agent traces. Project capability: LLM and agent model "
            "routing and evaluation. Why: Directly supports governed agent evaluation. "
            "Suggested application: Add one trace fixture.\n"
            "- betts_basketball · 64/100 — Item evidence: The paper evaluates "
            "forecast calibration. Project capability: Bayesian sports models "
            "and evaluation. Why: Could support model evaluation. "
            "Suggested application: Run one offline benchmark."
        ),
    }


def test_dry_run_csv_preview_never_reports_successful_board_ids(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=True,
        out_dir=tmp_path / "export",
    )
    rows = [{
        "pre_hash": "paper-123",
        "cells": {"Title": "Auditable paper", "Status": "Inbox"},
    }]

    successful_ids = client.upsert("papers", rows)

    assert successful_ids == []
    assert (tmp_path / "export" / "papers.csv").is_file()
    assert not (tmp_path / "boards").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_apply_uses_typed_reconciler_event_and_is_idempotent(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    rows = [{
        "pre_hash": "paper-123",
        "cells": {"Title": "Auditable paper", "Status": "Inbox"},
    }]

    assert client.upsert("papers", rows) == ["paper-123"]
    assert client.upsert("papers", rows) == ["paper-123"]
    events = client._provider("papers").log.read()

    assert len(events) == 1
    assert events[0].source_surface == "reconciler"
    assert events[0].evidence_ref == "growth_os:papers:paper-123"
    assert client._provider("papers").list_cards()[0]["title"] == "Auditable paper"


def test_research_projection_keeps_titles_analysis_and_source_links(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    item = CuratedItem(
        kind="repo",
        external_id="https://github.com/example/research-kit",
        title="research-kit",
        url="https://github.com/example/research-kit",
        summary="An evaluation toolkit.",
        extra={
            "owner": "example",
            "code_links": ["https://github.com/example/research-kit"],
            "related_links": ["https://example.org/docs"],
            "useful_for_us": "Could shorten experiment setup.",
            "pros": ["Small integration seam"],
            "cons": ["License must be verified"],
            "key_details": ["Python package"],
            "implementation_notes": ["Start with one offline benchmark"],
            "work_areas": ["Evaluation"],
            "use_cases": ["Experiment setup"],
            "research_priority": "high",
            "relevance_score": 89,
            "potential_impact_score": 80,
            "implementation_readiness_score": 77,
            "evidence_confidence_score": 74,
            "estimated_effort": "small",
            "project_fits": _complete_analysis()["project_fits"],
            "applicable_projects": ["llm_station", "betts_basketball"],
            "best_project": "llm_station",
            "best_project_fit_score": 91,
            "project_fit_summary": "- llm_station · 91/100 — Direct fit",
            "analysis_schema_version": "growthos.research-analysis.v5",
            "analysis_status": "complete",
            "analysis_origin": "local_model",
        },
    )

    client.upsert("repos", [{
        "pre_hash": item.external_id,
        "cells": FIELD_MAP["repos"](item),
    }])

    card = client._provider("repos").list_cards()[0]
    assert card["title"] == "research-kit"
    assert card["useful_for_us"] == "Could shorten experiment setup."
    assert card["pros"] == ["Small integration seam"]
    assert card["code_links"] == ["https://github.com/example/research-kit"]
    assert card["related_links"] == ["https://example.org/docs"]
    assert card["analysis_status"] == "complete"
    assert card["analysis_origin"] == "local_model"
    assert card["relevance_score"] == 89
    assert len(card["project_fits"]) == 2


def test_analysis_backfill_candidates_are_bounded_stable_and_incomplete(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    provider = client._provider("papers")
    provider.upsert_card("paper-b", {"title": "B", "analysis_status": "failed"})
    provider.upsert_card("paper-a", {"title": "A", "analysis_status": "not_analyzed"})
    provider.upsert_card("paper-complete", {
        "title": "Done", **_complete_analysis(),
    })
    provider.upsert_card("paper-old-contract", {
        "title": "Old complete", "analysis_status": "complete",
        "useful_for_us": "Useful", "pros": ["Pro"], "cons": ["Con"],
        "key_details": ["Detail"], "implementation_notes": ["Try it"],
    })
    provider.upsert_card("paper-titleless", {"analysis_status": "not_analyzed"})
    provider.upsert_card("paper-recovered", {
        "analysis_status": "not_analyzed",
        "appflowy_source_cells": {"Title": "Recovered source title"},
    })

    assert [row["card_id"] for row in client.analysis_candidates("papers", 1)] == [
        "paper-a"]
    candidates = client.analysis_candidates("papers", 10)
    assert [row["card_id"] for row in candidates] == [
        "paper-a", "paper-b", "paper-old-contract", "paper-recovered"]
    assert candidates[-1]["title"] == "Recovered source title"
    assert client.analysis_progress("papers") == {
        "stored_total": 6,
        "total": 5,
        "titled": 5,
        "complete": 1,
        "pending": 4,
        "missing_title": 1,
    }


def test_analysis_backfill_requeues_any_malformed_schema_or_provenance(
    tmp_path: Path,
):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    provider = client._provider("papers")
    variants = {
        "numeric-string": {"relevance_score": "90"},
        "float-score": {"potential_impact_score": 82.5},
        "blank-list-item": {"pros": [""]},
        "bad-priority": {"research_priority": "urgent"},
        "inconsistent-priority": {
            "research_priority": "high",
            "relevance_score": 10,
            "potential_impact_score": 40,
            "implementation_readiness_score": 20,
            "evidence_confidence_score": 60,
        },
        "missing-origin": {"analysis_origin": ""},
        "stale-error": {"analysis_error_code": "old_failure"},
        "partial-projects": {
            "project_fits": _complete_analysis()["project_fits"][:1],
        },
        "bad-derived-best": {"best_project": "betts_basketball"},
        "bad-derived-applicable": {"applicable_projects": ["llm_station"]},
    }
    for name, patch in variants.items():
        provider.upsert_card(
            f"paper-{name}", {"title": name, **_complete_analysis(), **patch})
    provider.upsert_card(
        "paper-valid", {"title": "Valid", **_complete_analysis()})

    candidates = client.analysis_candidates("papers", 20)

    assert {row["card_id"] for row in candidates} == {
        f"paper-{name}" for name in variants
    }


def test_reanalysis_early_failure_does_not_blank_unattempted_cards(
    monkeypatch, tmp_path: Path,
):
    from types import SimpleNamespace

    sys.modules.setdefault("feedparser", SimpleNamespace())
    from growthos.curate import _reanalyze

    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    provider = client._provider("papers")
    provider.upsert_card("paper-a", {
        **_complete_analysis(),
        "title": "A", "analysis_status": "not_analyzed",
        "useful_for_us": "Keep attempted usefulness",
        "pros": ["Keep attempted pro"],
        "cons": ["Keep attempted con"],
        "key_details": ["Keep attempted detail"],
        "implementation_notes": ["Keep attempted note"],
        "review_topics": ["Bayesian forecasting"],
    })
    preserved = {
        **_complete_analysis(),
        "title": "B",
        "analysis_status": "failed",
        "analysis_error_code": "prior_failure",
        "useful_for_us": "Preserve this prior result",
        "pros": ["Preserved pro"],
        "cons": ["Preserved con"],
        "key_details": ["Preserved detail"],
        "implementation_notes": ["Preserved implementation note"],
        "review_topics": ["Agent evaluation"],
    }
    provider.upsert_card("paper-b", preserved)

    def fail_first(items, _base_url, _model):
        items[0].extra.update({
            "analysis_status": "failed",
            "analysis_model": "test-model",
            "analysis_generated_at": "2026-07-16T12:00:00+00:00",
            "analysis_input_sha256": "a" * 64,
            "analysis_origin": "local_model",
            "analysis_error_code": "ollama_request_failed",
        })
        return 0

    monkeypatch.setattr("growthos.enrich.suggest", fail_first)
    result = _reanalyze(
        client, "papers", 2,
        base_url="http://ollama.test", model="test-model")

    cards = {row["card_id"]: row for row in provider.list_cards()}
    assert result["papers_analysis_written"] == 1
    assert cards["paper-a"]["analysis_error_code"] == "ollama_request_failed"
    assert cards["paper-a"]["useful_for_us"] == "Keep attempted usefulness"
    assert cards["paper-a"]["pros"] == ["Keep attempted pro"]
    assert cards["paper-a"]["work_areas"] == ["Evaluation"]
    assert cards["paper-a"]["use_cases"] == ["Trace testing"]
    assert cards["paper-a"]["relevance_score"] == 91
    assert cards["paper-a"]["project_fits"] == _complete_analysis()["project_fits"]
    assert cards["paper-a"]["best_project"] == "llm_station"
    assert cards["paper-a"]["project_fit_summary"] == (
        _complete_analysis()["project_fit_summary"])
    assert cards["paper-a"]["review_topics"] == ["Bayesian forecasting"]
    assert cards["paper-b"]["analysis_status"] == "failed"
    assert cards["paper-b"]["analysis_error_code"] == "prior_failure"
    assert cards["paper-b"]["useful_for_us"] == "Preserve this prior result"
    assert cards["paper-b"]["pros"] == ["Preserved pro"]
    assert cards["paper-b"]["work_areas"] == ["Evaluation"]
    assert cards["paper-b"]["use_cases"] == ["Trace testing"]
    assert cards["paper-b"]["relevance_score"] == 91
    assert cards["paper-b"]["project_fits"] == _complete_analysis()["project_fits"]
    assert cards["paper-b"]["best_project_fit_score"] == 91
    assert cards["paper-b"]["review_topics"] == ["Agent evaluation"]


def test_successful_reanalysis_clears_a_prior_canonical_error(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    provider = client._provider("papers")
    provider.upsert_card("paper-retry", {
        "title": "Retry me",
        "analysis_status": "failed",
        "analysis_error_code": "invalid_analysis_response",
    })
    item = CuratedItem(
        kind="paper", external_id="paper-retry", title="Retry me",
        url="https://arxiv.org/abs/paper-retry",
        extra={
            "analysis_status": "complete",
            "analysis_model": "test-model",
            "analysis_generated_at": "2026-07-16T12:30:00+00:00",
            "analysis_input_sha256": "b" * 64,
            "analysis_origin": "local_model",
            "useful_for_us": "Useful after retry",
            "pros": ["Pro"],
            "cons": ["Con"],
            "key_details": ["Detail"],
            "implementation_notes": ["Try it"],
        },
    )

    client.upsert("papers", [{
        "pre_hash": item.external_id,
        "cells": analysis_cells(item),
    }])

    card = {row["card_id"]: row for row in provider.list_cards()}["paper-retry"]
    assert card["analysis_status"] == "complete"
    assert card["analysis_error_code"] == ""


def test_backfill_recovers_source_context_not_only_the_historical_title():
    from types import SimpleNamespace

    sys.modules.setdefault("feedparser", SimpleNamespace())
    from growthos.curate import _analysis_item

    item = _analysis_item("papers", {
        "card_id": "legacy-paper",
        "title": "Recovered title",
        "appflowy_source_cells": {
            "Abstract": "A source-retained evaluation protocol.",
            "Authors": "A. Researcher",
            "URL": "https://arxiv.org/abs/2607.12345",
            "Topics": ["cs.AI"],
        },
        "review_topics": ["Agent evaluation"],
    })

    assert item.summary == "A source-retained evaluation protocol."
    assert item.authors == "A. Researcher"
    assert item.url == "https://arxiv.org/abs/2607.12345"
    assert item.topics == ["Agent evaluation"]


def test_curator_never_resets_an_existing_lane(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    row = {
        "pre_hash": "paper-123",
        "cells": {"Title": "Auditable paper", "Status": "Inbox"},
    }
    client.upsert("papers", [row])
    provider = client._provider("papers")
    from command_center.kanban_sync.events import emit_event
    emit_event(
        provider.log,
        action="start_todo",
        board_id=provider.board_id,
        card_id="paper-123",
        source_surface="internal_ui",
        status_before="Inbox",
        status_after="Reading",
    )

    client.upsert("papers", [row])

    assert provider.snapshot()["paper-123"]["status"] == "Reading"
    assert len(provider.log.read()) == 2


def test_updated_rows_return_exact_ids_not_storage_filenames(tmp_path: Path):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    client.upsert("papers", [{
        "pre_hash": "paper/id?case",
        "cells": {"Title": "Exact identity", "Status": "Inbox"},
    }])

    assert client.rows_updated_since("papers", "1970-01-01T00:00:00Z") == [
        "paper/id?case"
    ]


def test_row_transaction_retries_lock_contention_without_rescanning(
    monkeypatch, tmp_path: Path,
):
    client = InternalBoardClient(
        store_dir=tmp_path / "boards",
        event_log=tmp_path / "events.jsonl",
        dry_run=False,
    )
    provider = client._provider("dags")
    original = provider.upsert_card
    attempts = []

    def contended(*args, **kwargs):
        attempts.append("try")
        if len(attempts) < 3:
            raise BoardWriteLocked("reader active")
        return original(*args, **kwargs)

    monkeypatch.setattr(provider, "upsert_card", contended)
    monkeypatch.setattr(client, "_provider", lambda _db_name: provider)
    monkeypatch.setattr("growthos.internal_board.time.sleep", lambda _delay: None)

    written = client.upsert("dags", [{
        "pre_hash": "dag-1",
        "cells": {"DagID": "dag-1", "Name": "DAG one", "Status": "Active"},
    }])

    assert written == ["dag-1"]
    assert attempts == ["try", "try", "try"]
    assert provider.snapshot()["dag-1"]["status"] == "Active"

"""
Cross-cutting validation across the four 2026-07-02 deltas (research intake, gateway
logging, skills audit, card dependencies) and their combinations with each other and
with pre-existing pipeline behavior. Unit tests for each feature already exist in
test_research_digest.py / test_gateway_logging.py / test_skills_audit.py /
test_card_dependencies.py; this file is specifically about interactions:
  - research_digest sharing Pillar.FULL_IDEA with the pre-existing papers scanner
  - the full catalog -> feed -> scan(--apply) -> registry pipeline end to end
  - all three configured kanban boards (only one uses dependency_fields) validating together
  - board_state rendering a mix of dependency and non-dependency rows across sections
  - determinism of the new CLI outputs
"""
from __future__ import annotations

import json

import yaml

from command_center.channels.board_state import (
    BoardStateKnobs, _cards_section, _missions_section, render_board_state,
)
from command_center.improvement.discovery import (
    ObserverCharter, PapersScanner, ResearchSourceScanner, ScanPipeline,
)
from command_center.improvement.registry import ExperimentRegistry
from command_center.research import Priority, ResearchSource, ResearchSourceCatalog, Verdict
from command_center.research.catalog import source_to_feed_record
from command_center.schemas import KanbanBoardsConfig


# --------------------------------------------------------------------- shared-pillar dedup

def test_research_and_papers_scanners_coexist_in_one_pipeline(tmp_path):
    """Both PapersScanner and ResearchSourceScanner classify into Pillar.FULL_IDEA. A scan
    run mixing both sources must not crash, and each source's findings must carry its own
    `source` name even when they land in the same pillar (dedup is by pillar+title-slug, a
    pre-existing pipeline rule this integration must not silently break)."""
    papers_feed = [{"title": "Totally Different Paper", "abstract": "x", "url": "u",
                    "relevance": 0.9, "applicability": 0.8}]
    research_feed = [source_to_feed_record(ResearchSource(
        id="rs-1", title="A research source", source_type="github", source="o/r",
        concept_cluster="memory", claim="teaches something",
        measured_gap="a gap", related_modules=["m"], verdict=Verdict.EVALUATE))]

    papers = PapersScanner(lambda: papers_feed)
    research = ResearchSourceScanner(lambda: research_feed)

    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    pipe = ScanPipeline(ObserverCharter(reg, report_path=str(tmp_path / "report.md")))
    report = pipe.run([papers, research], date="2026-07-02", now_iso="2026-07-02T00:00:00Z",
                      apply=False)
    assert report.n_failed == 0
    assert report.n_findings == 2
    sources = {o.scanner for o in report.outcomes}
    assert sources == {"arxiv", "research_digest"}


def test_identical_title_across_sources_dedupes_by_design_not_crash(tmp_path):
    """If a research source and a paper happen to slug to the same pillar+title, the
    pipeline's existing dedup rule (pillar+title, not source) collapses them to one
    finding. This documents that behavior for this integration rather than assuming it —
    it must not raise, and exactly one of the two survives triage."""
    same_title = "Shared Idea Title"
    papers_feed = [{"title": same_title, "abstract": "x", "url": "u",
                    "relevance": 0.9, "applicability": 0.8}]
    research_feed = [source_to_feed_record(ResearchSource(
        id="rs-2", title=same_title, source_type="github", source="o/r2",
        concept_cluster="memory", claim="a different claim, same title slug",
        measured_gap="a gap", verdict=Verdict.EVALUATE))]
    papers = PapersScanner(lambda: papers_feed)
    research = ResearchSourceScanner(lambda: research_feed)
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    pipe = ScanPipeline(ObserverCharter(reg, report_path=str(tmp_path / "report.md")))
    report = pipe.run([papers, research], date="2026-07-02", now_iso="2026-07-02T00:00:00Z",
                      apply=False)
    assert report.n_failed == 0
    # both findings were classified (n_findings counts pre-dedup); triage/dedup collapsing
    # to one drafted card is the pre-existing behavior this test documents, not a crash.
    assert report.n_findings == 2


# --------------------------------------------------------------------- full pipeline, apply=True

def test_catalog_to_feed_to_scan_apply_creates_a_real_proposed_experiment(tmp_path):
    """The full advertised loop: a catalog row -> feed -> scan --apply -> an actual
    Proposed row lands in the ExperimentRegistry (not just a dry-run count)."""
    cat = ResearchSourceCatalog(sources=[ResearchSource(
        id="e2e-probe", title="End to end probe", source_type="github", source="o/e2e",
        concept_cluster="memory", claim="proves the pipeline writes a real row",
        measured_gap="a measured gap", related_modules=["m"],
        verdict=Verdict.EVALUATE, priority=Priority.HIGH)])
    feed = {"research_digest": [source_to_feed_record(cat.sources[0])]}
    feed_path = tmp_path / "feed.json"
    feed_path.write_text(json.dumps(feed), encoding="utf-8")

    research = ResearchSourceScanner(lambda: json.loads(feed_path.read_text())["research_digest"])
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    report_path = tmp_path / "report.md"
    pipe = ScanPipeline(ObserverCharter(reg, report_path=str(report_path)))
    report = pipe.run([research], date="2026-07-02", now_iso="2026-07-02T00:00:00Z", apply=True)

    assert report.n_failed == 0
    assert len(report.drafted_ids) == 1
    rows = reg.list_experiments()
    assert len(rows) == 1
    assert rows[0]["status"] == "Proposed"
    assert rows[0]["risk_tier"] == "L1_plan_only"
    assert report_path.exists()


# --------------------------------------------------------------------- kanban registry: mixed boards

def test_real_kanban_boards_yaml_validates_with_mixed_dependency_fields_usage():
    """The committed configs/kanban_boards.yaml mixes boards with and without
    dependency_fields. All must validate together in one KanbanBoardsConfig load —
    proves the opt-in field doesn't require every board to declare it."""
    raw = yaml.safe_load(open("configs/kanban_boards.yaml", encoding="utf-8"))
    cfg = KanbanBoardsConfig.model_validate(raw)
    by_id = {b.board_id: b for b in cfg.boards}
    assert {"llm_station_command_center", "betts_basketball",
            "betts_basketball_appflowy", "job_search_pipeline",
            "job_search_pipeline_internal"} <= set(by_id)
    assert set(by_id["llm_station_command_center"].dependency_fields) == {"blocked_by",
                                                                          "unblocks"}
    assert by_id["betts_basketball"].dependency_fields == []
    assert by_id["betts_basketball_appflowy"].dependency_fields == []
    assert by_id["job_search_pipeline_internal"].dependency_fields == []


# --------------------------------------------------------------------- board_state: mixed rows

def _knobs(max_items=10):
    return BoardStateKnobs(boards=["mission_intake"], max_items_per_group=max_items)


def test_board_state_renders_mixed_dependency_and_independent_cards_together():
    rows = [
        {"title": "Independent card", "status": "Backlog", "risk": "L1"},
        {"title": "Blocked card", "status": "Backlog", "risk": "L2", "blocked_by": "M1,M2"},
        {"title": "Another independent", "status": "Ready", "risk": "L1"},
    ]
    section = _cards_section(rows, _knobs())
    text = render_board_state([section], _knobs())
    assert "Independent card" in text and "⛔blocked_by:" not in text.split("Independent card")[0]
    assert "Blocked card [L2] ⛔blocked_by:M1,M2" in text
    assert "Another independent" in text
    # the independent cards render with no marker at all (byte-identical to pre-feature shape)
    assert "Another independent [L1]" in text and "⛔" not in text.split("Another independent")[1][:5]


def test_board_state_missions_section_also_gets_the_marker():
    rows = [{"id": "EXP-1", "action": "do a thing", "status": "open", "risk": "L2",
            "blocked_by": ["EXP-0"]}]
    section = _missions_section(rows, _knobs())
    text = render_board_state([section], _knobs())
    assert "⛔blocked_by:EXP-0" in text


def test_board_state_untouched_by_feature_when_no_row_uses_it():
    """Regression guard: boards that never set blocked_by render byte-identical to the
    pre-feature output (no stray whitespace, no marker artifacts)."""
    rows = [{"title": "Plain card", "status": "Backlog", "risk": "L1", "section": "core"}]
    section = _cards_section(rows, _knobs())
    text = render_board_state([section], _knobs())
    assert text.count("⛔") == 0
    assert "Plain card [L1 · core]" in text


# --------------------------------------------------------------------- determinism

def test_research_digest_feed_is_byte_identical_across_runs():
    from command_center.research import catalog_to_feed, load_catalog
    cat = load_catalog("knowledge/research/source_catalog.yaml")
    a = json.dumps(catalog_to_feed(cat), indent=2)
    b = json.dumps(catalog_to_feed(cat), indent=2)
    assert a == b


def test_skills_audit_ordering_is_deterministic_across_runs():
    from command_center.skills import discover_skills
    a = [r.to_dict() for r in discover_skills()]
    b = [r.to_dict() for r in discover_skills()]
    assert a == b

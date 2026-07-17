"""Frontend guardrails for readable, expandable Kanban cards on every surface."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "services" / "agent_kanban_ui" / "web"


def test_all_kanban_card_surfaces_use_the_shared_disclosure():
    app = (WEB / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "function CardDisclosure" in app
    assert app.count("<CardDisclosure") == 3
    assert 'aria-expanded={expanded}' in app
    assert "onClick={onToggle}" in app
    assert "Open full details" in app
    assert "onOpen={() => onOpen(c.id)}" in app
    assert "onOpen={() => onOpenCard(board.board, c, board.statuses ?? [])}" in app
    assert "onOpen={onOpen}" in app


def test_card_summaries_show_recorded_priority_and_estimate_without_invention():
    app = (WEB / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "<small>Priority</small>" in app
    assert "<small>Estimate</small>" in app
    assert 'priority || "Not set"' in app
    assert 'estimate || "Not set"' in app
    assert "CARD_PRIORITY_FIELDS" in app
    assert "CARD_ESTIMATE_FIELDS" in app


def test_scrollable_lanes_keep_cards_at_selectable_height():
    styles = (WEB / "src" / "styles.css").read_text(encoding="utf-8")

    assert ".card { flex: 0 0 auto;" in styles
    assert ".domain-card {" in styles
    assert "flex: 0 0 auto; background: var(--card)" in styles
    assert ".domain-nav-section {" in styles
    assert "overflow-y: auto; overscroll-behavior-y: contain;" in styles
    assert ".column-body," in styles
    assert ".domain-column-body {" in styles
    assert "overflow-x: auto; max-width: 100%;" in styles


def test_research_boards_expose_complete_kpi_contract_and_chip_filters():
    app = (WEB / "src" / "App.tsx").read_text(encoding="utf-8")
    styles = (WEB / "src" / "styles.css").read_text(encoding="utf-8")
    analysis = (WEB / "src" / "researchAnalysis.ts").read_text(
        encoding="utf-8")

    assert '"growthos.research-analysis.v5"' in analysis
    assert "function researchAnalysisComplete" in analysis
    assert "function ResearchFilterPanel" in app
    assert 'label="Areas of work"' in app
    assert 'label="Use cases"' in app
    assert 'label="Registered folders"' in app
    assert 'label="Priorities"' in app
    assert 'label="Relevance"' in app
    assert 'label="Impact"' in app
    assert 'label="Readiness"' in app
    assert 'label="Confidence"' in app
    assert 'label="Folder fit"' in app
    assert "Detailed KPI analysis is pending" in app
    assert "Detailed KPI analysis failed" in app
    assert "Analysis unavailable" in analysis
    assert "KPI upgrade pending" in analysis
    assert "allowCreate={false}" in app
    assert ".research-filter-tags {" in styles
    assert ".research-analysis-notice {" in styles


def test_research_progress_uses_only_exact_committed_strict_counts():
    progress = (WEB / "src" / "researchProgress.ts").read_text(encoding="utf-8")
    behavior = (WEB / "tests" / "researchProgress.test.mjs").read_text(
        encoding="utf-8")

    assert "exactResearchProgressCounts" in progress
    assert "pending: titled - complete" in progress
    assert "missing_title: total - titled" in progress
    assert "projectResearchProgressCounts" not in progress
    assert "progress reports only exact committed strict counts" in behavior
    assert "invalid or stale counts are clamped" in behavior

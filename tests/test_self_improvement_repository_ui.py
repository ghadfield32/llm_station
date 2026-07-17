"""Static UI contracts for the repository-aware Self Improvement board."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services/agent_kanban_ui/web/src/App.tsx"
API = ROOT / "services/agent_kanban_ui/web/src/api.ts"
CSS = ROOT / "services/agent_kanban_ui/web/src/styles.css"


def test_repository_tabs_are_catalog_driven_and_self_updating():
    source = APP.read_text(encoding="utf-8")
    start = source.index("function SelfImprovementToolbar")
    end = source.index("function DagCard", start)
    component = source[start:end]

    assert "repositories.map((repo)" in component
    assert "repo.repo_id" in component
    assert "All repositories" in component
    assert "scan_reason" in component
    assert "research_capabilities" in component
    assert "fetchRegisteredRepositories()" in source
    assert 'getJSON<RegisteredRepositoryCatalog>("/api/repos")' in API.read_text(
        encoding="utf-8")


def test_self_improvement_has_kpis_and_native_filter_dropdown():
    source = APP.read_text(encoding="utf-8")
    start = source.index("function SelfImprovementToolbar")
    end = source.index("function DagCard", start)
    component = source[start:end]

    assert 'aria-label="Self Improvement KPIs"' in component
    for label in ("Shown", "Backlog", "Active / review", "Blocked", "Average score"):
        assert label in component
    assert '<details className="improvement-filter-disclosure">' in component
    for control in ("Search", "Status", "Pillar", "Risk", "Source", "Minimum score"):
        assert control in component


def test_repository_overview_is_responsive_and_focus_visible():
    source = CSS.read_text(encoding="utf-8")
    assert ".improvement-repo-tabs" in source
    assert ".improvement-kpis" in source
    assert ".improvement-filter-summary:focus-visible" in source
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in source

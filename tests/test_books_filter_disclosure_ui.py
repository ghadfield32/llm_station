from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services/agent_kanban_ui/web/src/App.tsx"
CSS = ROOT / "services/agent_kanban_ui/web/src/styles.css"


def test_library_filters_are_an_optional_native_disclosure():
    source = APP.read_text(encoding="utf-8")
    start = source.index("function BookLibraryFilters")
    end = source.index("const EMPTY_BOOK_DRAFT", start)
    component = source[start:end]

    assert '<details className="book-filter-disclosure">' in component
    assert '<summary className="book-filter-summary">' in component
    assert "Optional" in component
    assert "book-filter-chevron" in component


def test_library_filter_disclosure_has_visible_focus_and_open_state_styles():
    source = CSS.read_text(encoding="utf-8")

    assert ".book-filter-summary:focus-visible" in source
    assert ".book-filter-disclosure[open] .book-filter-chevron" in source

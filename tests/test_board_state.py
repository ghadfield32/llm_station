"""Phase 1 of the agent kanban surface: the harness owns board state.

Hermetic — no live AppFlowy/Ledger/Ollama. Fetchers are injected, so we test the
renderer + the fail-loud collector deterministically.
"""
from command_center.channels.board_state import (
    BoardSection, collect_sections, render_board_state, load_agent_surface_config)
from command_center.schemas import BoardStateKnobs


def _knobs(**kw) -> BoardStateKnobs:
    return BoardStateKnobs(**kw)


def test_grouping_caps_and_discloses_overflow():
    knobs = _knobs(boards=["mission_intake"], max_items_per_group=2)
    cards = [
        {"title": "a", "status": "Backlog", "risk": "L2", "section": "DAGs"},
        {"title": "b", "status": "Backlog", "risk": "L1", "section": "Learning"},
        {"title": "c", "status": "Backlog", "risk": "L2", "section": "DAGs"},
        {"title": "d", "status": "In Progress", "risk": "L2", "section": "DAGs"},
    ]
    out = render_board_state(
        collect_sections(knobs, cards_fn=lambda: cards,
                         todos_fn=lambda: [], missions_fn=lambda: []),
        knobs)
    # 3 in Backlog, capped at 2, overflow disclosed (not silently dropped)
    assert "Backlog (3):" in out
    assert "(+1 more)" in out
    assert "In Progress (1):" in out
    assert "a [L2 · DAGs]" in out


def test_terminal_columns_are_omitted():
    knobs = _knobs(boards=["mission_intake"])
    cards = [
        {"title": "live", "status": "Backlog", "risk": "L2", "section": "DAGs"},
        {"title": "old", "status": "Done", "risk": "L2", "section": "DAGs"},
        {"title": "nope", "status": "Rejected", "risk": "L2", "section": "DAGs"},
    ]
    out = render_board_state(
        collect_sections(knobs, cards_fn=lambda: cards,
                         todos_fn=lambda: [], missions_fn=lambda: []),
        knobs)
    assert "live" in out
    assert "Done" not in out and "Rejected" not in out


def test_fetch_failure_is_loud_not_empty():
    """A source that can't be read renders an explicit ERROR line — never an empty
    group that would read as 'no cards' and silently mislead the model."""
    knobs = _knobs(boards=["missions"])

    def boom():
        raise RuntimeError("ledger unreachable")

    out = render_board_state(
        collect_sections(knobs, cards_fn=lambda: [],
                         todos_fn=lambda: [], missions_fn=boom),
        knobs)
    assert "missions: ERROR: RuntimeError: ledger unreachable" in out


def test_action_error_string_is_treated_as_failure():
    """growthos actions return an error *string* on bad input; that must surface as
    an ERROR section, not be rendered as rows."""
    knobs = _knobs(boards=["todos"])
    out = render_board_state(
        collect_sections(knobs, cards_fn=lambda: [],
                         todos_fn=lambda: "invalid status 'x'", missions_fn=lambda: []),
        knobs)
    assert "todos: ERROR:" in out
    assert "invalid status 'x'" in out


def test_empty_board_is_explicit():
    knobs = _knobs(boards=["todos"])
    out = render_board_state(
        collect_sections(knobs, cards_fn=lambda: [],
                         todos_fn=lambda: [], missions_fn=lambda: []),
        knobs)
    assert "todos: (no live items)" in out


def test_section_dataclass_defaults():
    sec = BoardSection("todos")
    assert sec.groups == [] and sec.error is None


def test_committed_config_validates_and_has_expected_shape():
    cfg = load_agent_surface_config()
    assert cfg.board_state.enabled is True
    assert "mission_intake" in cfg.board_state.boards
    assert cfg.tuning.min_decisions >= 1

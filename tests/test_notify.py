"""cc notify — the proactive Discord digest. Tests the pure pieces (no network):
the active-mission filter is driven by the canonical live-mission columns (not a
re-listed literal), and the digest composes from already-gathered inputs.
"""
from command_center.cli import notify
from command_center.channels.board_state import LIVE_COLUMNS


def test_filter_active_uses_canonical_live_columns():
    # one mission per live column + two terminal ones; only the live ones survive
    live = [{"id": f"m{i}", "status": s} for i, s in enumerate(LIVE_COLUMNS["missions"])]
    terminal = [{"id": "done", "status": "done"}, {"id": "rej", "status": "rejected"}]
    out = notify.filter_active(live + terminal)
    assert {m["id"] for m in out} == {m["id"] for m in live}
    assert all(m["status"] in set(LIVE_COLUMNS["missions"]) for m in out)


def test_compose_digest_lists_missions_and_brief():
    missions = [{"id": "m-1", "status": "running",
                 "action": "Fix odds_ingest_daily DAG\nsecond line ignored"}]
    out = notify.compose_digest("2026-06-13", "Brief headline\n- 3 new papers", missions)
    assert "Growth OS update - 2026-06-13" in out
    assert "Active missions (1):" in out
    assert "m-1 [running] Fix odds_ingest_daily DAG" in out
    assert "second line ignored" not in out      # only the first action line
    assert "Brief headline" in out


def test_compose_digest_no_missions_is_explicit_not_blank():
    out = notify.compose_digest("2026-06-13", "", [])
    assert "No active missions." in out
    assert "Latest brief:" not in out            # omitted when there is no brief


def test_compose_digest_truncates_long_action_to_a_headline():
    long_action = "x" * 200
    out = notify.compose_digest("2026-06-13", "", [{"id": "m", "status": "open",
                                                    "action": long_action}])
    # the action is capped to a headline length, never the whole body
    assert "x" * 70 in out and "x" * 80 not in out

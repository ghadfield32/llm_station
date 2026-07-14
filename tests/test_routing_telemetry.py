"""Router-correction telemetry: record a human's routing decision as durable
ground truth, read it back, and summarize it — but derive NO rules. Proves the
service logic (accepted computation, summary) over the in-memory store AND that
corrections survive a restart over the Ledger store (the whole point — evidence
must persist). No Docker: the Ledger app is loaded via importlib + TestClient,
like tests/test_work_graph_ledger_store.py.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
from pathlib import Path

import pytest

from command_center.work_graph import (
    InMemoryRoutingTelemetryStore,
    LedgerRoutingTelemetryStore,
    RoutingTelemetryService,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_APP = REPO_ROOT / "services/ledger/app.py"


def _svc(store) -> RoutingTelemetryService:
    ids = itertools.count(1)
    ticks = itertools.count(1)
    return RoutingTelemetryService(
        store,
        clock=lambda: f"2026-07-14T00:00:{next(ticks):02d}+00:00",
        id_factory=lambda: f"rc-{next(ids)}")


# ---- service logic over the in-memory store ---------------------------------

def test_accepted_is_true_only_when_choice_matches_suggestion():
    svc = _svc(InMemoryRoutingTelemetryStore())
    kept = svc.record("write a post", suggested_board_id="posts",
                      chosen_board_id="posts", matched_keywords=["post"])
    changed = svc.record("write a post", suggested_board_id="posts",
                         chosen_board_id="research")
    declined = svc.record("misc idea", suggested_board_id="posts",
                          chosen_board_id=None)
    assert kept.accepted is True
    assert changed.accepted is False           # human overrode the router
    assert declined.accepted is False          # left in the Inbox
    assert kept.matched_keywords == ["post"]


def test_empty_title_is_rejected():
    with pytest.raises(ValueError):
        _svc(InMemoryRoutingTelemetryStore()).record("   ")


def test_summary_counts_and_acceptance_rate():
    svc = _svc(InMemoryRoutingTelemetryStore())
    svc.record("a", suggested_board_id="posts", chosen_board_id="posts")
    svc.record("b", suggested_board_id="posts", chosen_board_id="research")
    svc.record("c", suggested_board_id=None, chosen_board_id="research")
    s = svc.summary()
    assert s["total"] == 3 and s["accepted"] == 1
    assert s["acceptance_rate"] == pytest.approx(1 / 3)
    assert s["by_chosen_board"] == {"posts": 1, "research": 2}


def test_summary_acceptance_rate_is_none_with_no_evidence():
    assert _svc(InMemoryRoutingTelemetryStore()).summary()["acceptance_rate"] is None


def test_list_filters_by_board_and_limit():
    svc = _svc(InMemoryRoutingTelemetryStore())
    svc.record("a", chosen_board_id="posts")
    svc.record("b", chosen_board_id="research")
    svc.record("c", chosen_board_id="posts")
    assert [c.title for c in svc.list(board="posts")] == ["a", "c"]
    assert len(svc.list(limit=2)) == 2


def test_list_since_filters_older_corrections():
    svc = _svc(InMemoryRoutingTelemetryStore())
    first = svc.record("old")                      # at ...:01
    second = svc.record("new")                     # at ...:02
    assert [c.title for c in svc.list(since=second.at)] == ["new"]
    assert [c.title for c in svc.list(since=first.at)] == ["old", "new"]


# ---- durability over the Ledger store ---------------------------------------

@pytest.fixture
def ledger_client(tmp_path):
    os.environ["LEDGER_DB"] = str(tmp_path / "ledger.db")
    spec = importlib.util.spec_from_file_location("ledger_app_telemetry_test", LEDGER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app)


def test_corrections_survive_a_fresh_service_over_the_same_ledger(ledger_client):
    svc = _svc(LedgerRoutingTelemetryStore(ledger_client))
    c = svc.record("research old footage", suggested_board_id="posts",
                   chosen_board_id="research", matched_keywords=["research"],
                   conversation_id="chat-9", source="capture")
    # a BRAND-NEW service (= restart) over the SAME Ledger db
    fresh = _svc(LedgerRoutingTelemetryStore(ledger_client))
    got = fresh.get(c.correction_id)
    assert got.title == "research old footage"
    assert got.chosen_board_id == "research"
    assert got.accepted is False               # posts suggested, research chosen
    assert got.matched_keywords == ["research"]
    assert got.source == "capture"
    assert fresh.summary()["by_chosen_board"] == {"research": 1}


def test_ledger_list_ordering_and_unknown_is_keyerror(ledger_client):
    svc = _svc(LedgerRoutingTelemetryStore(ledger_client))
    svc.record("first", chosen_board_id="posts")
    svc.record("second", chosen_board_id="research")
    assert [c.title for c in svc.list()] == ["first", "second"]     # insertion order
    with pytest.raises(KeyError):
        svc.get("never-seen")


def test_durability_across_a_full_ledger_app_reload(ledger_client):
    # write via the first app instance, then RELOAD the entire ledger app module
    # against the SAME on-disk LEDGER_DB (a truer "restart" than a fresh client
    # over the same app) and prove the row is still there.
    c = _svc(LedgerRoutingTelemetryStore(ledger_client)).record(
        "persist me", chosen_board_id="research")
    spec = importlib.util.spec_from_file_location("ledger_app_reload", LEDGER_APP)
    mod2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod2)                 # reads the same LEDGER_DB env
    from starlette.testclient import TestClient
    reloaded = _svc(LedgerRoutingTelemetryStore(TestClient(mod2.app)))
    assert reloaded.get(c.correction_id).title == "persist me"

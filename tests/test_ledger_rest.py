"""Ledger REST experiment endpoints, exercised live via FastAPI's TestClient — no Docker.

Proves the running Ledger surface (not just the host registry) stores experiments in the
one ledger.db, applies the lifecycle edges, and keeps Canary/Promoted behind the SAME human
HMAC approval wall mission approvals use. An agent cannot self-promote through the API.
"""
from __future__ import annotations

import importlib.util

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "services/ledger/app.py"
SECRET = "test-approval-secret"


@pytest.fixture(scope="module")
def ledger(tmp_path_factory):
    import os
    db = tmp_path_factory.mktemp("ledger") / "ledger.db"
    os.environ["LEDGER_DB"] = str(db)
    os.environ["LEDGER_APPROVAL_SECRET"] = SECRET
    # import the standalone service module by path (it is not part of the package)
    spec = importlib.util.spec_from_file_location("ledger_app_under_test", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from starlette.testclient import TestClient
    return TestClient(mod.app), mod


def _register(client, eid="EXP-rest-001"):
    return client.post("/experiment", json={
        "experiment_id": eid, "title": "rest test", "owner": "geoff",
        "target_type": "retrieval", "target_ref": "x", "risk_tier": "L2_local_edits",
        "mission_id": "T-rest"})


def test_register_and_get(ledger):
    client, _ = ledger
    r = _register(client)
    assert r.status_code == 200 and r.json()["status"] == "Proposed"
    g = client.get("/experiment/EXP-rest-001")
    assert g.status_code == 200
    assert g.json()["experiment"]["status"] == "Proposed"
    assert any(e["kind"] == "EXPERIMENT_REGISTERED" for e in g.json()["events"])


def test_duplicate_register_rejected(ledger):
    client, _ = ledger
    _register(client, "EXP-rest-dup")
    again = _register(client, "EXP-rest-dup")
    assert again.status_code == 409


def test_event_append_and_list(ledger):
    client, _ = ledger
    _register(client, "EXP-rest-ev")
    r = client.post("/experiment/EXP-rest-ev/event",
                    json={"kind": "BASELINE_STARTED", "actor_role": "runner", "action": "x"})
    assert r.status_code == 200
    g = client.get("/experiment/EXP-rest-ev")
    assert any(e["kind"] == "BASELINE_STARTED" for e in g.json()["events"])
    lst = client.get("/experiments")
    assert any(e["experiment_id"] == "EXP-rest-ev" for e in lst.json())


def test_legal_agent_transitions(ledger):
    client, _ = ledger
    _register(client, "EXP-rest-walk")
    for nxt in ("Baseline Ready", "Running", "Awaiting Verification", "Verified",
                "Awaiting Human Promotion"):
        r = client.post("/experiment/EXP-rest-walk/status",
                        json={"status": nxt, "actor": "agent"})
        assert r.status_code == 200, (nxt, r.text)


def test_illegal_transition_rejected(ledger):
    client, _ = ledger
    _register(client, "EXP-rest-illegal")
    r = client.post("/experiment/EXP-rest-illegal/status",
                    json={"status": "Promoted", "actor": "agent"})
    assert r.status_code == 409  # no edge Proposed -> Promoted


# ---- the HMAC promotion wall on the REST surface ---------------------------

def _to_awaiting(client, eid):
    _register(client, eid)
    for nxt in ("Baseline Ready", "Running", "Awaiting Verification", "Verified",
                "Awaiting Human Promotion"):
        client.post(f"/experiment/{eid}/status", json={"status": nxt, "actor": "agent"})


def test_agent_cannot_enter_canary_via_rest(ledger):
    client, _ = ledger
    _to_awaiting(client, "EXP-rest-agentcanary")
    r = client.post("/experiment/EXP-rest-agentcanary/status",
                    json={"status": "Canary", "actor": "agent"})
    assert r.status_code == 403 and "self-promotion" in r.text


def test_human_canary_requires_valid_signature(ledger):
    client, mod = ledger
    eid = "EXP-rest-humancanary"
    _to_awaiting(client, eid)
    # human actor but WRONG signature -> rejected
    bad = client.post(f"/experiment/{eid}/status",
                      json={"status": "Canary", "actor": "human", "signature": "nope"})
    assert bad.status_code == 403 and "bad signature" in bad.text
    # human actor with the correct HMAC -> allowed (same wall as mission approvals)
    sig = mod._sign(eid, "Canary")
    ok = client.post(f"/experiment/{eid}/status",
                     json={"status": "Canary", "actor": "human", "signature": sig})
    assert ok.status_code == 200 and ok.json()["status"] == "Canary"
    # and promotion from Canary, human + signed
    psig = mod._sign(eid, "Promoted")
    promo = client.post(f"/experiment/{eid}/status",
                        json={"status": "Promoted", "actor": "human", "signature": psig})
    assert promo.status_code == 200 and promo.json()["status"] == "Promoted"


def test_migration_recorded_and_tables_exist(ledger):
    client, mod = ledger
    import sqlite3
    conn = sqlite3.connect(mod.DB_PATH)
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()]
    assert "improvement.v1" in versions
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"experiments", "experiment_events", "missions", "leases"} <= tables  # extends, not replaces
    conn.close()


# ---- mission completion verifier ------------------------------------------

def _open_mission(client, action="verify completion"):
    r = client.post("/mission", json={
        "action": action,
        "repo": "llm_station",
        "branch": "test/completion",
        "risk": "L1",
        "requires_approval": False,
    })
    assert r.status_code == 200
    return r.json()["id"]


def _add_event(client, mid, kind, detail):
    r = client.post(f"/mission/{mid}/event", json={"kind": kind, "payload": {"detail": detail}})
    assert r.status_code == 200


def _forecast(expected):
    return {
        "expected_state_before": {"card": "Backlog"},
        "expected_state_after": expected,
        "expected_events": ["mission.verification"],
        "expected_no_change": ["provider_keys", "raw_transcripts"],
        "privacy_boundary": "hashes_and_refs_only",
        "rollback_or_revert_plan": "delete local evidence package",
    }


def _verification(observed, evidence_refs):
    return {
        "observed_state_after": observed,
        "evidence_refs": evidence_refs,
        "verifier_result": "matched_forecast",
    }


def _action(command="noop-scan"):
    return {
        "command_or_tool": command,
        "target_ref": "repo:llm_station",
        "observed_state_before": {"repo": "unchanged"},
        "action": "read_only_scan",
    }


def test_generic_status_cannot_set_done_without_completion_verifier(ledger):
    client, _ = ledger
    mid = _open_mission(client, "generic done rejection")

    r = client.post(f"/mission/{mid}/status", params={"status": "done"})

    assert r.status_code == 409
    assert "verify-completion" in r.text


def test_completion_verifier_marks_done_only_with_matching_evidence(ledger):
    client, _ = ledger
    mid = _open_mission(client, "completion pass")
    expected = {"card": "Done", "repo": "unchanged"}
    _add_event(client, mid, "mission.forecast", _forecast(expected))
    _add_event(client, mid, "mission.action", _action())
    _add_event(
        client,
        mid,
        "mission.verification",
        _verification(expected, ["evaluation/system-validation/test-run/BASELINE.md"]),
    )

    r = client.post(f"/mission/{mid}/verify-completion")

    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["verdict"]["status"] == "PASS"
    detail = client.get(f"/mission/{mid}").json()
    assert detail["mission"]["status"] == "done"
    assert any(event["kind"] == "mission.completion_verdict" for event in detail["events"])


def test_completion_verifier_blocks_missing_evidence_refs(ledger):
    client, _ = ledger
    mid = _open_mission(client, "completion missing evidence")
    expected = {"card": "Done"}
    _add_event(client, mid, "mission.forecast", _forecast(expected))
    _add_event(client, mid, "mission.verification", _verification(expected, []))

    r = client.post(f"/mission/{mid}/verify-completion")

    assert r.status_code == 200
    assert r.json()["status"] == "blocked"
    assert any("evidence_refs" in reason for reason in r.json()["verdict"]["reasons"])


def test_completion_verifier_blocks_repeated_action_signature(ledger):
    client, _ = ledger
    mid = _open_mission(client, "completion repeated action")
    expected = {"repo": "unchanged"}
    _add_event(client, mid, "mission.forecast", _forecast(expected))
    _add_event(client, mid, "mission.action", _action())
    _add_event(client, mid, "mission.action", _action())
    _add_event(
        client,
        mid,
        "mission.verification",
        _verification(expected, ["evaluation/system-validation/test-run/COMMANDS.md"]),
    )

    r = client.post(f"/mission/{mid}/verify-completion")

    assert r.status_code == 200
    assert r.json()["status"] == "blocked"
    assert any("repeated action signature" in reason for reason in r.json()["verdict"]["reasons"])

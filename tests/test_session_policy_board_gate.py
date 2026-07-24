"""AGT-14 packet 2: tighten-only policy gate for agent board proposals."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from command_center.agent_sessions import policy_engine, spec_bridge
from command_center.agent_sessions.events import AgentEvent
from command_center.agent_sessions.registry import HarnessRegistry
from command_center.agent_sessions.store import SessionStore
from command_center.agent_sessions.worker_app import build_app
from command_center.schemas.session_policy import PolicyHandler, PolicyVerdict


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"
TOKEN = "board-policy-worker-token"
OPERATOR = "human-board-token"
SIGNING_SECRET = "board-signing-secret"

CALL_CAP = PolicyHandler.MAX_TOOL_CALLS_PER_SESSION.value
COST_BUDGET = PolicyHandler.COST_BUDGET.value

BOARDS = {"schema_version": "command-center.kanban-boards.v1", "boards": []}
DOMAINS = {
    "schema_version": "command-center.domain-surfaces.v1",
    "domains": [{
        "domain_id": "improvements",
        "title": "Improvements",
        "card_component": "generic_task",
        "source": "board_store",
        "board_id": "improvements",
        "columns": ["Observed", "Ready", "In Progress", "Done"],
        "column_actions": {
            "Ready": "stage_card",
            "In Progress": "start_todo",
            "Done": "finish_todo",
        },
        "empty_state": {"title": "No work yet", "hint": "add a card"},
    }],
}


class _Usage:
    def __init__(self, cost: float) -> None:
        self.cost = cost

    def session_cost_usd(self, _session_id: str) -> float:
        return self.cost


class _WorkerProxy:
    """Cockpit client adapter backed by the real worker FastAPI endpoint."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.calls: list[tuple[str, str, str]] = []

    def evaluate_board_change_policy(
        self, session_id: str, *, author_harness: str, kind: str,
    ):
        self.calls.append((session_id, author_harness, kind))
        return self.client.post(
            f"/api/agent-sessions/{session_id}/board-change-policy",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"author_harness": author_harness, "kind": kind},
        )


class _PolicyCallForbidden:
    def evaluate_board_change_policy(self, *_args, **_kwargs):
        raise AssertionError("flag-off proposal path must not consult policy")


def _seed_configs(tmp_path: Path) -> None:
    (tmp_path / "domain_surfaces.yaml").write_text(
        yaml.safe_dump(DOMAINS), encoding="utf-8")
    (tmp_path / "kanban_boards.yaml").write_text(
        yaml.safe_dump(BOARDS), encoding="utf-8")


def _policy_stack(monkeypatch, tmp_path: Path, rule: dict, *, cost: float | None = None):
    specs_dir = tmp_path / "agent-session-specs"
    specs_dir.mkdir()
    (specs_dir / "board-policy.yaml").write_text(yaml.safe_dump({
        "name": "board-policy",
        "instructions": "Propose board changes through the governed endpoint.",
        "harness": "codex_agent",
        "capability_profile": "deep_code",
        "mode": "workspace",
        "policy_refs": ["board-guard"],
    }), encoding="utf-8")
    policy_path = tmp_path / "session_policies.yaml"
    policy_path.write_text(yaml.safe_dump({
        "schema_version": "command-center.session-policies.v1",
        "policy_sets": [{
            "name": "board-guard",
            "level": "session",
            "rules": [rule],
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(spec_bridge, "AGENT_SESSION_SPECS_DIR", specs_dir)
    monkeypatch.setattr(policy_engine, "SESSION_POLICIES_CONFIG", policy_path)

    store = SessionStore()
    record = store.create_session(
        harness="codex_agent", conversation_id="conversation-1", repo_id="repo-1")
    store.append_event(record.session_id, AgentEvent(
        "session_started", {"spec_name": "board-policy"}))
    usage = _Usage(cost) if cost is not None else None
    worker = TestClient(build_app(
        store=store, token=TOKEN, registry=HarnessRegistry([]),
        usage_service=usage))
    return store, record.session_id, _WorkerProxy(worker)


def _cockpit(
    monkeypatch, tmp_path: Path, *, policy_enabled: bool, worker,
) -> tuple[object, TestClient]:
    _seed_configs(tmp_path)
    if policy_enabled:
        monkeypatch.setenv("AGENT_SESSION_POLICIES_ENABLED", "1")
    else:
        monkeypatch.delenv("AGENT_SESSION_POLICIES_ENABLED", raising=False)
    monkeypatch.setenv("KANBAN_UI_HUMAN_OPERATORS", OPERATOR)
    monkeypatch.setenv("KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET", SIGNING_SECRET)

    module_name = f"agent_kanban_ui_board_policy_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(module_name, APP)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "AGENT_SESSIONS_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(mod, "BOARD_CHANGE_APPLY_ENABLED", True)
    monkeypatch.setattr(mod, "_agent_worker_client", worker)
    return mod, TestClient(mod.app)


def _plan(client: TestClient, session_id: str | None = None):
    body = {
        "domain_id": "improvements",
        "columns": ["Observed", "Ready", "In Progress", "Done", "Deferred"],
        "author_harness": "codex_agent",
        "rationale": "agent proposed a reversible format change",
    }
    if session_id is not None:
        body["session_id"] = session_id
    return client.post("/api/board-changes/plan-format", json=body)


def _apply_without_token(client: TestClient, payload: dict):
    return client.post("/api/board-changes/apply", json=payload)


def test_flag_off_is_identical_and_never_consults_policy(monkeypatch, tmp_path):
    store = SessionStore()
    session = store.create_session(
        harness="codex_agent", conversation_id="conversation-1", repo_id="repo-1")
    store.append_event(session.session_id, AgentEvent("session_started", {}))
    _mod, client = _cockpit(
        monkeypatch, tmp_path, policy_enabled=False, worker=_PolicyCallForbidden())

    planned = _plan(client)
    assert planned.status_code == 200, planned.text
    assert set(planned.json()) == {
        "proposal_id", "target_board", "before_columns", "after_columns",
        "diff", "preview", "apply_payload",
    }
    assert not any(event.type.startswith("policy_")
                   for event in store.events_since(session.session_id))

    blocked = _apply_without_token(client, planned.json()["apply_payload"])
    assert blocked.status_code == 403
    assert "token is required" in blocked.json()["detail"]
    assert yaml.safe_load((tmp_path / "domain_surfaces.yaml").read_text(
        encoding="utf-8")) == DOMAINS


def test_flag_on_deny_blocks_before_proposal_and_records_typed_event(
    monkeypatch, tmp_path,
):
    store, session_id, worker = _policy_stack(
        monkeypatch, tmp_path,
        {"handler": CALL_CAP, "params": {"limit": 0}})
    _mod, client = _cockpit(
        monkeypatch, tmp_path, policy_enabled=True, worker=worker)

    from command_center.kanban_sync import board_change

    monkeypatch.setattr(
        board_change, "make_proposal",
        lambda **_kwargs: pytest.fail("DENY must run before proposal creation"))
    denied = _plan(client, session_id)

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "policy_denied"
    assert "proposal_id" not in denied.json()
    event = store.events_since(session_id)[-1]
    assert event.type == "policy_denied"
    assert event.payload == {
        "verdict": "deny",
        "tool": "board_change:update_board_format",
        "level": "session",
        "policy_set": "board-guard",
        "handler": CALL_CAP,
        "note": None,
    }
    assert not (tmp_path / ".board-change-rollback").exists()


def test_flag_on_ask_records_existing_wall_route_and_never_auto_approves(
    monkeypatch, tmp_path,
):
    store, session_id, worker = _policy_stack(
        monkeypatch, tmp_path,
        {"handler": COST_BUDGET, "params": {
            "max_cost_usd": 100, "ask_thresholds_usd": [0],
        }},
        cost=0,
    )
    _mod, client = _cockpit(
        monkeypatch, tmp_path, policy_enabled=True, worker=worker)

    planned = _plan(client, session_id)
    assert planned.status_code == 200, planned.text
    body = planned.json()
    assert body["policy"]["verdict"] == "ask"
    assert body["policy"]["approval_surface"] == "board_change_human_wall"
    routed = store.events_since(session_id)[-1]
    assert routed.type == "approval_required"
    assert routed.payload["approval_surface"] == "board_change_human_wall"
    assert routed.payload["requires_human_token"] is True
    assert "approval_id" not in routed.payload
    assert store._approvals == {}

    blocked = _apply_without_token(client, body["apply_payload"])
    assert blocked.status_code == 403
    assert "token is required" in blocked.json()["detail"]

    minted = client.post("/api/board-changes/approval-token", json={
        "proposal_id": body["proposal_id"], "operator": OPERATOR})
    assert minted.status_code == 200, minted.text
    applied = client.post("/api/board-changes/apply", json={
        **body["apply_payload"],
        "approval_token": minted.json()["approval_token"],
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["receipt"]["approved_by"] == OPERATOR


@pytest.mark.parametrize(
    ("rule", "cost", "proposal_status", "verdict"),
    [
        ({"handler": CALL_CAP, "params": {"limit": 100}}, None, 200, "allow"),
        ({"handler": COST_BUDGET, "params": {
            "max_cost_usd": 100, "ask_thresholds_usd": [0],
        }}, 0, 200, "ask"),
        ({"handler": CALL_CAP, "params": {"limit": 0}}, None, 403, "deny"),
    ],
)
def test_no_policy_verdict_can_apply_without_the_human_token(
    monkeypatch, tmp_path, rule, cost, proposal_status, verdict,
):
    _store, session_id, worker = _policy_stack(
        monkeypatch, tmp_path, rule, cost=cost)
    _mod, client = _cockpit(
        monkeypatch, tmp_path, policy_enabled=True, worker=worker)

    proposed = _plan(client, session_id)
    assert proposed.status_code == proposal_status
    if proposal_status == 200:
        if verdict == "allow":
            assert "policy" not in proposed.json()
        payload = proposed.json()["apply_payload"]
    else:
        assert proposed.json()["detail"]["verdict"] == PolicyVerdict.DENY.value
        payload = {
            "author_harness": "codex_agent",
            "kind": "update_board_format",
            "target_board": "improvements",
            "before": DOMAINS,
            "after": DOMAINS,
            "rationale": f"synthetic {verdict} floor probe",
            "created_at": "2026-07-24T00:00:00+00:00",
        }

    blocked = _apply_without_token(client, payload)
    assert blocked.status_code == 403
    assert "token is required" in blocked.json()["detail"]


def test_board_action_shape_binds_harness_and_session():
    from command_center.agent_sessions.policy_engine import ToolAction

    action = ToolAction(
        tool_name="board_change:create_board",
        is_os_tool=False,
        estimated_cost_usd=None,
        session_tool_call_count=1,
        author_harness="codex_agent",
        session_id="agent-session-1",
    )
    assert action.author_harness == "codex_agent"
    assert action.session_id == "agent-session-1"
    assert action.is_os_tool is False
    with pytest.raises(ValueError, match="supplied together"):
        ToolAction(
            tool_name="board_change:create_board",
            is_os_tool=False,
            estimated_cost_usd=None,
            session_tool_call_count=1,
            author_harness="codex_agent",
        )

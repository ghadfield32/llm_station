"""Phase 5 wiring — the board-change PREVIEW/APPLY cockpit endpoints.

The load-bearing property (review note N1): the approver allowlist comes from
SERVER config (KANBAN_UI_HUMAN_OPERATORS via the env), never from the request
body, and apply is double-opt-in + fails closed. Preview never writes.
Hermetic: CONFIGS_DIR is a tmp dir seeded with empty-but-valid configs; the real
Pydantic validators and the atomic config journal run.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"

_DOMAINS = {"schema_version": "command-center.domain-surfaces.v1", "domains": []}
_BOARDS = {"schema_version": "command-center.kanban-boards.v1", "boards": []}


def _seed(tmp: Path) -> None:
    (tmp / "domain_surfaces.yaml").write_text(yaml.safe_dump(_DOMAINS), encoding="utf-8")
    (tmp / "kanban_boards.yaml").write_text(yaml.safe_dump(_BOARDS), encoding="utf-8")


def _load(monkeypatch, tmp_path, *, apply_enabled=False, operators=None, secret=None):
    from fastapi.testclient import TestClient
    _seed(tmp_path)
    spec = importlib.util.spec_from_file_location("akui_bc_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["akui_bc_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(mod, "BOARD_CHANGE_APPLY_ENABLED", apply_enabled)
    if operators is None:
        monkeypatch.delenv("KANBAN_UI_HUMAN_OPERATORS", raising=False)
    else:
        monkeypatch.setenv("KANBAN_UI_HUMAN_OPERATORS", operators)
    if secret is None:
        monkeypatch.delenv("KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET", raising=False)
    else:
        monkeypatch.setenv("KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET", secret)
    return mod, TestClient(mod.app)


def _domains_on_disk(tmp_path):
    return yaml.safe_load((tmp_path / "domain_surfaces.yaml").read_text(encoding="utf-8"))


# ── preview: read-only ───────────────────────────────────────────────────────
def test_preview_is_read_only(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path)
    r = tc.post("/api/board-changes/preview", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "improvements", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "no-op"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview"]["validates"] is True
    assert body["proposal_id"].startswith("bcp-")
    # nothing was written
    assert _domains_on_disk(tmp_path) == _DOMAINS


def test_preview_flags_invalid_config(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path)
    r = tc.post("/api/board-changes/preview", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS,
        "after": {"schema_version": "WRONG", "domains": "not-a-list"},
        "rationale": "bad"})
    assert r.status_code == 200
    assert r.json()["preview"]["validates"] is False


# ── apply: N1 — operators are server-sourced; fails closed ───────────────────
def test_apply_disabled_by_default(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=False, operators="Geoffrey")
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Geoffrey"})
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]


def test_apply_fails_closed_when_no_operators_configured(monkeypatch, tmp_path):
    # flag on but the server operator set is empty -> nothing can be approved
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators=None)
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Geoffrey"})
    assert r.status_code == 403
    assert _domains_on_disk(tmp_path) == _DOMAINS      # no write


def test_apply_rejects_approver_not_in_server_set(monkeypatch, tmp_path):
    # N1: a request-supplied name that isn't in the SERVER env set is refused —
    # the body cannot inject the allowlist.
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="Geoffrey")
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Mallory"})              # not an authenticated operator
    assert r.status_code == 403
    assert _domains_on_disk(tmp_path) == _DOMAINS


def test_apply_rejects_agent_as_approver(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="codex_agent")
    # even if someone mis-lists the agent as an operator, the agent-harness token
    # is refused as a human approver
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "codex_agent"})
    assert r.status_code == 403


def test_apply_rejects_stale_proposal(monkeypatch, tmp_path):
    # before != live config -> the config drifted since preview -> refuse
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="Geoffrey")
    stale_before = {"schema_version": "command-center.domain-surfaces.v1",
                    "domains": [{"stale": True}]}
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": stale_before, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Geoffrey"})
    assert r.status_code in (400, 403)                 # stale/invalid, never a write
    assert _domains_on_disk(tmp_path) == _DOMAINS


def test_apply_happy_path_writes_and_returns_receipt(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="Geoffrey, Alex")
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "apply the reviewed change", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Geoffrey"})
    assert r.status_code == 200, r.text
    receipt = r.json()["receipt"]
    assert receipt["approved_by"] == "Geoffrey"
    assert receipt["rollback_ref"].startswith("bcp-snap-")
    assert receipt["author_harness"] == "codex_agent"


# ── create_board branch (review note #3) ─────────────────────────────────────
def test_apply_create_board_branch_uses_registry(monkeypatch, tmp_path):
    # exercises the create_board path (registry docs, not domains); before==after
    # empty registry validates and the branch commits via the journal
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="tok-secret")
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "create_board",
        "target_board": "x", "before": _BOARDS, "after": _BOARDS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "tok-secret"})
    assert r.status_code == 200, r.text
    assert r.json()["receipt"]["kind"] == "create_board"


# ── rollback endpoint ────────────────────────────────────────────────────────
def _apply_ok(tc):
    return tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "tok-secret"}).json()["receipt"]


def test_rollback_requires_server_operator(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="tok-secret")
    ref = _apply_ok(tc)["rollback_ref"]
    bad = tc.post("/api/board-changes/rollback",
                  json={"rollback_ref": ref, "approved_by": "Mallory"})
    assert bad.status_code == 403                      # not a server operator
    ok = tc.post("/api/board-changes/rollback",
                 json={"rollback_ref": ref, "approved_by": "tok-secret"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["receipt"]["rollback_ref"] == ref


def test_rollback_unknown_ref_404s(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="tok-secret")
    r = tc.post("/api/board-changes/rollback",
                json={"rollback_ref": "bcp-snap-nope", "approved_by": "tok-secret"})
    assert r.status_code == 404


# ── §8 proposal-bound approval token path ────────────────────────────────────
_TOK = "server-signing-secret"


def test_mint_token_requires_secret_and_operator(monkeypatch, tmp_path):
    # no secret configured -> minting is unavailable
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True, operators="Geoffrey")
    r = tc.post("/api/board-changes/approval-token",
                json={"proposal_id": "bcp-x", "operator": "Geoffrey"})
    assert r.status_code == 403
    # secret set but operator not in the server set -> refused
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True,
                     operators="Geoffrey", secret=_TOK)
    r = tc.post("/api/board-changes/approval-token",
                json={"proposal_id": "bcp-x", "operator": "Mallory"})
    assert r.status_code == 403


def test_apply_requires_token_when_secret_configured(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True,
                     operators="Geoffrey", secret=_TOK)
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approved_by": "Geoffrey"})            # no token -> refused
    assert r.status_code == 403
    assert "token is required" in r.json()["detail"]
    assert _domains_on_disk(tmp_path) == _DOMAINS


def _preview_id(tc):
    return tc.post("/api/board-changes/preview", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r"}).json()["proposal_id"]


def test_token_happy_path_and_single_use(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True,
                     operators="Geoffrey", secret=_TOK)
    # the apply proposal_id is content-addressed off the exact bytes/created_at,
    # so mint against the real proposal_id the apply will compute
    from command_center.kanban_sync.board_change import make_proposal
    pid = make_proposal(author_harness="codex_agent", kind="update_board_format",
                        target_board="x", before=_DOMAINS, after=_DOMAINS,
                        rationale="r", created_at="2026-07-17T00:00:00Z").proposal_id
    tok = tc.post("/api/board-changes/approval-token",
                  json={"proposal_id": pid, "operator": "Geoffrey"}).json()["approval_token"]
    body = {"author_harness": "codex_agent", "kind": "update_board_format",
            "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
            "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
            "approval_token": tok}
    ok = tc.post("/api/board-changes/apply", json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["receipt"]["approved_by"] == "Geoffrey"
    # single-use: the same token cannot be replayed
    replay = tc.post("/api/board-changes/apply", json=body)
    assert replay.status_code == 403
    assert "already used" in replay.json()["detail"]


def test_token_for_a_different_proposal_is_refused(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True,
                     operators="Geoffrey", secret=_TOK)
    tok = tc.post("/api/board-changes/approval-token",
                  json={"proposal_id": "bcp-SOMETHING-ELSE", "operator": "Geoffrey"}
                  ).json()["approval_token"]
    r = tc.post("/api/board-changes/apply", json={
        "author_harness": "codex_agent", "kind": "update_board_format",
        "target_board": "x", "before": _DOMAINS, "after": _DOMAINS,
        "rationale": "r", "created_at": "2026-07-17T00:00:00Z",
        "approval_token": tok})
    assert r.status_code == 403
    assert "different proposal" in r.json()["detail"]
    assert _domains_on_disk(tmp_path) == _DOMAINS


# ── board-FORMAT plan endpoint (structured columns, no browser YAML) ─────────
_BOARD_DOMAINS = {
    "schema_version": "command-center.domain-surfaces.v1",
    "domains": [{
        "domain_id": "improvements", "title": "Improvements",
        "card_component": "generic_task", "source": "board_store",
        "board_id": "improvements",
        "columns": ["Observed", "Ready", "In Progress", "Done"],
        "column_actions": {"Ready": "stage_card", "In Progress": "start_todo",
                           "Done": "finish_todo"},
        "empty_state": {"title": "No work yet", "hint": "add a card"},
    }],
}


def _seed_board(tmp: Path) -> None:
    (tmp / "domain_surfaces.yaml").write_text(yaml.safe_dump(_BOARD_DOMAINS), encoding="utf-8")
    (tmp / "kanban_boards.yaml").write_text(yaml.safe_dump(_BOARDS), encoding="utf-8")


def test_plan_format_computes_before_after_server_side(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path)
    _seed_board(tmp_path)                          # richer config than the empty seed
    r = tc.post("/api/board-changes/plan-format", json={
        "domain_id": "improvements",
        "columns": ["Observed", "Grounded", "Ready", "In Progress", "Verifying", "Done"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["before_columns"] == ["Observed", "Ready", "In Progress", "Done"]
    assert "Grounded" in body["after_columns"] and "Verifying" in body["after_columns"]
    assert body["diff"]["added"] == ["Grounded", "Verifying"]
    assert body["preview"]["validates"] is True
    assert body["proposal_id"].startswith("bcp-")
    # the apply_payload is opaque + server-computed; the browser never authored it
    assert body["apply_payload"]["kind"] == "update_board_format"
    assert body["apply_payload"]["after"]["domains"][0]["columns"] == body["after_columns"]
    # read-only: nothing written
    assert _domains_on_disk(tmp_path)["domains"][0]["columns"] == [
        "Observed", "Ready", "In Progress", "Done"]


def test_plan_format_rejects_unknown_domain(monkeypatch, tmp_path):
    _mod, tc = _load(monkeypatch, tmp_path)
    _seed_board(tmp_path)
    r = tc.post("/api/board-changes/plan-format",
                json={"domain_id": "ghost", "columns": ["A"]})
    assert r.status_code == 400


def test_plan_format_apply_payload_round_trips_through_apply(monkeypatch, tmp_path):
    # the opaque apply_payload + a proposal-bound token drives the real apply
    _mod, tc = _load(monkeypatch, tmp_path, apply_enabled=True,
                     operators="Geoffrey", secret="sek")
    _seed_board(tmp_path)
    plan = tc.post("/api/board-changes/plan-format", json={
        "domain_id": "improvements",
        "columns": ["Observed", "Ready", "In Progress", "Done", "Deferred"]}).json()
    tok = tc.post("/api/board-changes/approval-token",
                  json={"proposal_id": plan["proposal_id"], "operator": "Geoffrey"}
                  ).json()["approval_token"]
    applied = tc.post("/api/board-changes/apply",
                      json={**plan["apply_payload"], "approval_token": tok})
    assert applied.status_code == 200, applied.text
    # the write landed: the board now has the new column
    assert "Deferred" in _domains_on_disk(tmp_path)["domains"][0]["columns"]

"""Phase 5 — board/config change proposals: content-addressed, side-effect-free
preview, and the structural self-approval wall (agents never approve their own
board change). The apply/mutation itself is NOT built here — this is the safe,
reviewable scaffolding that a later human-gated apply consumes.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from command_center.kanban_sync.board_change import (
    BoardChangeProposal,
    BoardChangeReceipt,
    build_board_change_preview,
    make_proposal,
)


def _proposal(**over):
    base = dict(author_harness="codex_agent", kind="update_board_format",
                target_board="improvements", before={"columns": ["a", "b"]},
                after={"columns": ["a", "b", "c"]}, rationale="add Done",
                created_at="2026-07-17T00:00:00Z")
    base.update(over)
    return make_proposal(**base)


def test_proposal_is_content_addressed():
    p = _proposal()
    # same content -> same id; different content -> different id
    assert _proposal().proposal_id == p.proposal_id
    assert _proposal(rationale="different").proposal_id != p.proposal_id


def test_proposal_rejects_tampered_id():
    p = _proposal()
    with pytest.raises(ValidationError, match="content-addressed"):
        BoardChangeProposal(proposal_id="bcp-forged", author_harness=p.author_harness,
                            kind=p.kind, target_board=p.target_board, before=p.before,
                            after=p.after, rationale=p.rationale, created_at=p.created_at)


def test_proposal_author_must_be_an_agent_not_a_human():
    with pytest.raises(ValidationError, match="agent harness"):
        _proposal(author_harness="human")


def test_preview_has_zero_side_effects():
    p = _proposal()
    before_snapshot = dict(p.before)
    prev = build_board_change_preview(p)
    # the proposal is untouched and nothing external changed (pure function)
    assert p.before == before_snapshot
    assert prev.changed_keys == ["columns"]
    assert prev.validates is True


def test_preview_surfaces_validation_failure_without_raising():
    p = _proposal()

    def _reject(_after):
        raise ValueError("bad schema")

    prev = build_board_change_preview(p, validate=_reject)
    assert prev.validates is False
    assert "bad schema" in (prev.validation_error or "")


def test_preview_flags_no_op_and_archive_reversibility():
    same = _proposal(after={"columns": ["a", "b"]})   # == before
    assert any("no effective change" in w for w in build_board_change_preview(same).warnings)
    arch = _proposal(kind="archive_domain")
    assert any("reversible" in w for w in build_board_change_preview(arch).warnings)


def test_receipt_blocks_agent_self_approval():
    p = _proposal()
    # an agent harness id can never be the approver (non-human token), so a
    # self-approval attempt is rejected at receipt construction
    with pytest.raises(ValidationError, match="not a human approver"):
        BoardChangeReceipt(proposal_id=p.proposal_id, kind=p.kind,
                           target_board=p.target_board, applied_at="t",
                           approved_by="codex_agent",   # == the proposing agent
                           rollback_ref="snap-1", author_harness="codex_agent")


def test_receipt_requires_human_and_rollback_ref():
    p = _proposal()
    with pytest.raises(ValidationError):
        BoardChangeReceipt(proposal_id=p.proposal_id, kind=p.kind,
                           target_board=p.target_board, applied_at="t",
                           approved_by="Geoffrey", rollback_ref="",   # no rollback
                           author_harness="codex_agent")
    ok = BoardChangeReceipt(proposal_id=p.proposal_id, kind=p.kind,
                            target_board=p.target_board, applied_at="t",
                            approved_by="Geoffrey", rollback_ref="snap-1",
                            author_harness="codex_agent")
    assert ok.approved_by == "Geoffrey" and ok.rollback_ref == "snap-1"


def test_no_delete_or_wall_kind_is_representable():
    # the proposal vocabulary has no hard-delete / approve / merge / deploy kind
    with pytest.raises(ValidationError):
        _proposal(kind="delete_board")
    with pytest.raises(ValidationError):
        _proposal(kind="merge")


# ---- human-gated apply / rollback (the wall crossing) -----------------------
# Hardened after the independent adversarial review (FAIL → these lock each
# confirmed bypass). The gate is an ALLOWLIST: human_operators is the
# authenticated set the endpoint supplies; an agent cannot mint it.

from command_center.kanban_sync.board_change import (  # noqa: E402
    apply_board_change, rollback_board_change)
from command_center.kanban_sync.events import (  # noqa: E402
    GovernanceViolation, is_human_owned_status)

OPS = {"Geoffrey"}          # the authenticated human-operator allowlist


def test_apply_snapshots_before_writing_and_returns_receipt():
    p = _proposal()
    order = []
    receipt = apply_board_change(
        p, approved_by="Geoffrey", human_operators=OPS,
        apply_config=lambda _p: order.append("write"),
        snapshot=lambda _p: order.append("snap") or "snap-42",
        now=lambda: "2026-07-17T01:00:00Z")
    assert order == ["snap", "write"]           # reversible BEFORE the write
    assert receipt.rollback_ref == "snap-42"
    assert receipt.approved_by == "Geoffrey"


def test_apply_writes_exactly_the_proposed_config():
    p = _proposal()
    written = {}
    apply_board_change(p, approved_by="Geoffrey", human_operators=OPS,
                       apply_config=lambda pr: written.update(pr.after),
                       snapshot=lambda _p: "s1", now=lambda: "t")
    assert written == {"columns": ["a", "b", "c"]}


# --- #1: a free-text name that isn't an authenticated operator is refused ----
def test_apply_rejects_approver_not_in_operator_allowlist():
    p = _proposal()
    calls = []
    with pytest.raises(GovernanceViolation, match="authenticated human-operator"):
        apply_board_change(p, approved_by="Geoffrey", human_operators=set(),
                           apply_config=lambda _p: calls.append("w"),
                           snapshot=lambda _p: calls.append("s") or "s1",
                           now=lambda: "t")
    assert calls == []          # nothing ran — the free-text name proved nothing


# --- #2a: another agent HARNESS id is refused even if mis-allowlisted --------
def test_apply_rejects_a_different_agent_harness():
    p = _proposal()          # author == codex_agent
    calls = []
    with pytest.raises(GovernanceViolation):
        apply_board_change(p, approved_by="claude_code_local",   # a real harness id
                           human_operators={"claude_code_local"},  # even if mis-allowlisted
                           apply_config=lambda _p: calls.append("w"),
                           snapshot=lambda _p: calls.append("s") or "s1",
                           now=lambda: "t")
    assert calls == []          # a known agent harness is never a human approver


# --- #2b: a zero-width-Unicode disguise of the author's own name is refused --
def test_apply_rejects_unicode_disguised_self_approval():
    p = _proposal()                      # author_harness == "codex_agent"
    disguised = "codex​_agent"      # looks like the author to a human eye
    calls = []
    with pytest.raises(GovernanceViolation):
        apply_board_change(p, approved_by=disguised, human_operators={disguised},
                           apply_config=lambda _p: calls.append("w"),
                           snapshot=lambda _p: calls.append("s") or "s1",
                           now=lambda: "t")
    assert calls == []


# --- #3: rollback by the proposing agent is blocked BEFORE restore() ---------
def test_rollback_blocks_proposing_agent_before_restore():
    p = _proposal()
    receipt = apply_board_change(p, approved_by="Geoffrey", human_operators=OPS,
                                 apply_config=lambda _p: None,
                                 snapshot=lambda _p: "snap-77", now=lambda: "t")
    restored = []
    with pytest.raises(GovernanceViolation):
        rollback_board_change(receipt, restored_by="codex_agent",   # the author
                              human_operators={"codex_agent"},
                              restore=lambda ref: restored.append(ref),
                              now=lambda: "t2")
    assert restored == []       # the write NEVER fired — gate is before restore


def test_rollback_requires_operator_and_restores_from_ref():
    p = _proposal()
    receipt = apply_board_change(p, approved_by="Geoffrey", human_operators=OPS,
                                 apply_config=lambda _p: None,
                                 snapshot=lambda _p: "snap-9", now=lambda: "t")
    restored = []
    rb = rollback_board_change(receipt, restored_by="Geoffrey", human_operators=OPS,
                               restore=lambda ref: restored.append(ref),
                               now=lambda: "t2")
    assert restored == ["snap-9"] and rb.rollback_ref == "snap-9"


# --- #4: mutating the proposal after preview is caught at apply --------------
def test_apply_refuses_mutated_proposal():
    p = _proposal()
    p.after["columns"].append("MALICIOUS")   # in-place mutation post-construction
    calls = []
    with pytest.raises(GovernanceViolation, match="content changed"):
        apply_board_change(p, approved_by="Geoffrey", human_operators=OPS,
                           apply_config=lambda _pr: calls.append("w"),
                           snapshot=lambda _p: calls.append("s") or "s1",
                           now=lambda: "t")
    assert calls == []          # integrity check fires before snapshot/write


# --- #5: the receipt validator itself rejects the "user" sentinel ------------
def test_receipt_rejects_user_sentinel_directly():
    p = _proposal()
    with pytest.raises(ValidationError):
        BoardChangeReceipt(proposal_id=p.proposal_id, kind=p.kind,
                           target_board=p.target_board, applied_at="t",
                           approved_by="user", rollback_ref="s1",
                           author_harness="codex_agent")


# --- #6: the underlying kanban wall resists the same Unicode disguise --------
def test_is_human_owned_status_resists_unicode_disguise():
    assert is_human_owned_status("Appro​ved") is True
    assert is_human_owned_status("Ａpproved") is True   # fullwidth 'A' → NFKC 'A'


# --- N1: the operator allowlist is server-sourced, never agent-reachable -----

from command_center.kanban_sync.board_change import (  # noqa: E402
    human_operators_from_env)


def test_human_operators_come_from_server_env_only():
    # the ONLY input is the server env mapping — there is no request/agent path
    ops = human_operators_from_env({"KANBAN_UI_HUMAN_OPERATORS": "Geoffrey, Alex"})
    assert ops == {"Geoffrey", "Alex"}


def test_no_operators_configured_fails_closed():
    # no server config -> empty allowlist -> nothing can be approved (N1 fail-safe)
    ops = human_operators_from_env({})
    assert ops == frozenset()
    p = _proposal()
    with pytest.raises(GovernanceViolation):
        apply_board_change(p, approved_by="Geoffrey", human_operators=ops,
                           apply_config=lambda _p: None,
                           snapshot=lambda _p: "s1", now=lambda: "t")


# ── §8 proposal-bound approval token ─────────────────────────────────────────

from command_center.kanban_sync.board_change import (  # noqa: E402
    mint_approval_token, verify_approval_token, token_secret_from_env)

_SECRET = "server-signing-secret"


def _token(proposal_id="bcp-x", operator="Geoffrey", issued_at=1000, nonce="n1", ttl=300):
    return mint_approval_token(proposal_id=proposal_id, operator=operator,
                               secret=_SECRET, issued_at=issued_at, nonce=nonce,
                               ttl_seconds=ttl)


def test_token_round_trip_verifies():
    tok = _token()
    got = verify_approval_token(tok, proposal_id="bcp-x", secret=_SECRET,
                                now=1100, spent_nonces=set())
    assert got.operator == "Geoffrey" and got.nonce == "n1"


def test_token_signature_tamper_rejected():
    tok = _token()
    payload, _sig = tok.split(".", 1)
    forged = f"{payload}.{'0' * 64}"
    with pytest.raises(GovernanceViolation, match="signature"):
        verify_approval_token(forged, proposal_id="bcp-x", secret=_SECRET,
                              now=1100, spent_nonces=set())


def test_token_is_bound_to_one_proposal():
    tok = _token(proposal_id="bcp-A")
    with pytest.raises(GovernanceViolation, match="different proposal"):
        verify_approval_token(tok, proposal_id="bcp-B", secret=_SECRET,
                              now=1100, spent_nonces=set())


def test_token_expires():
    tok = _token(issued_at=1000, ttl=300)   # expires at 1300
    with pytest.raises(GovernanceViolation, match="expired"):
        verify_approval_token(tok, proposal_id="bcp-x", secret=_SECRET,
                              now=1301, spent_nonces=set())


def test_token_is_single_use():
    tok = _token(nonce="used-1")
    with pytest.raises(GovernanceViolation, match="already used"):
        verify_approval_token(tok, proposal_id="bcp-x", secret=_SECRET,
                              now=1100, spent_nonces={"used-1"})


def test_token_requires_a_secret():
    with pytest.raises(GovernanceViolation, match="not set"):
        mint_approval_token(proposal_id="bcp-x", operator="Geoffrey", secret="",
                            issued_at=1000, nonce="n1")


def test_token_secret_from_env():
    assert token_secret_from_env({"KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET": "s"}) == "s"
    assert token_secret_from_env({}) is None

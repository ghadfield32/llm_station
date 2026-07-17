"""Phase 5 — first-class board/config change proposals (propose → preview →
human confirm → apply → receipt → rollback).

The TASK dimension already has this loop (work_graph/planner.py: preview() vs
commit() → TaskBatchReceipt). BOARD/CONFIG changes had the substrate scattered
across _commit_board_module_configs' journal, runtime_backup snapshots, and
config_audit.jsonl but no single reviewable object. This module is that object.

SECURITY MODEL (hardened after an independent adversarial review found the first
cut used a name-blocklist that a motivated agent could defeat):

  * The human gate is an ALLOWLIST, not a blocklist. `apply`/`rollback` require
    `human_operators` — the set of authenticated human identities supplied by
    the ENDPOINT from the request's auth context. An agent cannot mint or extend
    that set, so it cannot name itself (or a plausible human) into approval.
  * All actor comparisons are NFKC-normalized with zero-width/control chars
    stripped, so a Unicode disguise ("codex​_agent") cannot slip an equality
    check.
  * The gate is checked BEFORE any snapshot, write, or restore — in one shared
    function used by apply AND rollback, so the two can never drift.
  * Proposals are frozen and their before/after are deep-copied at construction;
    apply re-verifies the content hash, so an in-place mutation between preview
    and apply is rejected (preview and apply always act on identical bytes).
  * `build_board_change_preview` is pure (no writes).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import unicodedata
from typing import Any, Iterable, Literal

from pydantic import model_validator

from ..schemas.base import Strict
from .events import GovernanceViolation

# Board-change kinds an agent may PROPOSE. Deliberately excludes any hard-delete
# of canonical work and every wall verb — archiving is reversible; there is no
# "delete_board"/"approve"/"merge"/"deploy"/"publish" proposal kind to build.
BoardChangeKind = Literal[
    "create_board",          # add a new board + domain surface
    "update_board_format",   # columns/labels/filters/KPIs on an existing board
    "archive_domain",        # reversible archive (never hard delete)
]

# Actor tokens that are never a human, matched after normalization. The human
# ALLOWLIST is the real gate; this is defense-in-depth so a non-human value can
# never read as approved even if a caller passes a bad allowlist. The known
# agent harness ids are listed explicitly (the registry is the source of truth;
# duplicated here as a backstop) because not all of them end in "agent"
# (e.g. claude_code_local).
_NON_HUMAN_TOKENS = frozenset({
    "", "agent", "system", "user", "bot", "assistant",
    "fake", "codex_agent", "claude_code_local", "claude_agent",
    "openrouter_agent",
})


def _normalize_actor(name: str | None) -> str:
    """NFKC-normalize, strip zero-width/control chars (Unicode category Cf/Cc),
    trim, casefold. Defeats invisible-character disguises of an actor name."""
    s = unicodedata.normalize("NFKC", name or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) not in {"Cf", "Cc"})
    return s.strip().casefold()


def _is_non_human(actor_norm: str) -> bool:
    """True for anything that cannot be a human approver: an empty value or an
    exact match to a known non-human/agent token. Exact-match (not an
    `endswith` heuristic) so a real operator whose handle merely ends in
    'agent'/'bot' is not locked out (review note N2) — the authenticated
    allowlist is the primary gate; this is the backstop."""
    return actor_norm in _NON_HUMAN_TOKENS


def _canonical_hash(payload: dict[str, Any]) -> str:
    """Content address for a proposal: stable SHA-256 over canonical JSON, so
    a preview/receipt references exactly the bytes that were reviewed. Rejects
    non-JSON-native values rather than str()-coercing them (which would not be
    injective and could collide)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return "bcp-" + hashlib.sha256(blob).hexdigest()[:24]


def _proposal_hash(*, author_harness: str, kind: str, target_board: str,
                   before: dict[str, Any], after: dict[str, Any],
                   rationale: str, created_at: str) -> str:
    return _canonical_hash({
        "author_harness": author_harness, "kind": kind,
        "target_board": target_board, "before": before, "after": after,
        "rationale": rationale, "created_at": created_at})


class BoardChangeProposal(Strict):
    """A reviewable, content-addressed board/config change an agent PROPOSES.
    Frozen and content-addressed: proposal_id is the hash of its own content and
    the object cannot be reassigned after construction."""
    model_config = {"extra": "forbid", "frozen": True}

    proposal_id: str
    author_harness: str                 # the proposing agent (never a human)
    kind: BoardChangeKind
    target_board: str
    before: dict[str, Any]              # read-only snapshot of current config
    after: dict[str, Any]              # the proposed config
    rationale: str = ""
    created_at: str

    @model_validator(mode="after")
    def _check_identity_and_author(self) -> "BoardChangeProposal":
        if not self.author_harness.strip():
            raise ValueError("author_harness is required (the proposing agent)")
        if _is_non_human(_normalize_actor(self.author_harness)) is False:
            # author must be an agent — a human/system value here would let a
            # proposal masquerade as human-authored/approved.
            raise ValueError(
                "author_harness must be an agent harness (e.g. 'codex_agent'), "
                "not a human/system actor")
        expected = _proposal_hash(
            author_harness=self.author_harness, kind=self.kind,
            target_board=self.target_board, before=self.before,
            after=self.after, rationale=self.rationale,
            created_at=self.created_at)
        if self.proposal_id != expected:
            raise ValueError(
                f"proposal_id {self.proposal_id!r} does not match its content "
                f"(expected {expected!r}) — a proposal is content-addressed")
        return self

    def verify_integrity(self) -> None:
        """Recompute the content hash and confirm it still matches proposal_id.
        Called at apply time: if before/after were mutated in place after
        construction, the hash won't match and this raises — so apply can never
        write bytes different from what preview showed."""
        expected = _proposal_hash(
            author_harness=self.author_harness, kind=self.kind,
            target_board=self.target_board, before=self.before,
            after=self.after, rationale=self.rationale,
            created_at=self.created_at)
        if self.proposal_id != expected:
            raise GovernanceViolation(
                "proposal content changed after it was created — refusing to "
                "apply bytes different from the reviewed preview")


def make_proposal(*, author_harness: str, kind: BoardChangeKind,
                  target_board: str, before: dict[str, Any],
                  after: dict[str, Any], rationale: str, created_at: str,
                  ) -> BoardChangeProposal:
    """Mint a content-addressed proposal. before/after are DEEP-COPIED so a
    later mutation of the caller's dicts cannot change the stored (hashed)
    content."""
    before, after = copy.deepcopy(before), copy.deepcopy(after)
    pid = _proposal_hash(
        author_harness=author_harness, kind=kind, target_board=target_board,
        before=before, after=after, rationale=rationale, created_at=created_at)
    return BoardChangeProposal(
        proposal_id=pid, author_harness=author_harness, kind=kind,
        target_board=target_board, before=before, after=after,
        rationale=rationale, created_at=created_at)


class BoardChangePreview(Strict):
    """The side-effect-free review of a proposal: what would change, whether it
    validates, and any warnings. Computing this NEVER writes."""
    proposal_id: str
    kind: BoardChangeKind
    target_board: str
    changed_keys: list[str]            # top-level config keys that differ
    validates: bool
    validation_error: str | None = None
    warnings: list[str]


class BoardChangeReceipt(Strict):
    """Durable evidence that a proposal was applied by a HUMAN, with the info
    needed to roll it back. Written only after the shared human gate passed."""
    proposal_id: str
    kind: BoardChangeKind
    target_board: str
    applied_at: str
    approved_by: str                   # the authenticated human who confirmed
    rollback_ref: str                  # journal/snapshot id restoring `before`
    author_harness: str                # who proposed (for the audit trail)

    @model_validator(mode="after")
    def _record_integrity(self) -> "BoardChangeReceipt":
        # Belt-and-suspenders: a receipt can only be minted for a non-human-token
        # approver that differs from the author. The AUTHORITATIVE gate (the
        # human-operator allowlist) runs in apply/rollback before any write; this
        # guards direct construction so a hand-built receipt can't record an
        # agent as approver.
        who = _normalize_actor(self.approved_by)
        if _is_non_human(who):
            raise ValueError(
                f"approved_by {self.approved_by!r} is not a human approver")
        if who == _normalize_actor(self.author_harness):
            raise ValueError("agents never self-approve a board change")
        if not self.rollback_ref.strip():
            raise ValueError("rollback_ref is required — every apply is reversible")
        return self


_OPERATORS_ENV = "KANBAN_UI_HUMAN_OPERATORS"


def human_operators_from_env(env: dict[str, str] | None = None) -> frozenset[str]:
    """The authenticated human-operator allowlist — sourced ONLY from SERVER
    configuration (the KANBAN_UI_HUMAN_OPERATORS env var, comma-separated),
    NEVER from a request body or anything an agent can influence (review note
    N1). An endpoint's apply/rollback handler MUST build `human_operators` from
    this, so an agent cannot name itself into the approver set. Fails closed: no
    env → empty set → nothing can be approved until an operator is configured.

    SECURITY (review note #1): because the cockpit has no per-user SSO, each
    entry must be a SECRET APPROVAL TOKEN (a bearer secret the human enters when
    confirming), NOT a guessable display name — otherwise an agent that controls
    the request body could pass a known name (e.g. the repo's git author) and
    self-approve. The token lives only in the server env + the human's hands;
    the agent never sees it. (A signed per-proposal token bound to an
    authenticated channel is the intended future hardening.)
    """
    env = env if env is not None else dict(os.environ)
    raw = env.get(_OPERATORS_ENV, "")
    return frozenset(op.strip() for op in raw.split(",") if op.strip())


# ── §8 proposal-bound approval token ─────────────────────────────────────────
# The hardening the plan names before board mutation is enabled: replace a
# static operator secret with a SHORT-LIVED, SINGLE-USE, proposal-BOUND, signed
# approval. The token authorizes applying EXACTLY one proposal_id (which is
# itself the content hash — so it's content-bound), by one operator, until it
# expires; the server secret makes it unforgeable and the nonce makes it
# single-use (the apply path records spent nonces). Even a leaked operator
# token cannot be replayed against a different proposal or after expiry.
_TOKEN_SECRET_ENV = "KANBAN_UI_BOARD_CHANGE_SIGNING_SECRET"
_DEFAULT_TTL_SECONDS = 300


class ApprovalToken(Strict):
    """A verified, decoded approval — what verify returns so the caller can
    record the (single-use) nonce and audit the operator."""
    proposal_id: str
    operator: str
    expires_at: int
    nonce: str


def token_secret_from_env(env: dict[str, str] | None = None) -> str | None:
    env = env if env is not None else dict(os.environ)
    return (env.get(_TOKEN_SECRET_ENV) or "").strip() or None


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def mint_approval_token(*, proposal_id: str, operator: str, secret: str,
                        issued_at: int, nonce: str,
                        ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> str:
    """Mint a signed, proposal-bound, expiring, single-use approval token.
    Caller MUST have verified `operator` is an authenticated human first."""
    if not secret:
        raise GovernanceViolation(
            f"{_TOKEN_SECRET_ENV} is not set — cannot mint approval tokens")
    body = {"proposal_id": proposal_id, "operator": operator,
            "expires_at": int(issued_at) + int(ttl_seconds), "nonce": nonce}
    payload = base64.urlsafe_b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).decode("ascii")
    return f"{payload}.{_sign(payload, secret)}"


def verify_approval_token(token: str, *, proposal_id: str, secret: str,
                          now: int, spent_nonces: Iterable[str]) -> ApprovalToken:
    """Verify a token is valid for THIS proposal_id: signature matches, not
    expired, bound to this proposal, and its nonce not already spent. Raises
    GovernanceViolation otherwise. The caller MUST record the returned nonce as
    spent so the token cannot be reused."""
    if not secret:
        raise GovernanceViolation(
            f"{_TOKEN_SECRET_ENV} is not set — cannot verify approval tokens")
    try:
        payload, sig = token.split(".", 1)
    except (ValueError, AttributeError) as exc:
        raise GovernanceViolation("malformed approval token") from exc
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        raise GovernanceViolation("approval token signature is invalid")
    try:
        body = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception as exc:
        raise GovernanceViolation("approval token payload is unreadable") from exc
    if body.get("proposal_id") != proposal_id:
        raise GovernanceViolation(
            "approval token is bound to a different proposal — re-approve the "
            "change you actually reviewed")
    if int(now) > int(body.get("expires_at", 0)):
        raise GovernanceViolation("approval token has expired — re-approve")
    if body.get("nonce") in set(spent_nonces):
        raise GovernanceViolation("approval token already used (single-use)")
    return ApprovalToken(proposal_id=body["proposal_id"],
                         operator=str(body.get("operator", "")),
                         expires_at=int(body["expires_at"]),
                         nonce=str(body["nonce"]))


def _assert_human_approver(
    approver: str, *, author_harness: str, human_operators: Iterable[str],
) -> None:
    """THE shared human gate (used by apply AND rollback, always before any
    write). Allowlist-based: `human_operators` is the set of authenticated human
    identities supplied by the endpoint from the request's auth context — an
    agent cannot mint or extend it. Raises GovernanceViolation (the kanban wall's
    error class) so a failure reads as a wall hit, never a soft validation miss.
    """
    who = _normalize_actor(approver)
    if _is_non_human(who):
        raise GovernanceViolation(
            f"approver {approver!r} is not a human (normalized {who!r})")
    if who == _normalize_actor(author_harness):
        raise GovernanceViolation(
            f"approver {approver!r} is the proposing agent {author_harness!r} — "
            f"agents never self-approve")
    allowed = {_normalize_actor(h) for h in (human_operators or ())}
    if who not in allowed:
        raise GovernanceViolation(
            f"approver {approver!r} is not in the authenticated human-operator "
            f"set — a free-text name is not proof of a human action")


def _changed_top_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted({k for k in set(before) | set(after)
                   if before.get(k) != after.get(k)})


def build_board_change_preview(
    proposal: BoardChangeProposal,
    *,
    validate: Any | None = None,
) -> BoardChangePreview:
    """Compute the review of a proposal with ZERO side effects.

    `validate` is an optional callable(after_config) -> None that raises on an
    invalid proposed config (injected so this stays pure — the caller passes the
    real contract validator). Nothing here writes to disk, the board store, or
    the event log.
    """
    changed = _changed_top_keys(proposal.before, proposal.after)
    warnings: list[str] = []
    if not changed:
        warnings.append("no effective change — before and after are identical")
    if proposal.kind == "archive_domain":
        warnings.append("archive is reversible; canonical work is never deleted")

    validates, verr = True, None
    if validate is not None:
        try:
            validate(proposal.after)
        except Exception as exc:               # the injected contract validator
            validates, verr = False, f"{type(exc).__name__}: {exc}"[:300]

    return BoardChangePreview(
        proposal_id=proposal.proposal_id, kind=proposal.kind,
        target_board=proposal.target_board, changed_keys=changed,
        validates=validates, validation_error=verr, warnings=warnings)


def apply_board_change(
    proposal: BoardChangeProposal,
    *,
    approved_by: str,
    human_operators: Iterable[str],
    apply_config: Any,
    snapshot: Any,
    now: Any,
) -> BoardChangeReceipt:
    """Apply a proposal — HUMAN-gated, reversible, evidence-producing.

    Order is load-bearing:
      1. assert the shared human-operator gate FIRST — a rejected approver raises
         before anything is snapshotted or written;
      2. re-verify the proposal's content hash — refuse if it changed since
         preview (no writing bytes the human didn't review);
      3. snapshot the current state (rollback_ref) so the change is reversible;
      4. cross the wall exactly once via the injected governed writer;
      5. return a durable receipt.

    `human_operators` is the authenticated set from the endpoint. `apply_config`,
    `snapshot`, `now` are the real governed writer / rollback-point maker /
    clock — injected so the wall crossing is testable and callers pass audited
    machinery rather than a shortcut.
    """
    _assert_human_approver(approved_by, author_harness=proposal.author_harness,
                           human_operators=human_operators)     # (1) gate
    proposal.verify_integrity()                                 # (2) reviewed==applied
    rollback_ref = str(snapshot(proposal))                      # (3) reversible first
    apply_config(proposal)                                      # (4) the ONE write
    return BoardChangeReceipt(                                   # (5) durable evidence
        proposal_id=proposal.proposal_id, kind=proposal.kind,
        target_board=proposal.target_board, applied_at=str(now()),
        approved_by=approved_by, rollback_ref=rollback_ref,
        author_harness=proposal.author_harness)


def rollback_board_change(
    receipt: BoardChangeReceipt,
    *,
    restored_by: str,
    human_operators: Iterable[str],
    restore: Any,
    now: Any,
) -> BoardChangeReceipt:
    """Reverse an applied change from its receipt. Human-gated by the SAME shared
    function as apply, checked BEFORE `restore()` runs (the review found the
    first cut restored before its gate). Returns a NEW receipt recording the
    reversal — the audit trail keeps both the apply and the rollback."""
    _assert_human_approver(restored_by, author_harness=receipt.author_harness,
                           human_operators=human_operators)     # gate BEFORE restore
    restore(receipt.rollback_ref)                               # governed restore path
    return BoardChangeReceipt(
        proposal_id=receipt.proposal_id, kind=receipt.kind,
        target_board=receipt.target_board, applied_at=str(now()),
        approved_by=restored_by, rollback_ref=receipt.rollback_ref,
        author_harness=receipt.author_harness)

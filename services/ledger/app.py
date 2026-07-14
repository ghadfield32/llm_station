"""
Task Ledger — durable mission state for the command center.

Every autonomous mission gets a row and an append-only event log so you can
resume, audit, approve, or kill it — even after a restart. This is the piece
that makes "keep working while I'm away" safe rather than just possible.

Storage: SQLite (single file, survives restarts via a mounted volume).
Exposes a small REST API consumed by Hermes (to record work) and by the
Ledger UI / judgectl CLI (to review and gate).
"""

import os
import json
import sqlite3
import secrets
import hashlib
from datetime import datetime, timezone
from contextlib import closing
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("LEDGER_DB", "/data/ledger.db")
# Shared secret an operator presents to sign approvals (keep in .env / pw manager).
APPROVAL_SECRET = os.environ.get("LEDGER_APPROVAL_SECRET", "")

RiskTier = Literal["L0", "L1", "L2", "L3", "L4"]
Status = Literal["open", "awaiting_approval", "approved", "running",
                 "blocked", "done", "killed", "failed"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Experiment-registry schema. MIRROR of the canonical source of truth in
# src/command_center/improvement/ledger_schema.py (SCHEMA_SQL). This container
# cannot import the command_center package, so the DDL is duplicated here and kept
# honest by tests/test_ledger_experiment_schema.py, which fails on any drift.
# These tables EXTEND the same ledger.db — they do not create a second database.
EXPERIMENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id     TEXT PRIMARY KEY,
    mission_id        TEXT,
    title             TEXT,
    owner             TEXT,
    target_type       TEXT,
    target_ref        TEXT,
    risk_tier         TEXT,
    status            TEXT,
    baseline_version  TEXT,
    candidate_version TEXT,
    definition_json   TEXT,
    definition_hash   TEXT,
    baseline_locked   INTEGER DEFAULT 0,
    baseline_hash     TEXT,
    verifier_verdict  TEXT,
    human_decision    TEXT,
    canary_status     TEXT,
    rollback_status   TEXT,
    created_at        TEXT,
    updated_at        TEXT,
    expires_at        TEXT
);

CREATE TABLE IF NOT EXISTS experiment_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    ts            TEXT,
    kind          TEXT,
    actor_role    TEXT,
    actor_model   TEXT,
    action        TEXT,
    payload       TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id          TEXT PRIMARY KEY,
    experiment_id   TEXT,
    role            TEXT,
    iteration       INTEGER DEFAULT 0,
    started_at      TEXT,
    finished_at     TEXT,
    status          TEXT,
    cache_state     TEXT,
    commit_ref      TEXT,
    sample_count    INTEGER DEFAULT 0,
    metrics         TEXT,
    budget          TEXT,
    excluded_reason TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    run_id        TEXT,
    name          TEXT,
    kind          TEXT,
    path          TEXT,
    sha256        TEXT,
    bytes         INTEGER,
    ts            TEXT,
    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_links (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id   TEXT,
    to_id     TEXT,
    relation  TEXT,
    ts        TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
"""


# Agent-session schema. MIRROR of the canonical source of truth in
# src/command_center/agent_sessions/ledger_schema.py (SCHEMA_SQL). This container
# cannot import the command_center package, so the DDL is duplicated here and kept
# honest by tests/test_agent_session_ledger_schema.py, which fails on any drift.
# These tables EXTEND the same ledger.db — they do not create a second database.
AGENT_SESSION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id          TEXT PRIMARY KEY,
    conversation_id     TEXT,
    harness              TEXT,
    provider_profile    TEXT,
    model                TEXT,
    external_session_id TEXT,
    repo_id              TEXT,
    workspace_path       TEXT,
    worktree_path        TEXT,
    branch                TEXT,
    base_branch          TEXT,
    permission_profile   TEXT,
    worker_id            TEXT,
    status                TEXT,
    created_at           TEXT,
    updated_at           TEXT,
    last_event_sequence  INTEGER DEFAULT 0,
    cost_usd              REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS agent_session_events (
    session_id TEXT,
    sequence   INTEGER,
    ts         TEXT,
    type       TEXT,
    payload    TEXT,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS agent_session_approvals (
    approval_id  TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    action        TEXT NOT NULL,
    status        TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolved_at   TEXT,
    approved      INTEGER,
    reason        TEXT,
    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
"""


# Unified runtime usage schema. MIRROR of the canonical source of truth in
# src/command_center/usage/ledger_schema.py (SCHEMA_SQL). Duplicated here
# because this container cannot import command_center; kept honest by
# tests/test_usage_ledger_schema.py, which fails on any drift. Additive —
# extends the same ledger.db, does not create a second database.
USAGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_usage_samples (
    sample_id           TEXT PRIMARY KEY,
    runtime_id          TEXT NOT NULL,
    source              TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    ingested_at         TEXT NOT NULL,
    source_hash         TEXT NOT NULL UNIQUE,
    sample_kind         TEXT NOT NULL DEFAULT 'request_delta',
    input_tokens        INTEGER DEFAULT 0,
    cached_input_tokens INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    calls               INTEGER DEFAULT 0,
    sessions            INTEGER DEFAULT 0,
    tool_calls          INTEGER DEFAULT 0,
    duration_ms         INTEGER DEFAULT 0,
    cost_usd            REAL,
    cost_source         TEXT,
    window_start        TEXT,
    window_end          TEXT,
    aggregation_key     TEXT,
    repository_scans    INTEGER DEFAULT 0,
    test_runs           INTEGER DEFAULT 0,
    retries             INTEGER DEFAULT 0,
    failed_calls        INTEGER DEFAULT 0,
    worker_restarts     INTEGER DEFAULT 0,
    session_resumes     INTEGER DEFAULT 0,
    tenant_id           TEXT,
    workspace_id        TEXT,
    user_id             TEXT,
    conversation_id     TEXT,
    agent_session_id    TEXT,
    mission_id          TEXT,
    repo_id             TEXT,
    provider_request_id TEXT,
    source_record_id    TEXT,
    model               TEXT,
    effort              TEXT,
    context_mode        TEXT,
    api_equivalent_cost_usd REAL
);

CREATE TABLE IF NOT EXISTS model_limit_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    runtime_id        TEXT NOT NULL,
    bucket_id         TEXT NOT NULL,
    scope             TEXT NOT NULL,
    source            TEXT NOT NULL,
    state             TEXT NOT NULL,
    observed_at       TEXT NOT NULL,
    ingested_at       TEXT NOT NULL,
    source_hash       TEXT NOT NULL UNIQUE,
    label             TEXT,
    used_percent      REAL,
    used_amount       REAL,
    limit_amount      REAL,
    remaining_amount  REAL,
    unit              TEXT,
    window_seconds    INTEGER,
    reset_at          TEXT,
    plan_type         TEXT,
    credits_remaining REAL
);

CREATE TABLE IF NOT EXISTS model_availability_events (
    event_id    TEXT PRIMARY KEY,
    runtime_id  TEXT NOT NULL,
    source      TEXT NOT NULL,
    state       TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    source_hash TEXT NOT NULL UNIQUE,
    reason      TEXT,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS model_usage_alerts (
    alert_id   TEXT PRIMARY KEY,
    runtime_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    dedup_key  TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    subject_id TEXT,
    threshold  REAL,
    message    TEXT,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS model_routing_decisions (
    decision_id                 TEXT PRIMARY KEY,
    created_at                  TEXT NOT NULL,
    mission_id                  TEXT,
    runtime_id                  TEXT NOT NULL,
    selected                    INTEGER NOT NULL,
    reason                      TEXT,
    usage_snapshot_id           TEXT,
    limit_snapshot_ids          TEXT,
    availability_at_selection   TEXT,
    budget_state_at_selection   TEXT
);

CREATE TABLE IF NOT EXISTS model_usage_collection_state (
    collector_id          TEXT PRIMARY KEY,
    updated_at            TEXT NOT NULL,
    last_success_at       TEXT,
    last_cursor           TEXT,
    last_source_record_id TEXT,
    last_error            TEXT,
    consecutive_failures  INTEGER DEFAULT 0,
    next_eligible_at      TEXT,
    auth_state            TEXT DEFAULT 'unknown'
);

CREATE INDEX IF NOT EXISTS ix_usage_samples_runtime_observed
    ON model_usage_samples (runtime_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_usage_samples_mission
    ON model_usage_samples (mission_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_repo
    ON model_usage_samples (repo_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_user
    ON model_usage_samples (user_id);
CREATE INDEX IF NOT EXISTS ix_usage_samples_session
    ON model_usage_samples (agent_session_id);
CREATE INDEX IF NOT EXISTS ix_limit_snapshots_runtime_bucket_observed
    ON model_limit_snapshots (runtime_id, bucket_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_availability_runtime_observed
    ON model_availability_events (runtime_id, observed_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
"""

# Durable Universal Capture (intake) schema. MIRROR of the canonical source of
# truth in src/command_center/intake/ledger_schema.py (SCHEMA_SQL). Duplicated
# here because this container can't import the package; kept identical by
# tests/test_capture_ledger_schema.py, which fails on any drift. Additive.
CAPTURE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id        TEXT PRIMARY KEY,
    raw_content       TEXT NOT NULL,
    source_type       TEXT NOT NULL DEFAULT 'text',
    source_ref        TEXT,
    captured_at       TEXT NOT NULL,
    ingested_at       TEXT NOT NULL,
    captured_by       TEXT,
    current_board_id  TEXT,
    current_card_id   TEXT,
    conversation_id   TEXT,
    batch_id          TEXT,
    attachments       TEXT,
    requested_mode    TEXT NOT NULL DEFAULT 'save_only',
    processing_status TEXT NOT NULL DEFAULT 'captured',
    classification    TEXT,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capture_events (
    event_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT
);

CREATE INDEX IF NOT EXISTS ix_captures_status ON captures (processing_status);
CREATE INDEX IF NOT EXISTS ix_captures_batch ON captures (batch_id);
CREATE INDEX IF NOT EXISTS ix_capture_events_cap
    ON capture_events (capture_id, event_seq);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()

# Durable work-graph schema. MIRROR of the canonical source of truth in
# src/command_center/work_graph/ledger_schema.py (SCHEMA_SQL). Duplicated here
# because this container can't import the package; kept identical by
# tests/test_work_graph_ledger_schema.py, which fails on any drift. Additive.
WORKGRAPH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS work_items (
    work_item_id      TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT,
    kind              TEXT NOT NULL DEFAULT 'todo',
    canonical_status  TEXT NOT NULL DEFAULT 'backlog',
    primary_board_id  TEXT,
    owner             TEXT,
    priority          TEXT,
    due_at            TEXT,
    capture_id        TEXT,
    capture_batch_id  TEXT,
    packet_id         TEXT,
    conversation_id   TEXT,
    mission_id        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_placements (
    placement_id    TEXT PRIMARY KEY,
    work_item_id    TEXT NOT NULL,
    board_id        TEXT NOT NULL,
    domain_id       TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    placement_stage TEXT,
    card_component  TEXT NOT NULL DEFAULT 'generic_task',
    local_fields    TEXT,
    created_at      TEXT NOT NULL,
    removed_at      TEXT
);

CREATE TABLE IF NOT EXISTS work_edges (
    edge_id            TEXT PRIMARY KEY,
    from_work_item_id  TEXT NOT NULL,
    to_work_item_id    TEXT NOT NULL,
    relation           TEXT NOT NULL,
    blocking           INTEGER NOT NULL DEFAULT 0,
    reason             TEXT,
    evidence_refs      TEXT,
    created_by         TEXT,
    created_at         TEXT NOT NULL,
    removed_at         TEXT
);

CREATE TABLE IF NOT EXISTS work_events (
    event_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    payload      TEXT
);

CREATE INDEX IF NOT EXISTS ix_work_placements_item
    ON work_placements (work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_placements_board
    ON work_placements (board_id);
CREATE INDEX IF NOT EXISTS ix_work_edges_from ON work_edges (from_work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_edges_to ON work_edges (to_work_item_id);
CREATE INDEX IF NOT EXISTS ix_work_events_item
    ON work_events (work_item_id, event_seq);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()

# BYTE-IDENTICAL mirror of command_center.work_graph.telemetry_schema.SCHEMA_SQL
# (routing.telemetry.v1). tests/test_routing_telemetry_schema.py guards drift.
ROUTING_TELEMETRY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS routing_corrections (
    correction_id      TEXT PRIMARY KEY,
    at                 TEXT NOT NULL,
    title              TEXT NOT NULL,
    ref                TEXT,
    suggested_board_id TEXT,
    chosen_board_id    TEXT,
    accepted           INTEGER NOT NULL DEFAULT 0,
    matched_keywords   TEXT,
    conversation_id    TEXT,
    capture_id         TEXT,
    source             TEXT NOT NULL DEFAULT 'chat'
);

CREATE INDEX IF NOT EXISTS ix_routing_corrections_at
    ON routing_corrections (at);
CREATE INDEX IF NOT EXISTS ix_routing_corrections_chosen
    ON routing_corrections (chosen_board_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()

# BYTE-IDENTICAL mirror of command_center.work_graph.packet_ledger_schema
# .PACKET_SCHEMA_SQL (packet.v1). tests/test_packet_ledger_schema.py guards drift.
PACKET_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS readiness_packets (
    packet_id         TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft',
    capture_id        TEXT,
    conversation_id   TEXT,
    research          TEXT,
    plan_json         TEXT NOT NULL,
    plan_summary_json TEXT NOT NULL,
    runbook_json      TEXT,
    acceptance_json   TEXT,
    reviews_json      TEXT,
    current_revision  INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    committed_at      TEXT
);

CREATE TABLE IF NOT EXISTS packet_revisions (
    packet_id      TEXT NOT NULL,
    revision       INTEGER NOT NULL,
    content_digest TEXT NOT NULL,
    snapshot_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (packet_id, revision)
);

CREATE TABLE IF NOT EXISTS packet_reviews (
    packet_id     TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    role          TEXT NOT NULL,
    status        TEXT NOT NULL,
    summary       TEXT,
    findings_json TEXT,
    session_id    TEXT,
    reviewed_at   TEXT NOT NULL,
    PRIMARY KEY (packet_id, revision, role)
);

CREATE TABLE IF NOT EXISTS packet_events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id TEXT NOT NULL,
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    payload   TEXT
);

CREATE TABLE IF NOT EXISTS packet_work_links (
    packet_id    TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    PRIMARY KEY (packet_id, work_item_id)
);

CREATE INDEX IF NOT EXISTS ix_packet_revisions_packet
    ON packet_revisions (packet_id);
CREATE INDEX IF NOT EXISTS ix_packet_reviews_packet
    ON packet_reviews (packet_id, revision);
CREATE INDEX IF NOT EXISTS ix_packet_events_packet
    ON packet_events (packet_id, event_seq);
CREATE INDEX IF NOT EXISTS ix_packet_work_links_packet
    ON packet_work_links (packet_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
);
""".strip()


# Experiment lifecycle edges + the human-only wall, mirrored from
# command_center.improvement.lifecycle. The Ledger enforces the structural walls
# even on its REST surface: entering Canary/Promoted requires a valid human HMAC
# approval — the SAME wall mission approvals use, not a second mechanism.
_EXP_EDGES = {
    "Proposed": {"Baseline Ready", "Rejected", "Deferred", "Expired"},
    "Baseline Ready": {"Running", "Inconclusive", "Rejected", "Deferred", "Expired"},
    "Running": {"Running", "Awaiting Verification", "Inconclusive",
                "Rejected", "Deferred", "Expired"},
    "Awaiting Verification": {"Verified", "Inconclusive", "Rejected",
                              "Deferred", "Expired"},
    "Verified": {"Awaiting Human Promotion", "Rejected", "Deferred", "Expired"},
    "Awaiting Human Promotion": {"Canary", "Promoted", "Rejected",
                                 "Deferred", "Expired"},
    "Canary": {"Promoted", "Rolled Back", "Rejected", "Expired"},
    "Promoted": {"Rolled Back"},
}
_EXP_HUMAN_ONLY = {"Canary", "Promoted"}


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(_db()) as c:
        c.executescript(EXPERIMENT_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("improvement.v1", _now()))
        c.executescript(AGENT_SESSION_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("agent_sessions.v1", _now()))
        c.executescript(USAGE_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("usage.v1", _now()))
        c.executescript(CAPTURE_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("capture.v1", _now()))
        c.executescript(WORKGRAPH_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("workgraph.v1", _now()))
        c.executescript(ROUTING_TELEMETRY_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("routing.telemetry.v1", _now()))
        c.executescript(PACKET_SCHEMA_SQL)
        c.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                  "VALUES (?, ?)", ("packet.v1", _now()))
        c.executescript("""
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            created_at TEXT, updated_at TEXT,
            action TEXT, repo TEXT, branch TEXT,
            risk TEXT, status TEXT,
            requires_approval INTEGER DEFAULT 0,
            diff_summary TEXT, test_results TEXT, outcome TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT, ts TEXT, kind TEXT, payload TEXT,
            FOREIGN KEY(mission_id) REFERENCES missions(id)
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT, ts TEXT, actor TEXT, decision TEXT, signature TEXT,
            FOREIGN KEY(mission_id) REFERENCES missions(id)
        );
        -- Workspace leases: one active lease per (repo, branch) so two agents
        -- can never edit the same checkout. This is per-task isolation, enforced.
        CREATE TABLE IF NOT EXISTS leases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT, repo TEXT, branch TEXT, worktree TEXT,
            ts TEXT, released INTEGER DEFAULT 0,
            FOREIGN KEY(mission_id) REFERENCES missions(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_lease
            ON leases(repo, branch) WHERE released = 0;
        """)
        c.commit()


app = FastAPI(title="Task Ledger", version="2.0.0")
init_db()


class MissionIn(BaseModel):
    action: str
    repo: str = "unknown"
    branch: str = ""
    risk: RiskTier = "L4"
    requires_approval: bool = True


class EventIn(BaseModel):
    kind: str           # "model_call" | "command" | "judge_verdict" | "note" | "diff" | "tests"
    payload: dict


class GlobalEventIn(BaseModel):
    source: str
    kind: str
    summary: str = ""
    evidence: dict = Field(default_factory=dict)


class ApprovalIn(BaseModel):
    actor: str
    decision: Literal["approve", "reject"]
    signature: str      # HMAC the operator computes from APPROVAL_SECRET + mission_id + decision


def _sign(mission_id: str, decision: str) -> str:
    return hashlib.sha256(
        f"{APPROVAL_SECRET}:{mission_id}:{decision}".encode()
    ).hexdigest()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/mission")
def open_mission(body: MissionIn):
    mid = "T-" + secrets.token_hex(4)
    with closing(_db()) as c:
        c.execute(
            "INSERT INTO missions (id, created_at, updated_at, action, repo, branch, "
            "risk, status, requires_approval) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, _now(), _now(), body.action, body.repo, body.branch, body.risk,
             "awaiting_approval" if body.requires_approval else "open",
             int(body.requires_approval)),
        )
        c.commit()
    return {"id": mid, "status": "awaiting_approval" if body.requires_approval else "open"}


@app.post("/mission/{mid}/event")
def add_event(mid: str, body: EventIn):
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM missions WHERE id=?", (mid,)).fetchone():
            raise HTTPException(404, "mission not found")
        c.execute(
            "INSERT INTO events (mission_id, ts, kind, payload) VALUES (?,?,?,?)",
            (mid, _now(), body.kind, json.dumps(body.payload)),
        )
        # surface diffs/tests onto the mission row for quick scanning
        if body.kind == "diff":
            c.execute("UPDATE missions SET diff_summary=?, updated_at=? WHERE id=?",
                      (body.payload.get("summary", ""), _now(), mid))
        if body.kind == "tests":
            c.execute("UPDATE missions SET test_results=?, updated_at=? WHERE id=?",
                      (json.dumps(body.payload), _now(), mid))
        c.commit()
    return {"ok": True}


def _event_detail(payload: dict) -> dict:
    detail = payload.get("detail", payload)
    return detail if isinstance(detail, dict) else {}


def _action_signature(payload: dict) -> tuple[str, str, str]:
    detail = _event_detail(payload)
    return (
        str(detail.get("command_or_tool", "")),
        str(detail.get("target_ref", "")),
        str(detail.get("action", detail.get("command", ""))),
    )


def _completion_verdict(rows: list[sqlite3.Row]) -> dict:
    forecast = None
    verification = None
    action_signatures = []
    reasons: list[str] = []

    for row in rows:
        payload = json.loads(row["payload"])
        if row["kind"] == "mission.forecast":
            forecast = payload
        elif row["kind"] == "mission.verification":
            verification = payload
        elif row["kind"] == "mission.action":
            signature = _action_signature(payload)
            if any(signature):
                action_signatures.append(signature)

    if forecast is None:
        reasons.append("missing mission.forecast event")
    if verification is None:
        reasons.append("missing mission.verification event")

    evidence_refs = []
    if forecast is not None and verification is not None:
        forecast_detail = _event_detail(forecast)
        verification_detail = _event_detail(verification)
        expected = forecast_detail.get("expected_state_after")
        observed = verification_detail.get("observed_state_after")
        if expected is not None and observed != expected:
            reasons.append(
                f"observed_state_after does not match expected_state_after: {observed!r} != {expected!r}"
            )
        evidence_refs = verification_detail.get("evidence_refs", [])
        if not isinstance(evidence_refs, list) or not evidence_refs:
            reasons.append("verification must include non-empty evidence_refs")

    if len(action_signatures) != len(set(action_signatures)):
        reasons.append("repeated action signature detected; strategy change required")

    return {
        "status": "BLOCKED" if reasons else "PASS",
        "reasons": reasons,
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [],
    }


@app.post("/mission/{mid}/verify-completion")
def verify_completion(mid: str):
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM missions WHERE id=?", (mid,)).fetchone():
            raise HTTPException(404, "mission not found")
        rows = c.execute(
            "SELECT ts, kind, payload FROM events WHERE mission_id=? ORDER BY id",
            (mid,),
        ).fetchall()
        verdict = _completion_verdict(rows)
        status = "done" if verdict["status"] == "PASS" else "blocked"
        c.execute(
            "UPDATE missions SET status=?, outcome=?, updated_at=? WHERE id=?",
            (status, json.dumps(verdict), _now(), mid),
        )
        c.execute(
            "INSERT INTO events (mission_id, ts, kind, payload) VALUES (?,?,?,?)",
            (mid, _now(), "mission.completion_verdict", json.dumps(verdict)),
        )
        c.commit()
    return {"id": mid, "status": status, "verdict": verdict}


@app.post("/events")
def add_global_event(body: GlobalEventIn):
    """Record a non-mission operational event.

    Proactive checks use this for report-only findings. Mission-producing checks
    still create a normal mission and then write mission-scoped events.
    """
    with closing(_db()) as c:
        c.execute(
            "INSERT INTO events (mission_id, ts, kind, payload) VALUES (?,?,?,?)",
            (
                None,
                _now(),
                body.kind,
                json.dumps(
                    {
                        "source": body.source,
                        "summary": body.summary,
                        "evidence": body.evidence,
                    }
                ),
            ),
        )
        c.commit()
    return {"ok": True}


@app.post("/mission/{mid}/approve")
def approve(mid: str, body: ApprovalIn):
    if not APPROVAL_SECRET:
        raise HTTPException(500, "LEDGER_APPROVAL_SECRET not set")
    if not secrets.compare_digest(body.signature, _sign(mid, body.decision)):
        raise HTTPException(403, "bad signature — approval rejected")
    new_status = "approved" if body.decision == "approve" else "blocked"
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM missions WHERE id=?", (mid,)).fetchone():
            raise HTTPException(404, "mission not found")
        c.execute("INSERT INTO approvals (mission_id, ts, actor, decision, signature) "
                  "VALUES (?,?,?,?,?)", (mid, _now(), body.actor, body.decision, body.signature))
        c.execute("UPDATE missions SET status=?, updated_at=? WHERE id=?",
                  (new_status, _now(), mid))
        c.commit()
    return {"id": mid, "status": new_status}


@app.post("/mission/{mid}/status")
def set_status(mid: str, status: Status, outcome: str = ""):
    if status == "done":
        raise HTTPException(409, "mission completion requires /mission/{id}/verify-completion")
    with closing(_db()) as c:
        c.execute("UPDATE missions SET status=?, outcome=?, updated_at=? WHERE id=?",
                  (status, outcome, _now(), mid))
        c.commit()
    return {"id": mid, "status": status}


class LeaseIn(BaseModel):
    repo: str
    branch: str
    worktree: str = ""


@app.post("/mission/{mid}/lease")
def acquire_lease(mid: str, body: LeaseIn):
    """Acquire the single active lease for (repo, branch). Fails if one exists —
    that's the point: no two agents edit the same checkout."""
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM missions WHERE id=?", (mid,)).fetchone():
            raise HTTPException(404, "mission not found")
        try:
            c.execute(
                "INSERT INTO leases (mission_id, repo, branch, worktree, ts) "
                "VALUES (?,?,?,?,?)",
                (mid, body.repo, body.branch, body.worktree, _now()),
            )
            c.commit()
        except sqlite3.IntegrityError:
            existing = c.execute(
                "SELECT mission_id FROM leases WHERE repo=? AND branch=? AND released=0",
                (body.repo, body.branch)).fetchone()
            raise HTTPException(
                409, f"branch {body.repo}:{body.branch} already leased by "
                     f"{existing['mission_id'] if existing else 'another mission'}")
    return {"ok": True, "repo": body.repo, "branch": body.branch}


@app.post("/mission/{mid}/lease/release")
def release_lease(mid: str, body: LeaseIn):
    with closing(_db()) as c:
        c.execute("UPDATE leases SET released=1 WHERE mission_id=? AND repo=? AND branch=? AND released=0",
                  (mid, body.repo, body.branch))
        c.commit()
    return {"ok": True}


@app.post("/mission/{mid}/kill")
def kill(mid: str):
    """Kill switch: mark cancelled. Workers poll status and stop on 'killed'."""
    with closing(_db()) as c:
        c.execute("UPDATE missions SET status='killed', updated_at=? WHERE id=?",
                  (_now(), mid))
        c.execute("INSERT INTO events (mission_id, ts, kind, payload) VALUES (?,?,?,?)",
                  (mid, _now(), "note", json.dumps({"msg": "KILL requested"})))
        c.commit()
    return {"id": mid, "status": "killed"}


@app.get("/mission/{mid}")
def get_mission(mid: str):
    with closing(_db()) as c:
        m = c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        if not m:
            raise HTTPException(404, "mission not found")
        ev = c.execute("SELECT ts, kind, payload FROM events WHERE mission_id=? ORDER BY id",
                       (mid,)).fetchall()
        ap = c.execute("SELECT ts, actor, decision FROM approvals WHERE mission_id=? ORDER BY id",
                       (mid,)).fetchall()
    return {
        "mission": dict(m),
        "events": [{"ts": e["ts"], "kind": e["kind"], "payload": json.loads(e["payload"])} for e in ev],
        "approvals": [dict(a) for a in ap],
    }


@app.get("/missions")
def list_missions(status: Optional[Status] = None):
    q = "SELECT id, created_at, action, repo, branch, risk, status FROM missions"
    args = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY created_at DESC LIMIT 200"
    with closing(_db()) as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
def ui():
    """Minimal Ledger UI — render missions, expand for full audit trail + kill."""
    with closing(_db()) as c:
        rows = c.execute("SELECT id, created_at, action, repo, branch, risk, status "
                         "FROM missions ORDER BY created_at DESC LIMIT 100").fetchall()
    items = "".join(
        f"<tr><td><a href='/mission/{r['id']}'>{r['id']}</a></td>"
        f"<td>{r['risk']}</td><td>{r['status']}</td>"
        f"<td>{r['repo']}</td><td>{r['branch']}</td>"
        f"<td>{r['action'][:80]}</td>"
        f"<td><form method='post' action='/mission/{r['id']}/kill'>"
        f"<button>kill</button></form></td></tr>"
        for r in rows
    )
    return f"""<!doctype html><html><head><meta charset=utf-8>
    <title>Task Ledger</title>
    <style>body{{font:14px system-ui;margin:2rem}}table{{border-collapse:collapse;width:100%}}
    td,th{{border:1px solid #ddd;padding:6px;text-align:left}}button{{cursor:pointer}}</style>
    </head><body><h1>Task Ledger</h1>
    <table><tr><th>id</th><th>risk</th><th>status</th><th>repo</th><th>branch</th>
    <th>action</th><th></th></tr>{items}</table>
    <p style="color:#666">Reach this over Tailscale only. Kill marks a mission cancelled;
    workers poll status and stop.</p></body></html>"""


# ---- experiment registry (the improvement loop) ----------------------------
# These endpoints store experiment state in the SAME ledger.db. Transition
# enforcement mirrors command_center.improvement.lifecycle; the deep gate
# (deterministic-pass + independent PASS verdict) is enforced by the host-side
# registry the runner/CLI use. Here the Ledger guarantees the structural wall:
# no experiment reaches Canary/Promoted without a valid human HMAC approval.


class ExperimentIn(BaseModel):
    experiment_id: str
    title: str = ""
    owner: str = ""
    target_type: str = ""
    target_ref: str = ""
    risk_tier: str = "L2_local_edits"
    mission_id: Optional[str] = None
    baseline_version: str = ""
    candidate_version: str = ""
    definition_json: str = ""
    definition_hash: str = ""
    expires_at: Optional[str] = None


class ExpEventIn(BaseModel):
    kind: str
    actor_role: str = ""
    actor_model: str = ""
    action: str = ""
    payload: dict = Field(default_factory=dict)


class ExpStatusIn(BaseModel):
    status: str
    actor: Literal["agent", "human"] = "agent"
    signature: str = ""   # required HMAC for transitions into Canary/Promoted


@app.post("/experiment")
def register_experiment(body: ExperimentIn):
    with closing(_db()) as c:
        if c.execute("SELECT 1 FROM experiments WHERE experiment_id=?",
                     (body.experiment_id,)).fetchone():
            raise HTTPException(409, "experiment already registered")
        c.execute(
            "INSERT INTO experiments (experiment_id, mission_id, title, owner, "
            "target_type, target_ref, risk_tier, status, baseline_version, "
            "candidate_version, definition_json, definition_hash, created_at, "
            "updated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.experiment_id, body.mission_id, body.title, body.owner,
             body.target_type, body.target_ref, body.risk_tier, "Proposed",
             body.baseline_version, body.candidate_version, body.definition_json,
             body.definition_hash, _now(), _now(), body.expires_at))
        c.execute("INSERT INTO experiment_events (experiment_id, ts, kind, actor_role, "
                  "actor_model, action, payload) VALUES (?,?,?,?,?,?,?)",
                  (body.experiment_id, _now(), "EXPERIMENT_REGISTERED", "registry", "",
                   f"registered {body.experiment_id}", json.dumps({"status": "Proposed"})))
        c.commit()
    return {"experiment_id": body.experiment_id, "status": "Proposed"}


@app.get("/experiments")
def list_experiments(status: Optional[str] = None):
    q = "SELECT experiment_id, title, target_type, target_ref, status, " \
        "verifier_verdict, human_decision, canary_status FROM experiments"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY created_at DESC LIMIT 200"
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


@app.get("/experiment/{eid}")
def get_experiment(eid: str):
    with closing(_db()) as c:
        m = c.execute("SELECT * FROM experiments WHERE experiment_id=?", (eid,)).fetchone()
        if not m:
            raise HTTPException(404, "experiment not found")
        ev = c.execute("SELECT ts, kind, actor_role, action FROM experiment_events "
                       "WHERE experiment_id=? ORDER BY id", (eid,)).fetchall()
        runs = c.execute("SELECT run_id, role, status, sample_count FROM experiment_runs "
                         "WHERE experiment_id=? ORDER BY started_at", (eid,)).fetchall()
    return {"experiment": dict(m), "events": [dict(e) for e in ev],
            "runs": [dict(r) for r in runs]}


@app.post("/experiment/{eid}/event")
def add_experiment_event(eid: str, body: ExpEventIn):
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM experiments WHERE experiment_id=?", (eid,)).fetchone():
            raise HTTPException(404, "experiment not found")
        c.execute("INSERT INTO experiment_events (experiment_id, ts, kind, actor_role, "
                  "actor_model, action, payload) VALUES (?,?,?,?,?,?,?)",
                  (eid, _now(), body.kind, body.actor_role, body.actor_model,
                   body.action, json.dumps(body.payload)))
        c.commit()
    return {"ok": True}


@app.post("/experiment/{eid}/status")
def set_experiment_status(eid: str, body: ExpStatusIn):
    """Change experiment status. Mirrors the lifecycle walls: the edge must exist,
    and Canary/Promoted require a valid human HMAC approval (the same wall mission
    approvals use). An agent can never self-promote through this endpoint."""
    with closing(_db()) as c:
        row = c.execute("SELECT status FROM experiments WHERE experiment_id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "experiment not found")
        current = row["status"]
        if body.status not in _EXP_EDGES.get(current, set()):
            raise HTTPException(409, f"illegal transition {current!r} -> {body.status!r}")
        if body.status in _EXP_HUMAN_ONLY:
            if body.actor != "human":
                raise HTTPException(403, f"{body.status} is human-only; no self-promotion")
            if not APPROVAL_SECRET:
                raise HTTPException(500, "LEDGER_APPROVAL_SECRET not set")
            if not secrets.compare_digest(body.signature, _sign(eid, body.status)):
                raise HTTPException(403, "bad signature — promotion rejected")
        c.execute("UPDATE experiments SET status=?, updated_at=? WHERE experiment_id=?",
                  (body.status, _now(), eid))
        c.execute("INSERT INTO experiment_events (experiment_id, ts, kind, actor_role, "
                  "action, payload) VALUES (?,?,?,?,?,?)",
                  (eid, _now(), "PROMOTED" if body.status == "Promoted" else "note",
                   body.actor, f"{current} -> {body.status}",
                   json.dumps({"from": current, "to": body.status})))
        c.commit()
    return {"experiment_id": eid, "status": body.status}


# ---- Agent sessions (Claude Agent / Codex Agent / FakeHarness durability) --------
# The Ledger — not the harness — assigns event sequence numbers, transactionally
# with the insert, so a vendor-supplied ordering is never trusted (see
# src/command_center/agent_sessions/store.py SessionStore for the in-memory sibling
# these endpoints back). session_id is server-generated, same pattern as mission ids.

class AgentSessionIn(BaseModel):
    harness: str
    conversation_id: str
    repo_id: str
    provider_profile: str = "default"
    model: Optional[str] = None
    permission_profile: str = "read_only"


class AgentSessionEventIn(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class AgentSessionStatusIn(BaseModel):
    status: str


def _agent_session_row_to_dict(row) -> dict:
    return dict(row)


@app.post("/agent-session")
def create_agent_session(body: AgentSessionIn):
    session_id = "AS-" + secrets.token_hex(4)
    now = _now()
    with closing(_db()) as c:
        c.execute(
            "INSERT INTO agent_sessions (session_id, conversation_id, harness, "
            "provider_profile, model, external_session_id, repo_id, "
            "workspace_path, worktree_path, branch, base_branch, "
            "permission_profile, worker_id, status, created_at, updated_at, "
            "last_event_sequence, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, body.conversation_id, body.harness, body.provider_profile,
             body.model, None, body.repo_id, None, None, None, None,
             body.permission_profile, None, "starting", now, now, 0, 0.0))
        c.commit()
        row = c.execute("SELECT * FROM agent_sessions WHERE session_id=?",
                        (session_id,)).fetchone()
    return _agent_session_row_to_dict(row)


@app.get("/agent-sessions")
def list_agent_sessions(status: Optional[str] = None, conversation_id: Optional[str] = None,
                        repo_id: Optional[str] = None):
    q = "SELECT * FROM agent_sessions"
    conditions = []
    args: list = []
    if status:
        conditions.append("status=?")
        args.append(status)
    if conversation_id:
        conditions.append("conversation_id=?")
        args.append(conversation_id)
    if repo_id:
        conditions.append("repo_id=?")
        args.append(repo_id)
    if conditions:
        q += " WHERE " + " AND ".join(conditions)
    q += " ORDER BY created_at DESC LIMIT 200"
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(q, tuple(args)).fetchall()]


@app.get("/agent-session/{sid}")
def get_agent_session(sid: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM agent_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "agent session not found")
    return _agent_session_row_to_dict(row)


@app.post("/agent-session/{sid}/event")
def append_agent_session_event(sid: str, body: AgentSessionEventIn):
    """Assigns `sequence` here, inside the same transaction as the insert — two
    events for the same session can never race to the same sequence number
    (SQLite's default single-writer semantics make this safe without app-level
    locking)."""
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM agent_sessions WHERE session_id=?",
                         (sid,)).fetchone():
            raise HTTPException(404, "agent session not found")
        next_seq = c.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_session_events "
            "WHERE session_id=?", (sid,)).fetchone()[0]
        now = _now()
        c.execute(
            "INSERT INTO agent_session_events (session_id, sequence, ts, type, "
            "payload) VALUES (?,?,?,?,?)",
            (sid, next_seq, now, body.type, json.dumps(body.payload)))
        c.execute(
            "UPDATE agent_sessions SET last_event_sequence=?, updated_at=? "
            "WHERE session_id=?", (next_seq, now, sid))
        c.commit()
    return {"session_id": sid, "sequence": next_seq, "ts": now}


@app.get("/agent-session/{sid}/events")
def list_agent_session_events(sid: str, after_sequence: int = 0):
    """The reconnect primitive: a client that last saw `after_sequence` gets
    exactly the gap — no duplicates, no misses."""
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM agent_sessions WHERE session_id=?",
                         (sid,)).fetchone():
            raise HTTPException(404, "agent session not found")
        rows = c.execute(
            "SELECT session_id, sequence, ts, type, payload FROM agent_session_events "
            "WHERE session_id=? AND sequence>? ORDER BY sequence", (sid, after_sequence)
        ).fetchall()
    # decode payload here so the client gets a real nested object, not a
    # double-encoded string (matches get_experiment's convention of never
    # handing back a raw payload TEXT column as-is)
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]


@app.post("/agent-session/{sid}/status")
def set_agent_session_status(sid: str, body: AgentSessionStatusIn):
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM agent_sessions WHERE session_id=?",
                         (sid,)).fetchone():
            raise HTTPException(404, "agent session not found")
        now = _now()
        c.execute("UPDATE agent_sessions SET status=?, updated_at=? WHERE session_id=?",
                  (body.status, now, sid))
        c.commit()
    return {"session_id": sid, "status": body.status}


class AgentSessionFieldsIn(BaseModel):
    # Written by a real harness adapter once it has real vendor identity/cost
    # (see src/command_center/agent_sessions/adapters/) — every field optional,
    # only supplied ones are updated; omitted fields are left untouched.
    external_session_id: Optional[str] = None
    worker_id: Optional[str] = None
    model: Optional[str] = None
    provider_profile: Optional[str] = None
    cost_usd: Optional[float] = None


_AGENT_SESSION_FIELD_COLUMNS = (
    "external_session_id", "worker_id", "model", "provider_profile", "cost_usd")


@app.post("/agent-session/{sid}/fields")
def update_agent_session_fields(sid: str, body: AgentSessionFieldsIn):
    updates = {k: v for k, v in body.model_dump().items()
              if k in _AGENT_SESSION_FIELD_COLUMNS and v is not None}
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM agent_sessions WHERE session_id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "agent session not found")
        if updates:
            now = _now()
            set_clause = ", ".join(f"{k}=?" for k in updates)
            c.execute(f"UPDATE agent_sessions SET {set_clause}, updated_at=? WHERE session_id=?",
                     (*updates.values(), now, sid))
            c.commit()
            row = c.execute("SELECT * FROM agent_sessions WHERE session_id=?", (sid,)).fetchone()
    return _agent_session_row_to_dict(row)


class AgentSessionApprovalIn(BaseModel):
    action: str


class AgentSessionApprovalResolveIn(BaseModel):
    approved: bool
    reason: str = ""


def _approval_row_to_dict(row) -> dict:
    d = dict(row)
    d["approved"] = bool(d["approved"]) if d["approved"] is not None else None
    return d


@app.post("/agent-session/{sid}/approval")
def create_agent_session_approval(sid: str, body: AgentSessionApprovalIn):
    with closing(_db()) as c:
        if not c.execute("SELECT 1 FROM agent_sessions WHERE session_id=?",
                         (sid,)).fetchone():
            raise HTTPException(404, "agent session not found")
        approval_id = "APR-" + secrets.token_hex(4)
        now = _now()
        c.execute(
            "INSERT INTO agent_session_approvals (approval_id, session_id, action, "
            "status, requested_at, resolved_at, approved, reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (approval_id, sid, body.action, "pending", now, None, None, ""))
        c.commit()
        row = c.execute("SELECT * FROM agent_session_approvals WHERE approval_id=?",
                        (approval_id,)).fetchone()
    return _approval_row_to_dict(row)


@app.get("/agent-session/approval/{aid}")
def get_agent_session_approval(aid: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM agent_session_approvals WHERE approval_id=?",
                        (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "approval not found")
    return _approval_row_to_dict(row)


@app.post("/agent-session/{sid}/approval/{aid}/resolve")
def resolve_agent_session_approval(sid: str, aid: str, body: AgentSessionApprovalResolveIn):
    """One-use, session-bound: an approval belonging to a different session, or one
    already resolved, is rejected rather than silently re-applied (replay)."""
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM agent_session_approvals WHERE approval_id=?",
                        (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "approval not found")
        if row["session_id"] != sid:
            raise HTTPException(
                403, f"approval {aid!r} does not belong to session {sid!r}")
        if row["status"] == "resolved":
            raise HTTPException(
                409, f"approval {aid!r} was already resolved — replay rejected")
        now = _now()
        c.execute(
            "UPDATE agent_session_approvals SET status=?, resolved_at=?, approved=?, "
            "reason=? WHERE approval_id=?",
            ("resolved", now, 1 if body.approved else 0, body.reason, aid))
        c.commit()
        resolved = c.execute("SELECT * FROM agent_session_approvals WHERE approval_id=?",
                             (aid,)).fetchone()
    return _approval_row_to_dict(resolved)


# ---- Unified runtime usage (usage / limits / availability / alerts) --------
# REST mirror of command_center.usage.store.UsageStore. Ingestion is
# idempotent at the SQL layer (UNIQUE source_hash / dedup_key): a repeat is a
# no-op that returns the already-stored row. Source-priority winner selection
# stays in the CLIENT store (shared with the in-memory backend via
# select_latest_limits/select_latest_availability), so these endpoints just
# store rows and return them all — the client picks the winner, keeping both
# backends behaviourally identical. Fixed column allowlists (never the raw
# body keys) build every INSERT, so an unexpected key can't reach SQL.

_USAGE_SAMPLE_COLS = (
    "sample_id", "runtime_id", "source", "observed_at", "ingested_at", "source_hash",
    "sample_kind", "input_tokens", "cached_input_tokens", "output_tokens",
    "reasoning_tokens", "total_tokens", "calls", "sessions", "tool_calls",
    "duration_ms", "cost_usd", "cost_source", "window_start", "window_end",
    "aggregation_key", "repository_scans", "test_runs", "retries", "failed_calls",
    "worker_restarts", "session_resumes", "tenant_id", "workspace_id", "user_id",
    "conversation_id", "agent_session_id", "mission_id", "repo_id",
    "provider_request_id", "source_record_id",
    "model", "effort", "context_mode", "api_equivalent_cost_usd")
_COLLECTION_STATE_COLS = (
    "collector_id", "updated_at", "last_success_at", "last_cursor",
    "last_source_record_id", "last_error", "consecutive_failures", "next_eligible_at",
    "auth_state")
_LIMIT_COLS = (
    "snapshot_id", "runtime_id", "bucket_id", "scope", "source", "state", "observed_at",
    "ingested_at", "source_hash", "label", "used_percent", "used_amount", "limit_amount",
    "remaining_amount", "unit", "window_seconds", "reset_at", "plan_type",
    "credits_remaining")
_AVAIL_COLS = (
    "event_id", "runtime_id", "source", "state", "observed_at", "ingested_at",
    "source_hash", "reason", "detail")
_ALERT_COLS = (
    "alert_id", "runtime_id", "kind", "dedup_key", "created_at", "subject_id",
    "threshold", "message", "detail")
_ROUTING_COLS = (
    "decision_id", "created_at", "mission_id", "runtime_id", "selected", "reason",
    "usage_snapshot_id", "limit_snapshot_ids", "availability_at_selection",
    "budget_state_at_selection")


def _insert_or_ignore(table: str, cols: tuple, body: dict) -> None:
    values = [body.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    with closing(_db()) as c:
        c.execute(f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) "
                  f"VALUES ({placeholders})", values)
        c.commit()


def _fetch_one(table: str, where_col: str, value) -> dict:
    with closing(_db()) as c:
        row = c.execute(f"SELECT * FROM {table} WHERE {where_col}=?", (value,)).fetchone()
    return dict(row) if row else {}


# ── Universal Capture (intake) — durable backend for the cockpit's LedgerCaptureStore ──
class CaptureIn(BaseModel):
    capture_id: str
    raw_content: str
    source_type: str = "text"
    source_ref: Optional[str] = None
    captured_at: str
    captured_by: Optional[str] = None
    current_board_id: Optional[str] = None
    current_card_id: Optional[str] = None
    conversation_id: Optional[str] = None
    batch_id: Optional[str] = None
    attachments: list = []
    requested_mode: str = "save_only"
    status: str = "captured"


class CaptureEventIn(BaseModel):
    ts: str
    kind: str
    payload: dict = {}


class CaptureStatusIn(BaseModel):
    status: str
    ts: str


class CaptureClassifyIn(BaseModel):
    classification: dict
    ts: str


def _require_capture(c, capture_id: str) -> None:
    if not c.execute("SELECT 1 FROM captures WHERE capture_id=?",
                     (capture_id,)).fetchone():
        raise HTTPException(404, f"no such capture: {capture_id}")


def _capture_view(c, capture_id: str) -> dict:
    row = c.execute("SELECT * FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such capture: {capture_id}")
    d = dict(row)
    d["attachments"] = json.loads(d["attachments"]) if d.get("attachments") else []
    d["classification"] = (json.loads(d["classification"])
                           if d.get("classification") else None)
    ev = c.execute("SELECT COUNT(*) n, MAX(ts) mx FROM capture_events "
                   "WHERE capture_id=?", (capture_id,)).fetchone()
    d["event_count"] = ev["n"] or 0
    d["updated_at"] = ev["mx"] or d.get("updated_at")   # = last event ts (matches in-memory)
    return d


@app.post("/capture")
def create_capture(body: CaptureIn):
    with closing(_db()) as c:
        # idempotent on replay by capture_id — a repeat write is a no-op
        if c.execute("SELECT 1 FROM captures WHERE capture_id=?",
                     (body.capture_id,)).fetchone() is None:
            c.execute(
                "INSERT INTO captures (capture_id, raw_content, source_type, "
                "source_ref, captured_at, ingested_at, captured_by, current_board_id, "
                "current_card_id, conversation_id, batch_id, attachments, "
                "requested_mode, processing_status, classification, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.capture_id, body.raw_content, body.source_type, body.source_ref,
                 body.captured_at, _now(), body.captured_by, body.current_board_id,
                 body.current_card_id, body.conversation_id, body.batch_id,
                 json.dumps(body.attachments), body.requested_mode, body.status,
                 None, body.captured_at))
            c.execute(
                "INSERT INTO capture_events (capture_id, ts, kind, payload) VALUES (?,?,?,?)",
                (body.capture_id, body.captured_at, "status",
                 json.dumps({"status": body.status, "created": True})))
            c.commit()
        return _capture_view(c, body.capture_id)


@app.post("/capture/{capture_id}/event")
def add_capture_event(capture_id: str, body: CaptureEventIn):
    with closing(_db()) as c:
        _require_capture(c, capture_id)
        c.execute("INSERT INTO capture_events (capture_id, ts, kind, payload) "
                  "VALUES (?,?,?,?)",
                  (capture_id, body.ts, body.kind, json.dumps(body.payload)))
        c.commit()
    return {"ok": True}


@app.post("/capture/{capture_id}/status")
def set_capture_status(capture_id: str, body: CaptureStatusIn):
    with closing(_db()) as c:
        _require_capture(c, capture_id)
        c.execute("UPDATE captures SET processing_status=?, updated_at=? WHERE capture_id=?",
                  (body.status, body.ts, capture_id))
        c.execute("INSERT INTO capture_events (capture_id, ts, kind, payload) "
                  "VALUES (?,?,?,?)",
                  (capture_id, body.ts, "status", json.dumps({"status": body.status})))
        c.commit()
        return _capture_view(c, capture_id)


@app.post("/capture/{capture_id}/classify")
def classify_capture(capture_id: str, body: CaptureClassifyIn):
    with closing(_db()) as c:
        _require_capture(c, capture_id)
        c.execute("UPDATE captures SET classification=?, updated_at=? WHERE capture_id=?",
                  (json.dumps(body.classification), body.ts, capture_id))
        c.execute("INSERT INTO capture_events (capture_id, ts, kind, payload) "
                  "VALUES (?,?,?,?)",
                  (capture_id, body.ts, "classify", json.dumps(body.classification)))
        c.commit()
        return _capture_view(c, capture_id)


@app.get("/captures")
def list_captures(status: Optional[str] = None, batch_id: Optional[str] = None):
    q, params = "SELECT capture_id FROM captures", []
    conds = []
    if status is not None:
        conds.append("processing_status=?"); params.append(status)
    if batch_id is not None:
        conds.append("batch_id=?"); params.append(batch_id)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY rowid"      # stable insertion order (matches in-memory)
    with closing(_db()) as c:
        ids = [r["capture_id"] for r in c.execute(q, params).fetchall()]
        return [_capture_view(c, cid) for cid in ids]


@app.get("/capture/{capture_id}")
def get_capture(capture_id: str):
    with closing(_db()) as c:
        return _capture_view(c, capture_id)


@app.get("/capture/{capture_id}/events")
def get_capture_events(capture_id: str):
    with closing(_db()) as c:
        _require_capture(c, capture_id)
        rows = c.execute("SELECT * FROM capture_events WHERE capture_id=? "
                         "ORDER BY event_seq", (capture_id,)).fetchall()
    return [{"capture_id": r["capture_id"], "ts": r["ts"], "kind": r["kind"],
             "payload": json.loads(r["payload"]) if r["payload"] else {}} for r in rows]


# ── Durable work graph — backend for the cockpit's LedgerWorkGraphStore ────────
_WORK_ITEM_COLS = (
    "work_item_id", "title", "description", "kind", "canonical_status",
    "primary_board_id", "owner", "priority", "due_at", "capture_id",
    "capture_batch_id", "packet_id", "conversation_id", "mission_id",
    "created_at", "updated_at")


def _placement_to_dict(r) -> dict:
    d = dict(r)
    d["is_primary"] = bool(d["is_primary"])
    d["local_fields"] = json.loads(d["local_fields"]) if d.get("local_fields") else {}
    return d


def _edge_to_dict(r) -> dict:
    d = dict(r)
    d["blocking"] = bool(d["blocking"])
    d["evidence_refs"] = json.loads(d["evidence_refs"]) if d.get("evidence_refs") else []
    return d


@app.post("/work-item")
def upsert_work_item(body: dict):
    vals = [body.get(col) for col in _WORK_ITEM_COLS]
    with closing(_db()) as c:
        c.execute(f"INSERT OR REPLACE INTO work_items ({', '.join(_WORK_ITEM_COLS)}) "
                  f"VALUES ({', '.join('?' * len(_WORK_ITEM_COLS))})", vals)
        c.commit()
        row = c.execute("SELECT * FROM work_items WHERE work_item_id=?",
                        (body["work_item_id"],)).fetchone()
    return dict(row)


@app.get("/work-items")
def list_work_items_ledger():
    with closing(_db()) as c:
        rows = c.execute("SELECT * FROM work_items ORDER BY rowid").fetchall()
    return [dict(r) for r in rows]


@app.get("/work-item/{work_item_id}")
def get_work_item_ledger(work_item_id: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM work_items WHERE work_item_id=?",
                        (work_item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such work item: {work_item_id}")
    return dict(row)


@app.post("/work-placement")
def upsert_placement(body: dict):
    with closing(_db()) as c:
        c.execute(
            "INSERT OR REPLACE INTO work_placements (placement_id, work_item_id, "
            "board_id, domain_id, is_primary, placement_stage, card_component, "
            "local_fields, created_at, removed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (body["placement_id"], body["work_item_id"], body["board_id"],
             body["domain_id"], int(bool(body.get("is_primary"))),
             body.get("placement_stage"), body.get("card_component", "generic_task"),
             json.dumps(body.get("local_fields") or {}), body["created_at"],
             body.get("removed_at")))
        c.commit()
        row = c.execute("SELECT * FROM work_placements WHERE placement_id=?",
                        (body["placement_id"],)).fetchone()
    return _placement_to_dict(row)


@app.get("/work-placement/{placement_id}")
def get_placement_ledger(placement_id: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM work_placements WHERE placement_id=?",
                        (placement_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such placement: {placement_id}")
    return _placement_to_dict(row)


@app.get("/work-placements")
def list_placements_ledger(work_item_id: Optional[str] = None,
                           board_id: Optional[str] = None, active_only: int = 1):
    q, params, conds = "SELECT * FROM work_placements", [], []
    if work_item_id is not None:
        conds.append("work_item_id=?"); params.append(work_item_id)
    if board_id is not None:
        conds.append("board_id=?"); params.append(board_id)
    if active_only:
        conds.append("removed_at IS NULL")
    if conds:
        q += " WHERE " + " AND ".join(conds)
    with closing(_db()) as c:
        rows = c.execute(q, params).fetchall()
    return [_placement_to_dict(r) for r in rows]


@app.post("/work-edge")
def upsert_edge(body: dict):
    with closing(_db()) as c:
        c.execute(
            "INSERT OR REPLACE INTO work_edges (edge_id, from_work_item_id, "
            "to_work_item_id, relation, blocking, reason, evidence_refs, created_by, "
            "created_at, removed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (body["edge_id"], body["from_work_item_id"], body["to_work_item_id"],
             body["relation"], int(bool(body.get("blocking"))), body.get("reason"),
             json.dumps(body.get("evidence_refs") or []), body.get("created_by"),
             body["created_at"], body.get("removed_at")))
        c.commit()
        row = c.execute("SELECT * FROM work_edges WHERE edge_id=?",
                        (body["edge_id"],)).fetchone()
    return _edge_to_dict(row)


@app.get("/work-edge/{edge_id}")
def get_edge_ledger(edge_id: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM work_edges WHERE edge_id=?", (edge_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such edge: {edge_id}")
    return _edge_to_dict(row)


@app.get("/work-edges")
def list_edges_ledger(active_only: int = 1):
    q = "SELECT * FROM work_edges"
    if active_only:
        q += " WHERE removed_at IS NULL"
    with closing(_db()) as c:
        rows = c.execute(q).fetchall()
    return [_edge_to_dict(r) for r in rows]


@app.post("/work-item/{work_item_id}/event")
def add_work_event(work_item_id: str, body: dict):
    with closing(_db()) as c:
        c.execute("INSERT INTO work_events (work_item_id, ts, kind, payload) "
                  "VALUES (?,?,?,?)",
                  (work_item_id, body["ts"], body["kind"],
                   json.dumps(body.get("payload") or {})))
        c.commit()
    return {"ok": True}


@app.get("/work-item/{work_item_id}/events")
def get_work_events(work_item_id: str):
    with closing(_db()) as c:
        rows = c.execute("SELECT * FROM work_events WHERE work_item_id=? "
                         "ORDER BY event_seq", (work_item_id,)).fetchall()
    return [{"event_seq": r["event_seq"], "work_item_id": r["work_item_id"],
             "ts": r["ts"], "kind": r["kind"],
             "payload": json.loads(r["payload"]) if r["payload"] else {}} for r in rows]


# ── Readiness Packet durability (packet.v1) ───────────────────────────────────
# Durable sibling of the in-memory packet store. `readiness_packets.reviews_json`
# holds the CURRENT reviews (authoritative for reconstruction); `packet_reviews`
# is the append-only per-revision audit; `packet_work_links` is authoritative for
# a committed packet's work items. A committed packet (committed_at set) is frozen:
# revision and review writes are rejected at the DB layer, not only in the service.
def _packet_work_links(c, packet_id: str) -> list:
    return [r["work_item_id"] for r in c.execute(
        "SELECT work_item_id FROM packet_work_links WHERE packet_id=? ORDER BY rowid",
        (packet_id,)).fetchall()]


def _packet_to_dict(r, work_item_ids: list) -> dict:
    return {
        "packet_id": r["packet_id"], "title": r["title"], "status": r["status"],
        "revision": r["current_revision"],
        "capture_id": r["capture_id"], "conversation_id": r["conversation_id"],
        "work_item_ids": work_item_ids,
        "plan": json.loads(r["plan_json"]),
        "plan_summary": json.loads(r["plan_summary_json"]),
        "research": r["research"] or "",
        "runbook": json.loads(r["runbook_json"]) if r["runbook_json"] else [],
        "acceptance_criteria":
            json.loads(r["acceptance_json"]) if r["acceptance_json"] else [],
        "reviews": json.loads(r["reviews_json"]) if r["reviews_json"] else [],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "committed_at": r["committed_at"],
    }


@app.post("/readiness-packet")
def upsert_packet(body: dict):
    with closing(_db()) as c:
        frozen = c.execute(
            "SELECT committed_at FROM readiness_packets WHERE packet_id=?",
            (body["packet_id"],)).fetchone()
        if frozen is not None and frozen["committed_at"] is not None:
            # durable second wall: a committed packet's row is frozen (finalize
            # goes through /commit, not this upsert)
            raise HTTPException(409, f"packet {body['packet_id']} is committed; frozen")
        c.execute(
            "INSERT OR REPLACE INTO readiness_packets (packet_id, title, status, "
            "capture_id, conversation_id, research, plan_json, plan_summary_json, "
            "runbook_json, acceptance_json, reviews_json, current_revision, "
            "created_at, updated_at, committed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (body["packet_id"], body["title"], body.get("status", "draft"),
             body.get("capture_id"), body.get("conversation_id"),
             body.get("research", ""),
             json.dumps(body["plan"]), json.dumps(body["plan_summary"]),
             json.dumps(body.get("runbook") or []),
             json.dumps(body.get("acceptance_criteria") or []),
             json.dumps(body.get("reviews") or []),
             int(body.get("revision", 1)),
             body["created_at"], body["updated_at"], body.get("committed_at")))
        c.commit()
        row = c.execute("SELECT * FROM readiness_packets WHERE packet_id=?",
                        (body["packet_id"],)).fetchone()
        links = _packet_work_links(c, body["packet_id"])
    return _packet_to_dict(row, links)


@app.get("/readiness-packets")
def list_packets_ledger(status: Optional[str] = None):
    q = "SELECT * FROM readiness_packets"
    params: list = []
    if status is not None:
        q += " WHERE status=?"; params.append(status)
    q += " ORDER BY rowid"
    with closing(_db()) as c:
        rows = c.execute(q, params).fetchall()
        return [_packet_to_dict(r, _packet_work_links(c, r["packet_id"]))
                for r in rows]


@app.get("/readiness-packet/{packet_id}")
def get_packet_ledger(packet_id: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM readiness_packets WHERE packet_id=?",
                        (packet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no such packet: {packet_id}")
        links = _packet_work_links(c, packet_id)
    return _packet_to_dict(row, links)


@app.post("/readiness-packet/{packet_id}/revision")
def append_packet_revision(packet_id: str, body: dict):
    with closing(_db()) as c:
        row = c.execute("SELECT committed_at FROM readiness_packets WHERE packet_id=?",
                        (packet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no such packet: {packet_id}")
        if row["committed_at"] is not None:
            raise HTTPException(409, f"packet {packet_id} is committed; frozen")
        exists = c.execute(
            "SELECT 1 FROM packet_revisions WHERE packet_id=? AND revision=?",
            (packet_id, int(body["revision"]))).fetchone()
        if exists:
            raise HTTPException(
                409, f"packet {packet_id} revision {body['revision']} already exists")
        c.execute(
            "INSERT INTO packet_revisions (packet_id, revision, content_digest, "
            "snapshot_json, created_at) VALUES (?,?,?,?,?)",
            (packet_id, int(body["revision"]), body["content_digest"],
             body["snapshot_json"], body["created_at"]))
        c.commit()
    return {"ok": True}


@app.get("/readiness-packet/{packet_id}/revisions")
def list_packet_revisions(packet_id: str):
    with closing(_db()) as c:
        rows = c.execute(
            "SELECT packet_id, revision, content_digest, created_at "
            "FROM packet_revisions WHERE packet_id=? ORDER BY revision",
            (packet_id,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/readiness-packet/{packet_id}/review")
def record_packet_review(packet_id: str, body: dict):
    with closing(_db()) as c:
        row = c.execute("SELECT committed_at FROM readiness_packets WHERE packet_id=?",
                        (packet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no such packet: {packet_id}")
        if row["committed_at"] is not None:      # durable frozen-after-commit wall
            raise HTTPException(409, f"packet {packet_id} is committed; frozen")
        c.execute(
            "INSERT OR REPLACE INTO packet_reviews (packet_id, revision, role, "
            "status, summary, findings_json, session_id, reviewed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (packet_id, int(body["revision"]), body["role"], body["status"],
             body.get("summary", ""), json.dumps(body.get("findings") or []),
             body.get("session_id"), body["reviewed_at"]))
        c.commit()
    return {"ok": True}


@app.post("/readiness-packet/{packet_id}/work-links")
def add_packet_work_links(packet_id: str, body: dict):
    with closing(_db()) as c:
        for wid in body.get("work_item_ids") or []:
            c.execute("INSERT OR IGNORE INTO packet_work_links (packet_id, "
                      "work_item_id) VALUES (?,?)", (packet_id, wid))
        c.commit()
        links = _packet_work_links(c, packet_id)
    return {"work_item_ids": links}


@app.get("/readiness-packet/{packet_id}/work-links")
def get_packet_work_links(packet_id: str):
    with closing(_db()) as c:
        return {"work_item_ids": _packet_work_links(c, packet_id)}


@app.post("/readiness-packet/{packet_id}/commit")
def commit_packet_ledger(packet_id: str, body: dict):
    """Atomically finalize a packet: set committed_at + status and write the
    work-item links in ONE transaction (no committed-but-unlinked window).
    Rejects a double commit (409) at the DB layer."""
    with closing(_db()) as c:
        row = c.execute("SELECT committed_at FROM readiness_packets WHERE packet_id=?",
                        (packet_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no such packet: {packet_id}")
        if row["committed_at"] is not None:
            raise HTTPException(409, f"packet {packet_id} is already committed")
        c.execute(
            "UPDATE readiness_packets SET status=?, committed_at=?, updated_at=? "
            "WHERE packet_id=?",
            (body.get("status", "committed"), body["committed_at"],
             body["updated_at"], packet_id))
        for wid in body.get("work_item_ids") or []:
            c.execute("INSERT OR IGNORE INTO packet_work_links (packet_id, "
                      "work_item_id) VALUES (?,?)", (packet_id, wid))
        c.commit()                                 # single txn = atomic finalize
        row2 = c.execute("SELECT * FROM readiness_packets WHERE packet_id=?",
                         (packet_id,)).fetchone()
        links = _packet_work_links(c, packet_id)
    return _packet_to_dict(row2, links)


# ── router-correction telemetry (routing.telemetry.v1) ────────────────────────
_CORRECTION_COLS = (
    "correction_id", "at", "title", "ref", "suggested_board_id",
    "chosen_board_id", "accepted", "matched_keywords", "conversation_id",
    "capture_id", "source")


def _correction_to_dict(r) -> dict:
    d = dict(r)
    d["accepted"] = bool(d["accepted"])
    d["matched_keywords"] = (json.loads(d["matched_keywords"])
                             if d.get("matched_keywords") else [])
    return d


@app.post("/routing-correction")
def upsert_routing_correction(body: dict):
    vals = [
        body["correction_id"], body["at"], body["title"], body.get("ref"),
        body.get("suggested_board_id"), body.get("chosen_board_id"),
        int(bool(body.get("accepted"))),
        json.dumps(body.get("matched_keywords") or []),
        body.get("conversation_id"), body.get("capture_id"),
        body.get("source", "chat")]
    with closing(_db()) as c:
        c.execute(f"INSERT OR REPLACE INTO routing_corrections "
                  f"({', '.join(_CORRECTION_COLS)}) "
                  f"VALUES ({', '.join('?' * len(_CORRECTION_COLS))})", vals)
        c.commit()
        row = c.execute("SELECT * FROM routing_corrections WHERE correction_id=?",
                        (body["correction_id"],)).fetchone()
    return _correction_to_dict(row)


@app.get("/routing-correction/{correction_id}")
def get_routing_correction(correction_id: str):
    with closing(_db()) as c:
        row = c.execute("SELECT * FROM routing_corrections WHERE correction_id=?",
                        (correction_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no such routing correction: {correction_id}")
    return _correction_to_dict(row)


@app.get("/routing-corrections")
def list_routing_corrections(since: Optional[str] = None,
                             board: Optional[str] = None,
                             limit: Optional[int] = None):
    q, params, conds = "SELECT * FROM routing_corrections", [], []
    if since is not None:
        conds.append("at>=?"); params.append(since)
    if board is not None:
        conds.append("chosen_board_id=?"); params.append(board)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY at, rowid"
    if limit is not None:
        q += " LIMIT ?"; params.append(limit)
    with closing(_db()) as c:
        rows = c.execute(q, params).fetchall()
    return [_correction_to_dict(r) for r in rows]


@app.post("/model-usage/sample")
def ingest_usage_sample(body: dict):
    _insert_or_ignore("model_usage_samples", _USAGE_SAMPLE_COLS, body)
    return _fetch_one("model_usage_samples", "source_hash", body["source_hash"])


@app.get("/model-usage/samples")
def list_usage_samples(runtime_id: str, after: Optional[str] = None):
    q = "SELECT * FROM model_usage_samples WHERE runtime_id=?"
    args: list = [runtime_id]
    if after:
        q += " AND observed_at > ?"
        args.append(after)
    q += " ORDER BY observed_at LIMIT 5000"
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(q, tuple(args)).fetchall()]


@app.post("/model-usage/limit")
def ingest_limit_snapshot(body: dict):
    _insert_or_ignore("model_limit_snapshots", _LIMIT_COLS, body)
    return _fetch_one("model_limit_snapshots", "source_hash", body["source_hash"])


@app.get("/model-usage/limits")
def list_limit_snapshots(runtime_id: str):
    """ALL snapshots for a runtime — the client applies source-priority."""
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM model_limit_snapshots WHERE runtime_id=? LIMIT 5000",
            (runtime_id,)).fetchall()]


@app.post("/model-usage/availability")
def ingest_availability_event(body: dict):
    _insert_or_ignore("model_availability_events", _AVAIL_COLS, body)
    return _fetch_one("model_availability_events", "source_hash", body["source_hash"])


@app.get("/model-usage/availability")
def list_availability_events(runtime_id: str):
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM model_availability_events WHERE runtime_id=? LIMIT 5000",
            (runtime_id,)).fetchall()]


@app.post("/model-usage/alert")
def record_usage_alert(body: dict):
    """Deduplicated by UNIQUE dedup_key: `recorded` is False when the alert
    already existed (nothing re-fired)."""
    with closing(_db()) as c:
        existed = c.execute("SELECT 1 FROM model_usage_alerts WHERE dedup_key=?",
                            (body["dedup_key"],)).fetchone()
    _insert_or_ignore("model_usage_alerts", _ALERT_COLS, body)
    return {"recorded": existed is None,
            "alert": _fetch_one("model_usage_alerts", "dedup_key", body["dedup_key"])}


@app.get("/model-usage/alerts")
def list_usage_alerts(runtime_id: Optional[str] = None):
    q = "SELECT * FROM model_usage_alerts"
    args: tuple = ()
    if runtime_id:
        q += " WHERE runtime_id=?"
        args = (runtime_id,)
    q += " ORDER BY created_at LIMIT 2000"
    with closing(_db()) as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


@app.post("/model-usage/routing-decision")
def record_routing_decision(body: dict):
    _insert_or_ignore("model_routing_decisions", _ROUTING_COLS, body)
    return _fetch_one("model_routing_decisions", "decision_id", body["decision_id"])


@app.get("/model-usage/runtimes")
def list_usage_runtimes():
    with closing(_db()) as c:
        rows = c.execute(
            "SELECT runtime_id FROM model_usage_samples "
            "UNION SELECT runtime_id FROM model_limit_snapshots "
            "UNION SELECT runtime_id FROM model_availability_events").fetchall()
    return sorted({r["runtime_id"] for r in rows})


@app.get("/model-usage/collection-state/{collector_id}")
def get_collection_state(collector_id: str):
    """Durable collector checkpoint. 404 (not an error row) when a collector
    has never run — the client treats that as "start fresh"."""
    row = _fetch_one("model_usage_collection_state", "collector_id", collector_id)
    if not row:
        raise HTTPException(404, "collector state not found")
    return row


@app.post("/model-usage/collection-state")
def set_collection_state(body: dict):
    """Upsert a collector checkpoint (INSERT OR REPLACE — a collector writes
    its full state each poll)."""
    values = [body.get(c) for c in _COLLECTION_STATE_COLS]
    placeholders = ", ".join("?" for _ in _COLLECTION_STATE_COLS)
    with closing(_db()) as c:
        c.execute(
            f"INSERT OR REPLACE INTO model_usage_collection_state "
            f"({', '.join(_COLLECTION_STATE_COLS)}) VALUES ({placeholders})", values)
        c.commit()
    return _fetch_one("model_usage_collection_state", "collector_id",
                      body["collector_id"])


@app.post("/model-usage/prune")
def prune_usage_samples(body: dict):
    """Retention: delete detailed samples observed strictly before `before`.
    Never touches routing decisions or alerts (the evidence behind a decision
    is kept)."""
    with closing(_db()) as c:
        cur = c.execute("DELETE FROM model_usage_samples WHERE observed_at < ?",
                        (body["before"],))
        c.commit()
        removed = cur.rowcount
    return {"removed": removed}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)

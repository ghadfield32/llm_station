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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)

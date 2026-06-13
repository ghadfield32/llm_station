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


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(_db()) as c:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)

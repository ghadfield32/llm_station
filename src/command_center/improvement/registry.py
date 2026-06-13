"""
Experiment registry — append-oriented access to the experiment tables in ledger.db.

This is the ONE place an experiment's status changes, and it changes only through a
validated lifecycle transition (lifecycle.validate_transition). That is what makes
"no component may promote itself" and "a model verdict cannot override a deterministic
failure" real at the data layer, not just in the UI: set_status(...) for Canary or
Promoted with an AGENT actor raises before any row is written.

Raw results are preserved: runs (including FAILED/EXCLUDED) and artifacts are
insert-only; the registered definition is stored immutably; the baseline locks once
the first baseline run is recorded.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import EventRecord, ExperimentEventType
from .ledger_schema import migrate
from .lifecycle import (
    Actor,
    ExperimentStatus,
    TransitionConditions,
    validate_transition,
)
from .schema import ExperimentDefinition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(obj: Any) -> str:
    """Stable sha256 of a JSON-serializable object (sorted keys)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def file_sha256(path: str | Path) -> tuple[str, int]:
    """(sha256 hex, byte length) of a file's contents."""
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def default_db_path() -> str:
    """The Ledger DB. Honors LEDGER_DB (the same env the Ledger service uses), else
    a repo-local data/ledger.db. One database — the experiment tables live beside the
    mission tables."""
    env = os.environ.get("LEDGER_DB")
    if env:
        return env
    return str(Path("data") / "ledger.db")


# Lifecycle states that carry a clean, correctly-typed event when entered.
_STATUS_EVENT: dict[ExperimentStatus, ExperimentEventType] = {
    ExperimentStatus.AWAITING_HUMAN_PROMOTION: ExperimentEventType.HUMAN_PROMOTION_REQUESTED,
    ExperimentStatus.CANARY: ExperimentEventType.CANARY_STARTED,
    ExperimentStatus.PROMOTED: ExperimentEventType.PROMOTED,
    ExperimentStatus.ROLLED_BACK: ExperimentEventType.ROLLED_BACK,
    ExperimentStatus.REJECTED: ExperimentEventType.EXPERIMENT_REJECTED,
    ExperimentStatus.DEFERRED: ExperimentEventType.EXPERIMENT_DEFERRED,
}


class RegistryError(RuntimeError):
    pass


class ExperimentRegistry:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or default_db_path()
        parent = Path(self.db_path).parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            migrate(c)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- registration -------------------------------------------------------

    def register(self, definition: ExperimentDefinition, mission_id: str | None = None) -> dict:
        """Insert a new experiment. The definition is stored immutably as JSON.
        Raises if the experiment_id already exists (no silent overwrite)."""
        eid = definition.experiment_id
        defn = definition.model_dump(mode="json")
        dh = canonical_hash(defn)
        with closing(self._conn()) as c:
            if c.execute("SELECT 1 FROM experiments WHERE experiment_id=?", (eid,)).fetchone():
                raise RegistryError(f"experiment {eid!r} already registered")
            c.execute(
                "INSERT INTO experiments (experiment_id, mission_id, title, owner, "
                "target_type, target_ref, risk_tier, status, baseline_version, "
                "candidate_version, definition_json, definition_hash, created_at, "
                "updated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, mission_id, definition.title, definition.owner,
                 definition.target_type.value, definition.target_ref,
                 definition.risk_tier.value, definition.status.value,
                 definition.baseline, definition.candidate,
                 json.dumps(defn, sort_keys=True), dh, _now(), _now(),
                 definition.expires_at),
            )
            c.commit()
        self.append_event(EventRecord(
            kind=ExperimentEventType.EXPERIMENT_REGISTERED.value,
            experiment_id=eid, mission_id=mission_id, actor_role="registry",
            action=f"registered {definition.target_type.value} experiment {eid}",
            detail={"definition_hash": dh, "status": definition.status.value},
        ))
        return self.get(eid)  # type: ignore[return-value]

    def get(self, experiment_id: str) -> dict | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT * FROM experiments WHERE experiment_id=?",
                            (experiment_id,)).fetchone()
        return dict(row) if row else None

    def definition(self, experiment_id: str) -> dict | None:
        """The immutably-stored registered definition (parsed)."""
        row = self.get(experiment_id)
        return json.loads(row["definition_json"]) if row and row["definition_json"] else None

    def list_experiments(self, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM experiments"
        args: tuple = ()
        if status:
            q += " WHERE status=?"
            args = (status,)
        q += " ORDER BY created_at DESC"
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    # ---- events (append-only) ----------------------------------------------

    def append_event(self, record: EventRecord) -> int:
        with closing(self._conn()) as c:
            cur = c.execute(
                "INSERT INTO experiment_events (experiment_id, ts, kind, actor_role, "
                "actor_model, action, payload) VALUES (?,?,?,?,?,?,?)",
                (record.experiment_id, _now(), record.kind, record.actor_role,
                 record.actor_model, record.action,
                 json.dumps(record.model_dump(mode="json"), sort_keys=True)),
            )
            c.commit()
            return int(cur.lastrowid or 0)

    def events(self, experiment_id: str) -> list[dict]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT id, ts, kind, actor_role, actor_model, action, payload "
                "FROM experiment_events WHERE experiment_id=? ORDER BY id",
                (experiment_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out

    # ---- runs (insert-only; failed/excluded retained) ----------------------

    def record_run(self, *, run_id: str, experiment_id: str, role: str,
                   status: str, iteration: int = 0, cache_state: str = "cold",
                   commit_ref: str = "", sample_count: int = 0,
                   metrics: dict | None = None, budget: dict | None = None,
                   excluded_reason: str = "") -> None:
        """Store one run. role in {baseline, candidate, verifier}. FAILED and
        EXCLUDED runs are recorded too — never silently discarded. Recording the
        first baseline run locks the baseline."""
        if role == "baseline":
            self._lock_baseline(experiment_id, canonical_hash(
                {"baseline": (self.get(experiment_id) or {}).get("baseline_version"),
                 "commit": commit_ref}))
        with closing(self._conn()) as c:
            c.execute(
                "INSERT INTO experiment_runs (run_id, experiment_id, role, iteration, "
                "started_at, finished_at, status, cache_state, commit_ref, sample_count, "
                "metrics, budget, excluded_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, experiment_id, role, iteration, _now(), _now(), status,
                 cache_state, commit_ref, sample_count,
                 json.dumps(metrics or {}, sort_keys=True),
                 json.dumps(budget or {}, sort_keys=True), excluded_reason),
            )
            c.commit()

    def runs(self, experiment_id: str, role: str | None = None) -> list[dict]:
        q = "SELECT * FROM experiment_runs WHERE experiment_id=?"
        args: tuple = (experiment_id,)
        if role:
            q += " AND role=?"
            args = (experiment_id, role)
        q += " ORDER BY started_at, run_id"
        with closing(self._conn()) as c:
            rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d["metrics"]) if d["metrics"] else {}
            d["budget"] = json.loads(d["budget"]) if d["budget"] else {}
            out.append(d)
        return out

    def _lock_baseline(self, experiment_id: str, baseline_hash: str) -> None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT baseline_locked, baseline_hash FROM experiments "
                            "WHERE experiment_id=?", (experiment_id,)).fetchone()
            if row is None:
                raise RegistryError(f"unknown experiment {experiment_id!r}")
            if row["baseline_locked"]:
                # immutable once set — re-locking with a different basis is an error
                if row["baseline_hash"] != baseline_hash:
                    raise RegistryError(
                        f"baseline for {experiment_id!r} is locked and immutable; "
                        "a candidate run cannot change the baseline definition")
                return
            c.execute("UPDATE experiments SET baseline_locked=1, baseline_hash=?, "
                      "updated_at=? WHERE experiment_id=?",
                      (baseline_hash, _now(), experiment_id))
            c.commit()

    def baseline_locked(self, experiment_id: str) -> bool:
        row = self.get(experiment_id)
        return bool(row and row["baseline_locked"])

    # ---- artifacts (content-addressed, insert-only) ------------------------

    def add_artifact(self, *, experiment_id: str, run_id: str, name: str,
                     kind: str, path: str, sha256: str | None = None,
                     bytes_len: int | None = None) -> None:
        if sha256 is None or bytes_len is None:
            sha256, bytes_len = file_sha256(path)
        with closing(self._conn()) as c:
            c.execute(
                "INSERT INTO experiment_artifacts (experiment_id, run_id, name, kind, "
                "path, sha256, bytes, ts) VALUES (?,?,?,?,?,?,?,?)",
                (experiment_id, run_id, name, kind, str(path), sha256, bytes_len, _now()),
            )
            c.commit()

    def artifacts(self, experiment_id: str) -> list[dict]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM experiment_artifacts WHERE experiment_id=? ORDER BY id",
                (experiment_id,)).fetchall()]

    # ---- status transitions (the enforcement point) ------------------------

    def set_status(self, experiment_id: str, new_status: ExperimentStatus, *,
                   actor: Actor, conditions: TransitionConditions | None = None,
                   actor_model: str | None = None, note: str = "") -> dict:
        """Change status ONLY through a validated lifecycle transition. Raises
        (and writes nothing) if the transition is illegal, human-only, or the gate
        is unmet. Appends a typed event for lifecycle-significant states."""
        row = self.get(experiment_id)
        if row is None:
            raise RegistryError(f"unknown experiment {experiment_id!r}")
        current = ExperimentStatus(row["status"])
        validate_transition(current, new_status, actor=actor, conditions=conditions)
        with closing(self._conn()) as c:
            c.execute("UPDATE experiments SET status=?, updated_at=? WHERE experiment_id=?",
                      (new_status.value, _now(), experiment_id))
            c.commit()
        ev = _STATUS_EVENT.get(new_status)
        if ev is not None:
            self.append_event(EventRecord(
                kind=ev.value, experiment_id=experiment_id,
                actor_role=actor.value, actor_model=actor_model,
                action=note or f"{current.value} -> {new_status.value}",
                detail={"from": current.value, "to": new_status.value},
            ))
        return self.get(experiment_id)  # type: ignore[return-value]

    def set_verifier_verdict(self, experiment_id: str, verdict: str, *,
                             actor_model: str | None = None, detail: dict | None = None) -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE experiments SET verifier_verdict=?, updated_at=? "
                      "WHERE experiment_id=?", (verdict, _now(), experiment_id))
            c.commit()
        kind = (ExperimentEventType.VERIFICATION_REPRODUCED if verdict == "PASS"
                else ExperimentEventType.VERIFICATION_FAILED)
        self.append_event(EventRecord(
            kind=kind.value, experiment_id=experiment_id, actor_role="verifier",
            actor_model=actor_model, action=f"verifier verdict: {verdict}",
            detail=detail or {}))

    def set_human_decision(self, experiment_id: str, decision: str, note: str = "") -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE experiments SET human_decision=?, updated_at=? "
                      "WHERE experiment_id=?", (decision, _now(), experiment_id))
            c.commit()

    def set_canary_status(self, experiment_id: str, status: str) -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE experiments SET canary_status=?, updated_at=? "
                      "WHERE experiment_id=?", (status, _now(), experiment_id))
            c.commit()
        kind = (ExperimentEventType.CANARY_PASSED if status == "passed"
                else ExperimentEventType.CANARY_FAILED if status == "failed"
                else None)
        if kind:
            self.append_event(EventRecord(
                kind=kind.value, experiment_id=experiment_id, actor_role="canary",
                action=f"canary {status}"))

    def set_rollback_status(self, experiment_id: str, status: str) -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE experiments SET rollback_status=?, updated_at=? "
                      "WHERE experiment_id=?", (status, _now(), experiment_id))
            c.commit()

    def promotion_conditions(self, experiment_id: str, *,
                             human_approval: bool = False) -> TransitionConditions:
        """Derive the gated-transition conditions from auditable Ledger state — never
        from a model's say-so. deterministic_passed requires a completed candidate run
        and no deterministic-gate failure; the verification fields come from the
        verifier's recorded verdict + independence flag."""
        row = self.get(experiment_id)
        if row is None:
            raise RegistryError(f"unknown experiment {experiment_id!r}")
        evs = self.events(experiment_id)
        kinds = [e["kind"] for e in evs]
        det_passed = ("CANDIDATE_COMPLETED" in kinds
                      and "DETERMINISTIC_GATE_FAILED" not in kinds)
        distinct = False
        safety_inconclusive = False
        for e in evs:
            if e["kind"] in ("VERIFICATION_REPRODUCED", "VERIFICATION_FAILED"):
                d = e["payload"].get("detail", {}) or {}
                distinct = distinct or bool(d.get("independent"))
                safety_inconclusive = safety_inconclusive or bool(d.get("safety_inconclusive"))
        return TransitionConditions(
            deterministic_passed=det_passed,
            verification_present=row["verifier_verdict"] is not None,
            verification_verdict=row["verifier_verdict"],
            safety_inconclusive=safety_inconclusive,
            independent_verifier_distinct=distinct,
            human_approval=human_approval,
            rollback_demonstrated=(row["rollback_status"] == "demonstrated"),
        )

    # ---- relationships + search (negative-result memory) -------------------

    def link(self, from_id: str, to_id: str, relation: str) -> None:
        with closing(self._conn()) as c:
            c.execute("INSERT INTO experiment_links (from_id, to_id, relation, ts) "
                      "VALUES (?,?,?,?)", (from_id, to_id, relation, _now()))
            c.commit()

    def links(self, experiment_id: str) -> list[dict]:
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM experiment_links WHERE from_id=? OR to_id=? ORDER BY id",
                (experiment_id, experiment_id)).fetchall()]

    def search(self, query: str) -> list[dict]:
        """Search experiments (incl. terminal/negative results) by id/title/target/
        status/decision. Negative results stay findable — that's the whole point."""
        like = f"%{query.lower()}%"
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT * FROM experiments WHERE lower(experiment_id) LIKE ? "
                "OR lower(title) LIKE ? OR lower(target_ref) LIKE ? "
                "OR lower(status) LIKE ? OR lower(coalesce(human_decision,'')) LIKE ? "
                "ORDER BY updated_at DESC", (like, like, like, like, like)).fetchall()
        return [dict(r) for r in rows]

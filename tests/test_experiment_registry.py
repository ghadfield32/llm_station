"""Experiment-registry tests (Ledger extension).

Cover registration, append-only events, raw-evidence retention (failed runs kept),
baseline immutability, artifact hashes, and the transition-enforcement wall at the
data layer (an agent cannot set Canary/Promoted).
"""
from __future__ import annotations

import sqlite3

import pytest
import yaml
from pathlib import Path

from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry, RegistryError, file_sha256
from command_center.improvement.events import EventRecord, ExperimentEventType
from command_center.improvement.lifecycle import (
    Actor, ExperimentStatus as S, TransitionConditions, HumanApprovalRequired, IllegalTransition,
)
from command_center.improvement.ledger_schema import migrate, applied_versions


REPO_ROOT = Path(__file__).resolve().parents[1]


def _defn() -> ExperimentDefinition:
    data = yaml.safe_load((REPO_ROOT / "configs/improvement.yaml").read_text(encoding="utf-8"))
    return ExperimentDefinition.model_validate(data["experiments"][0])


@pytest.fixture
def reg(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))


def _good_conditions() -> TransitionConditions:
    return TransitionConditions(
        deterministic_passed=True, verification_present=True, verification_verdict="PASS",
        independent_verifier_distinct=True, human_approval=True, rollback_demonstrated=True)


# ---- registration + immutable definition -----------------------------------

def test_register_and_get(reg):
    d = _defn()
    reg.register(d, mission_id="T-abc123")
    row = reg.get(d.experiment_id)
    assert row["status"] == "Proposed"
    assert row["mission_id"] == "T-abc123"
    assert row["definition_hash"]
    # the registered definition is stored verbatim and immutable
    stored = reg.definition(d.experiment_id)
    assert stored["experiment_id"] == d.experiment_id


def test_double_register_rejected(reg):
    d = _defn()
    reg.register(d)
    with pytest.raises(RegistryError):
        reg.register(d)


def test_registration_emits_event(reg):
    d = _defn()
    reg.register(d)
    kinds = [e["kind"] for e in reg.events(d.experiment_id)]
    assert ExperimentEventType.EXPERIMENT_REGISTERED.value in kinds


# ---- append-only events -----------------------------------------------------

def test_event_unknown_kind_rejected():
    with pytest.raises(ValueError):
        EventRecord(kind="NOT_A_REAL_EVENT", experiment_id="x")


def test_events_are_ordered_and_retained(reg):
    d = _defn()
    reg.register(d)
    for k in (ExperimentEventType.BASELINE_STARTED, ExperimentEventType.BASELINE_COMPLETED):
        reg.append_event(EventRecord(kind=k.value, experiment_id=d.experiment_id, action="x"))
    kinds = [e["kind"] for e in reg.events(d.experiment_id)]
    assert kinds.count(ExperimentEventType.BASELINE_STARTED.value) == 1
    assert kinds[-1] == ExperimentEventType.BASELINE_COMPLETED.value


# ---- raw-evidence retention: failed runs are kept --------------------------

def test_failed_runs_are_retained(reg):
    d = _defn()
    reg.register(d)
    reg.record_run(run_id="r1", experiment_id=d.experiment_id, role="candidate",
                   status="completed", sample_count=10, metrics={"recall_at_5": 0.8})
    reg.record_run(run_id="r2", experiment_id=d.experiment_id, role="candidate",
                   status="failed", excluded_reason="timeout")
    reg.record_run(run_id="r3", experiment_id=d.experiment_id, role="candidate",
                   status="excluded", excluded_reason="cache not equivalent")
    runs = reg.runs(d.experiment_id, role="candidate")
    statuses = {r["status"] for r in runs}
    assert statuses == {"completed", "failed", "excluded"}
    # exact reasons preserved, not discarded
    assert any(r["excluded_reason"] == "timeout" for r in runs)


# ---- baseline immutability --------------------------------------------------

def test_baseline_locks_on_first_baseline_run(reg):
    d = _defn()
    reg.register(d)
    assert not reg.baseline_locked(d.experiment_id)
    reg.record_run(run_id="b1", experiment_id=d.experiment_id, role="baseline",
                   status="completed", commit_ref="abc", metrics={"recall_at_5": 0.6})
    assert reg.baseline_locked(d.experiment_id)
    # re-running the same baseline (same basis) is fine
    reg.record_run(run_id="b2", experiment_id=d.experiment_id, role="baseline",
                   status="completed", commit_ref="abc", metrics={"recall_at_5": 0.6})
    # a baseline run on a DIFFERENT commit changes the basis -> rejected
    with pytest.raises(RegistryError):
        reg.record_run(run_id="b3", experiment_id=d.experiment_id, role="baseline",
                       status="completed", commit_ref="different", metrics={})


# ---- artifacts: content addressed ------------------------------------------

def test_artifact_hash_recorded(reg, tmp_path):
    d = _defn()
    reg.register(d)
    p = tmp_path / "log.txt"
    p.write_text("hello evidence", encoding="utf-8")
    reg.add_artifact(experiment_id=d.experiment_id, run_id="r1", name="log",
                     kind="stdout", path=str(p))
    arts = reg.artifacts(d.experiment_id)
    assert len(arts) == 1
    sha, n = file_sha256(p)
    assert arts[0]["sha256"] == sha and arts[0]["bytes"] == n


# ---- transition enforcement at the data layer ------------------------------

def test_set_status_legal(reg):
    d = _defn()
    reg.register(d)
    reg.set_status(d.experiment_id, S.BASELINE_READY, actor=Actor.AGENT)
    assert reg.get(d.experiment_id)["status"] == "Baseline Ready"


def test_set_status_illegal_raises_and_writes_nothing(reg):
    d = _defn()
    reg.register(d)
    with pytest.raises(IllegalTransition):
        reg.set_status(d.experiment_id, S.PROMOTED, actor=Actor.HUMAN, conditions=_good_conditions())
    assert reg.get(d.experiment_id)["status"] == "Proposed"  # unchanged


def test_agent_cannot_set_canary_via_registry(reg):
    d = _defn()
    reg.register(d)
    # walk to Awaiting Human Promotion legitimately
    reg.set_status(d.experiment_id, S.BASELINE_READY, actor=Actor.AGENT)
    reg.set_status(d.experiment_id, S.RUNNING, actor=Actor.AGENT)
    reg.set_status(d.experiment_id, S.AWAITING_VERIFICATION, actor=Actor.AGENT)
    reg.set_status(d.experiment_id, S.VERIFIED, actor=Actor.AGENT)
    reg.set_status(d.experiment_id, S.AWAITING_HUMAN_PROMOTION, actor=Actor.AGENT,
                   conditions=_good_conditions())
    # the wall: an agent cannot enter Canary
    with pytest.raises(HumanApprovalRequired):
        reg.set_status(d.experiment_id, S.CANARY, actor=Actor.AGENT, conditions=_good_conditions())
    # a human can
    reg.set_status(d.experiment_id, S.CANARY, actor=Actor.HUMAN, conditions=_good_conditions())
    assert reg.get(d.experiment_id)["status"] == "Canary"


def test_promotion_event_recorded(reg):
    d = _defn()
    reg.register(d)
    for s, cond in [(S.BASELINE_READY, None), (S.RUNNING, None),
                    (S.AWAITING_VERIFICATION, None), (S.VERIFIED, None),
                    (S.AWAITING_HUMAN_PROMOTION, _good_conditions())]:
        reg.set_status(d.experiment_id, s, actor=Actor.AGENT, conditions=cond)
    reg.set_status(d.experiment_id, S.PROMOTED, actor=Actor.HUMAN, conditions=_good_conditions())
    kinds = [e["kind"] for e in reg.events(d.experiment_id)]
    assert ExperimentEventType.PROMOTED.value in kinds
    assert ExperimentEventType.HUMAN_PROMOTION_REQUESTED.value in kinds


# ---- verifier verdict / decisions / negative-result search -----------------

def test_verifier_verdict_and_search(reg):
    d = _defn()
    reg.register(d)
    reg.set_verifier_verdict(d.experiment_id, "FAIL", detail={"reason": "did not reproduce"})
    assert reg.get(d.experiment_id)["verifier_verdict"] == "FAIL"
    # negative results stay findable
    hits = reg.search("retrieval")
    assert any(h["experiment_id"] == d.experiment_id for h in hits)


def test_links_supersede(reg):
    d = _defn()
    reg.register(d)
    reg.link(d.experiment_id, "EXP-followup-002", "superseded_by")
    ls = reg.links(d.experiment_id)
    assert ls and ls[0]["relation"] == "superseded_by"


# ---- migration ---------------------------------------------------------------

def test_migration_idempotent_and_versioned(tmp_path):
    db = str(tmp_path / "ledger.db")
    conn = sqlite3.connect(db)
    assert migrate(conn) == "improvement.v1"
    migrate(conn)  # second run is a no-op
    assert applied_versions(conn) == ["improvement.v1"]
    conn.close()


def test_migration_preserves_existing_mission_tables(tmp_path):
    db = str(tmp_path / "ledger.db")
    conn = sqlite3.connect(db)
    # simulate a pre-existing Ledger DB with the mission table + a row
    conn.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO missions VALUES ('T-1', 'open')")
    conn.commit()
    migrate(conn)  # additive — must not disturb missions
    row = conn.execute("SELECT status FROM missions WHERE id='T-1'").fetchone()
    assert row[0] == "open"
    # and the experiment tables now exist
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"experiments", "experiment_events", "experiment_runs"} <= tables
    conn.close()

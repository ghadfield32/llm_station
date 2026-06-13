"""Controlled-proposal tests: evidence thresholds, dedup, cooldown, and the rule that
a drafted proposal lands non-approved and the generator never approves/promotes."""
from __future__ import annotations

from datetime import datetime, timedelta

from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.proposals import (
    ProposalGenerator, EvidenceSignal, EvidenceSource,
)
from command_center.improvement.schema import ExperimentDefinition
from command_center.improvement.lifecycle import Actor, ExperimentStatus


def _reg(tmp_path):
    return ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))


def _slow_retrieval(occurrences=5) -> EvidenceSignal:
    return EvidenceSignal(
        source=EvidenceSource.SLOW_RETRIEVAL, target_ref="command_center.retrieval",
        observed=4200.0, threshold=2000.0, direction="increase",
        occurrences=occurrences, min_occurrences=3, detail="median query latency 4.2s")


def test_noise_below_threshold_is_skipped(tmp_path):
    gen = ProposalGenerator(_reg(tmp_path))
    weak = _slow_retrieval(occurrences=1)        # only once -> noise
    drafts = gen.propose([weak])
    assert drafts[0].skipped and "noise" in drafts[0].skipped


def test_actionable_signal_drafts_a_valid_experiment(tmp_path):
    gen = ProposalGenerator(_reg(tmp_path))
    drafts = gen.propose([_slow_retrieval()])
    d = drafts[0]
    assert d.skipped == ""
    # the draft is a valid, contract-passing experiment, capped at L2, human-gated
    defn = d.definition
    assert isinstance(defn, ExperimentDefinition)
    assert defn.risk_tier.value == "L2_local_edits"
    assert defn.promotion.human_approval_required and not defn.promotion.automatic_promotion
    assert any(m.required for m in defn.metrics) and any(m.safety for m in defn.metrics)


def test_apply_lands_non_approved_proposed(tmp_path):
    reg = _reg(tmp_path)
    gen = ProposalGenerator(reg)
    drafts = gen.propose([_slow_retrieval()], apply=True)
    eid = drafts[0].experiment_id
    row = reg.get(eid)
    assert row is not None
    assert row["status"] == "Proposed"            # non-approved, exactly where it should land
    assert row["human_decision"] in (None, "")    # the generator invented no decision


def test_dedup_within_batch(tmp_path):
    gen = ProposalGenerator(_reg(tmp_path))
    drafts = gen.propose([_slow_retrieval(), _slow_retrieval()])
    assert any("duplicate within batch" in d.skipped for d in drafts if d.skipped)


def test_dedup_against_open_proposal(tmp_path):
    reg = _reg(tmp_path)
    gen = ProposalGenerator(reg)
    gen.propose([_slow_retrieval()], apply=True)   # opens a Proposed experiment
    again = gen.propose([_slow_retrieval()])       # same signal again
    assert again[0].skipped and "dedup" in again[0].skipped


def test_cooldown_blocks_recent_reproposal(tmp_path):
    reg = _reg(tmp_path)
    gen = ProposalGenerator(reg)
    drafts = gen.propose([_slow_retrieval()], apply=True)
    eid = drafts[0].experiment_id
    reg.set_status(eid, ExperimentStatus.REJECTED, actor=Actor.AGENT)
    created = reg.get(eid)["created_at"]
    soon = (datetime.fromisoformat(created) + timedelta(hours=1)).isoformat()
    again = gen.propose([_slow_retrieval()], now_iso=soon)
    assert again[0].skipped and "cooldown" in again[0].skipped


def test_reproposal_allowed_after_cooldown(tmp_path):
    reg = _reg(tmp_path)
    gen = ProposalGenerator(reg)
    drafts = gen.propose([_slow_retrieval()], apply=True)
    eid = drafts[0].experiment_id
    reg.set_status(eid, ExperimentStatus.REJECTED, actor=Actor.AGENT)
    created = reg.get(eid)["created_at"]
    later = (datetime.fromisoformat(created) + timedelta(hours=200)).isoformat()
    again = gen.propose([_slow_retrieval()], now_iso=later)
    assert again[0].skipped == ""                  # cooldown elapsed -> may re-propose

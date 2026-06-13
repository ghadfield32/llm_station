"""
Discovery foundations: the pillar taxonomy, the Finding model, the ICE/RICE/WSJF/VOI
ranking, and — most importantly — the observer-only charter's structural wall.

These tests pin the things that must not silently drift: every pillar resolves to a real
target type, the ranking formulas equal hand-computed values, WSJF actually rescues a
high-risk / low-effort item that ICE buries, a drafted card is always a bounded `Proposed`
L2 experiment, and the charter exposes NO way to promote / merge / deploy / set status.
"""
from __future__ import annotations

import math

import pytest

from command_center.improvement.discovery import (
    CharterViolation, Finding, ObserverCharter, Pillar, PILLAR_SOURCES,
    PILLAR_TARGETS, confidence_band, cost_of_delay, ice, rank, rice, target_for, voi, wsjf,
)
from command_center.improvement.discovery.ranking import score
from command_center.improvement.lifecycle import ExperimentStatus
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.schema import TargetType
from command_center.schemas.base import RiskTier


# --------------------------------------------------------------------------- pillars

def test_every_pillar_maps_to_targets_and_sources():
    assert len(list(Pillar)) == 9
    for p in Pillar:
        assert PILLAR_TARGETS[p], f"{p} has no target types"
        assert all(isinstance(t, TargetType) for t in PILLAR_TARGETS[p])
        assert PILLAR_SOURCES[p], f"{p} has no scan sources"
        assert target_for(p) is PILLAR_TARGETS[p][0]


def test_updated_metrics_pillar_targets_models_and_routing():
    # leaderboard/provider churn should land on model/routing/judge work
    tt = PILLAR_TARGETS[Pillar.UPDATED_METRICS]
    assert TargetType.MODEL in tt and TargetType.ROUTING in tt


# --------------------------------------------------------------------------- findings

def _finding(**kw) -> Finding:
    base = dict(pillar=Pillar.CODE_QUALITY, source="ruff", title="drop dead code",
                claim="vulture finds 40 unused symbols", evidence="vulture: 40 items >=90% conf")
    base.update(kw)
    return Finding(**base)


def test_finding_defaults_target_and_dedup_and_id_are_stable():
    f = _finding()
    assert f.suggested_target_type is target_for(Pillar.CODE_QUALITY)
    assert f.dedup_key == "code_quality:drop-dead-code"
    assert f.target_ref == "discovery/code_quality/ruff"
    # experiment_id is a pure function of the dedup_key
    assert f.experiment_id == _finding().experiment_id
    assert f.experiment_id.startswith("EXP-scan-code-")


def test_finding_validates_ranges():
    with pytest.raises(ValueError):
        _finding(confidence=1.4)
    with pytest.raises(ValueError):
        _finding(effort=0.0)
    with pytest.raises(ValueError):
        _finding(cost=-1.0)


def test_finding_to_experiment_definition_is_bounded_proposed_l2():
    f = _finding(suggested_risk=RiskTier.L2)
    d = f.to_experiment_definition()
    assert d.status is ExperimentStatus.PROPOSED
    assert d.risk_tier is RiskTier.L2
    # secret-free + no execution budget here (definition, not a run)
    assert d.requests_secrets is False
    assert d.budgets.max_input_tokens == 0 and d.budgets.max_cost_usd == 0
    # a required primary + a required, regression-capped safety metric
    req = [m for m in d.metrics if m.required]
    assert any(m.name == "primary_outcome" for m in req)
    safety = [m for m in d.metrics if m.safety]
    assert safety and safety[0].maximum_regression == 0.0
    # promotion stays human-gated, never automatic
    assert d.promotion.human_approval_required is True
    assert d.promotion.automatic_promotion is False


def test_finding_targeting_control_plane_demands_elevated_review():
    # a source slug carrying a control-plane marker must not be quietly draftable
    f = _finding(pillar=Pillar.RULES_STANDARDS, source="github branch protection",
                 title="tighten merge wall")
    assert "github" in f.target_ref
    with pytest.raises(ValueError, match="elevated_human_review"):
        f.to_experiment_definition()


# --------------------------------------------------------------------------- ranking

def test_ice_rice_wsjf_voi_match_hand_computed():
    f = _finding(impact=0.8, confidence=0.5, ease=0.5, reach=10.0, effort=2.0,
                 time_criticality=0.3, risk_reduction=0.4, voi_value=0.9, voi_prob=0.5, cost=3.0)
    assert ice(f) == pytest.approx(0.8 * 0.5 * 0.5)
    assert rice(f) == pytest.approx((10.0 * 0.8 * 0.5) / 2.0)
    assert cost_of_delay(f) == pytest.approx(0.8 + 0.3 + 0.4)
    assert wsjf(f) == pytest.approx((0.8 + 0.3 + 0.4) / 2.0)
    assert voi(f) == pytest.approx((0.9 * 0.5) / 3.0)
    assert score(f, "wsjf") == pytest.approx(wsjf(f))


def test_wsjf_rescues_high_riskreduction_low_effort_item_that_ice_buries():
    # A security fix: modest impact, low confidence/ease (ICE buries it), but huge
    # risk-reduction and tiny effort — WSJF must lift it above a flashy feature.
    cve = _finding(title="patch CVE", impact=0.4, confidence=0.4, ease=0.3,
                   time_criticality=0.8, risk_reduction=0.9, effort=0.5)
    feature = _finding(title="shiny feature", impact=0.9, confidence=0.9, ease=0.9,
                       time_criticality=0.0, risk_reduction=0.0, effort=2.0)
    assert ice(feature) > ice(cve)                      # ICE prefers the feature
    by_wsjf = [f for f, _ in rank([feature, cve], "wsjf")]
    assert by_wsjf[0] is cve                             # WSJF rescues the CVE


def test_rank_is_descending_and_deterministic():
    fs = [_finding(title=f"t{i}", impact=i / 10) for i in range(5)]
    ranked = rank(fs, "ice")
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_unknown_ranking_method_raises():
    with pytest.raises(ValueError, match="unknown ranking method"):
        score(_finding(), "bogus")


def test_confidence_band_brackets_and_tightens_with_corroboration():
    lo1, hi1 = confidence_band(_finding(confidence=0.6))
    assert lo1 < 0.6 < hi1
    # more independent sources -> a tighter band
    lo4, hi4 = confidence_band(_finding(confidence=0.6, detail={"n_sources": 4}))
    assert (hi4 - lo4) < (hi1 - lo1)
    assert (hi4 - lo4) == pytest.approx((hi1 - lo1) / math.sqrt(4))


# --------------------------------------------------------------------------- charter

def _charter(tmp_path) -> tuple[ObserverCharter, ExperimentRegistry]:
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    return ObserverCharter(reg, report_path=tmp_path / "report.md"), reg


def test_charter_capabilities_are_read_draft_report_only(tmp_path):
    charter, _ = _charter(tmp_path)
    assert set(charter.capabilities()) == {
        "read_experiments", "read_open_findings", "read_negative_results",
        "draft_backlog_card", "write_report", "capabilities"}


@pytest.mark.parametrize("forbidden", [
    "promote", "canary", "merge", "deploy", "set_status", "approve", "rollback",
    "rotate_secrets", "request_human_promotion"])
def test_charter_forbids_every_escalation(tmp_path, forbidden):
    charter, _ = _charter(tmp_path)
    with pytest.raises(CharterViolation):
        getattr(charter, forbidden)


def test_charter_drafts_only_proposed_and_is_idempotent(tmp_path):
    charter, reg = _charter(tmp_path)
    f = _finding(title="dedup me")
    row = charter.draft_backlog_card(f.to_experiment_definition())
    assert row is not None and row["status"] == ExperimentStatus.PROPOSED.value
    # re-drafting the same finding is a no-op (idempotent re-run), not a duplicate/raise
    assert charter.draft_backlog_card(f.to_experiment_definition()) is None
    assert len(reg.list_experiments()) == 1


def test_charter_refuses_a_non_proposed_definition(tmp_path):
    charter, _ = _charter(tmp_path)
    defn = _finding().to_experiment_definition()
    defn = defn.model_copy(update={"status": ExperimentStatus.PROMOTED})
    with pytest.raises(CharterViolation, match="only draft Proposed"):
        charter.draft_backlog_card(defn)


def test_charter_writes_one_report_artifact(tmp_path):
    charter, _ = _charter(tmp_path)
    out = charter.write_report("# Daily Self-Improvement Report\n\nnothing today.")
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Daily")
    assert out.endswith("report.md")


def test_charter_reads_partition_open_vs_negative(tmp_path):
    charter, reg = _charter(tmp_path)
    open_card = _finding(title="open one").to_experiment_definition()
    reg.register(open_card)
    assert any(e["experiment_id"] == open_card.experiment_id
               for e in charter.read_open_findings())
    assert charter.read_negative_results() == []

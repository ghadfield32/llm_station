"""
Self-improvement metrics: DORA, acceptance/rollback/unit-cost, negative-memory hit rate,
the SciPy-free power-law convergence fit, and BWT/FWT transfer — checked against values
computed by hand.
"""
from __future__ import annotations

import json

import pytest

from command_center.improvement.events import EventRecord
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.selfmetrics import (
    ExperimentTimeline, acceptance_by_group, bwt, compute_dora, cost_per_accepted,
    fit_convergence, fwt, negative_result_hit_rate, rollback_rate, snapshot,
    timelines_from_registry,
)

NOW = "2026-06-13T00:00:00+00:00"


def _tl(eid, group, created, promoted=None, rolled_back=None):
    return ExperimentTimeline(experiment_id=eid, group=group, created_at=created,
                              promoted_at=promoted, rolled_back_at=rolled_back)


# ---------------------------------------------------------------------- DORA

def _dora_timelines():
    return [
        _tl("a", "code_quality", "2026-06-01T00:00:00+00:00", "2026-06-03T00:00:00+00:00"),
        _tl("b", "automation", "2026-06-05T00:00:00+00:00", "2026-06-06T00:00:00+00:00",
            "2026-06-06T12:00:00+00:00"),
        _tl("c", "code_quality", "2026-03-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),  # old
        _tl("d", "automation", "2026-06-10T00:00:00+00:00"),                                 # open
    ]


def test_dora_matches_hand_computed():
    d = compute_dora(_dora_timelines(), window_days=28, now_iso=NOW)
    assert d.deploys == 2                                  # a, b (c is before window, d never)
    assert d.deployment_frequency_per_week == pytest.approx(0.5)   # 2 / (28/7)
    assert d.lead_time_hours_median == pytest.approx(36.0)         # median(48, 24)
    assert d.change_failure_rate == pytest.approx(0.5)             # 1 of 2 rolled back
    assert d.mttr_hours_median == pytest.approx(12.0)


def test_dora_no_deploys_is_honest_not_fabricated():
    d = compute_dora([_tl("x", "g", "2026-06-10T00:00:00+00:00")], window_days=7, now_iso=NOW)
    assert d.deploys == 0
    assert d.deployment_frequency_per_week == 0.0
    assert d.lead_time_hours_median is None                # not a fake 0
    assert d.mttr_hours_median is None
    assert d.change_failure_rate == 0.0


def test_dora_rejects_bad_window():
    with pytest.raises(ValueError):
        compute_dora([], window_days=0, now_iso=NOW)


# ------------------------------------------------------- acceptance / rollback / cost

def test_acceptance_by_group():
    stats = {g.group: g for g in acceptance_by_group(_dora_timelines())}
    assert stats["code_quality"].accepted == 2 and stats["code_quality"].total == 2
    assert stats["automation"].accepted == 1 and stats["automation"].total == 2
    assert stats["automation"].rate == pytest.approx(0.5)


def test_rollback_rate():
    assert rollback_rate(_dora_timelines()) == pytest.approx(1 / 3)   # 1 of 3 promoted failed


def test_cost_per_accepted_and_negative_hit_rate():
    assert cost_per_accepted(100.0, 4) == pytest.approx(25.0)
    assert cost_per_accepted(100.0, 0) is None             # nothing accepted yet
    with pytest.raises(ValueError):
        cost_per_accepted(-1.0, 1)
    assert negative_result_hit_rate(3, 10) == pytest.approx(0.3)
    assert negative_result_hit_rate(0, 0) == 0.0
    with pytest.raises(ValueError):
        negative_result_hit_rate(5, 3)                     # suppressed > total


# ---------------------------------------------------------------- power-law fit

def test_fit_convergence_recovers_known_parameters():
    a, b, c = 0.9, 0.5, 0.5
    ns = [1, 2, 4, 8, 16, 32]
    aps = [a - b * (n ** (-c)) for n in ns]
    fit = fit_convergence(ns, aps)
    assert fit.a == pytest.approx(a, abs=1e-6)
    assert fit.b == pytest.approx(b, abs=1e-6)
    assert fit.c == pytest.approx(c, abs=1e-6)
    assert fit.r2 > 0.9999
    assert fit.predict(64) > fit.predict(32)               # still climbing toward a
    assert fit.predict(10_000) == pytest.approx(a, abs=1e-2)


def test_fit_convergence_validates_input():
    with pytest.raises(ValueError):
        fit_convergence([1, 2], [0.1, 0.2])                # < 3 points
    with pytest.raises(ValueError):
        fit_convergence([1, 2, 3], [0.1, 0.2])             # mismatched lengths
    with pytest.raises(ValueError):
        fit_convergence([5, 5, 5], [0.1, 0.2, 0.3])        # N must vary
    with pytest.raises(ValueError):
        fit_convergence([0, 1, 2], [0.1, 0.2, 0.3])        # N must be > 0


# ---------------------------------------------------------------- BWT / FWT

def test_bwt_detects_forgetting():
    R = [[0.90, 0.10, 0.10],
         [0.80, 0.85, 0.20],
         [0.75, 0.70, 0.95]]
    # mean((0.75-0.90), (0.70-0.85)) = mean(-0.15, -0.15) = -0.15
    assert bwt(R) == pytest.approx(-0.15)


def test_fwt_matches_hand_value():
    R = [[0.90, 0.10, 0.10],
         [0.80, 0.85, 0.20],
         [0.75, 0.70, 0.95]]
    baseline = [0.1, 0.1, 0.1]
    # mean((R[0][1]-0.1), (R[1][2]-0.1)) = mean(0.0, 0.1) = 0.05
    assert fwt(R, baseline) == pytest.approx(0.05)


def test_transfer_validates_shape():
    with pytest.raises(ValueError):
        bwt([[0.1, 0.2]])                                  # < 2 tasks
    with pytest.raises(ValueError):
        bwt([[0.1, 0.2], [0.3]])                           # not square
    with pytest.raises(ValueError):
        fwt([[0.1, 0.2], [0.3, 0.4]], [0.1])               # baseline wrong length


# ---------------------------------------------------------------- registry path

def test_timelines_and_snapshot_from_registry(tmp_path):
    from command_center.improvement.discovery import Finding, Pillar
    reg = ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))
    f = Finding(pillar=Pillar.CODE_QUALITY, source="t", title="x", claim="c", evidence="e")
    d = f.to_experiment_definition()
    reg.register(d)
    # a promotion event lands in the Ledger (timeline reader keys off event kinds)
    reg.append_event(EventRecord(kind="PROMOTED", experiment_id=d.experiment_id,
                                 actor_role="human", action="promoted"))
    timelines = timelines_from_registry(reg)
    assert len(timelines) == 1
    assert timelines[0].group == "code_quality"            # parsed from the EXP-scan- id
    assert timelines[0].accepted is True
    snap = snapshot(reg, window_days=3650, now_iso="2030-01-01T00:00:00+00:00",
                    total_cost_usd=10.0, n_suppressed_negative=1, n_findings=4)
    assert snap.dora.deploys == 1
    assert snap.cost_per_accepted_usd == pytest.approx(10.0)
    assert snap.negative_hit_rate == pytest.approx(0.25)
    assert json.loads(json.dumps(snap.to_dict()))["rollback_rate"] == 0.0

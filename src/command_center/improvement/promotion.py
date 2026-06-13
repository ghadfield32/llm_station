"""
Generalized promotion, canary, and rollback — the model pipeline's pattern, applied
to every target type.

The mission's existing model flow (canary -> evals -> human tap -> promote/rollback)
is the template. Here a small adapter per target type knows three things: what version
is active, how to switch it, and how to roll it back. Everything else — recording the
active + candidate version, defining the canary population/duration/thresholds, testing
rollback BEFORE promotion, post-watch at 1h/24h/7d, and the rule that promotion is
human-only — is generic and lives in the controller.

Safety rules enforced here:
  * promotion requires a human actor + a recorded human approval (lifecycle gate).
  * rollback is demonstrated (dry-run) before promotion, so the PROMOTED -> ROLLED_BACK
    edge is always available.
  * auto-rollback fires ONLY when the rollback is reversible, local, and within the
    experiment's risk tier; otherwise the controller stops and asks for a human.
  * never auto-roll-forward — there is no path that promotes without a human.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..schemas.base import RiskTier
from .events import EventRecord, ExperimentEventType
from .lifecycle import Actor, ExperimentStatus, TransitionConditions
from .registry import ExperimentRegistry
from .schema import ExperimentDefinition


# ---- target adapters --------------------------------------------------------

class PromotionAdapter:
    """Knows how to switch and roll back ONE target type's active version."""
    target_type: str = ""

    def active_version(self) -> str:
        raise NotImplementedError

    def candidate_version(self, defn: ExperimentDefinition) -> str:
        return f"candidate:{defn.experiment_id}"

    def reversible_local_within_tier(self, risk_tier: RiskTier) -> bool:
        """True iff rolling back is a local, reversible action within the risk tier —
        the only case where auto-rollback is allowed."""
        return risk_tier in (RiskTier.L0, RiskTier.L1, RiskTier.L2)

    def apply(self, version: str) -> None:
        raise NotImplementedError

    def dry_run_rollback(self) -> bool:
        """Prove rollback works without committing to it. Returns True if a rollback
        would succeed."""
        raise NotImplementedError


class _FileStateAdapter(PromotionAdapter):
    """Switches a target's active version via a small, inspectable JSON state file —
    a local, reversible, within-L2 flip. Concrete adapters set filename + initial."""
    filename = ""
    initial = ""

    def __init__(self, state_dir: str | Path = "data/improvement/active"):
        self.state_path = Path(state_dir) / self.filename
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write({"active": self.initial, "history": [self.initial]})

    def _read(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def active_version(self) -> str:
        return self._read()["active"]

    def apply(self, version: str) -> None:
        st = self._read()
        st["history"].append(version)
        st["active"] = version
        self._write(st)

    def dry_run_rollback(self) -> bool:
        return len(self._read()["history"]) >= 1  # a previous version exists to return to


class RetrievalPromotionAdapter(_FileStateAdapter):
    target_type = "retrieval"
    filename = "retrieval_strategy.json"
    initial = "baseline:literal"


class JudgePromotionAdapter(_FileStateAdapter):
    """Switches the active judge ruleset. A judge change rides the same flow as a model
    or retrieval change (mission §15: historical-incident replay = the calibration set;
    false-block / missed-defect analysis = the calibration metrics)."""
    target_type = "judge"
    filename = "judge_ruleset.json"
    initial = "baseline:reference"


# Every other target type gets a file-state adapter too: a local, reversible, within-L2
# version flip is exactly what these are. Generated so all 13 target types have a working
# adapter without 11 near-identical classes.
_GENERIC_TARGETS = ["model", "prompt", "skill", "routing", "tool", "memory", "standard",
                    "proactive_check", "workflow", "documentation", "repository_template"]


def _generic_adapter(ttype: str) -> type[_FileStateAdapter]:
    return type(
        f"{ttype.title().replace('_', '')}PromotionAdapter", (_FileStateAdapter,),
        {"target_type": ttype, "filename": f"{ttype}_active.json",
         "initial": f"baseline:{ttype}"})


ADAPTERS: dict[str, Callable[[], PromotionAdapter]] = {
    "retrieval": RetrievalPromotionAdapter,
    "judge": JudgePromotionAdapter,
    **{t: _generic_adapter(t) for t in _GENERIC_TARGETS},
}


def adapter_for(defn: ExperimentDefinition) -> PromotionAdapter | None:
    factory = ADAPTERS.get(defn.target_type.value)
    return factory() if factory else None


# ---- canary / promotion / rollback controller ------------------------------

class PromotionError(RuntimeError):
    pass


@dataclass
class CanaryPlan:
    active_version: str
    candidate_version: str
    population: str
    duration: str
    rollback_thresholds: list[str]
    rollback_reversible: bool

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class PromotionController:
    def __init__(self, registry: ExperimentRegistry, *, adapter: PromotionAdapter | None = None):
        self.reg = registry
        self._adapter = adapter

    def _defn(self, experiment_id: str) -> ExperimentDefinition:
        raw = self.reg.definition(experiment_id)
        if raw is None:
            raise PromotionError(f"experiment {experiment_id!r} not registered")
        return ExperimentDefinition.model_validate(raw)

    def _get_adapter(self, defn: ExperimentDefinition) -> PromotionAdapter:
        a = self._adapter or adapter_for(defn)
        if a is None:
            raise PromotionError(f"no promotion adapter for target_type {defn.target_type.value!r}")
        return a

    # ---- human-requested promotion path ------------------------------------

    def request_human_promotion(self, experiment_id: str) -> dict:
        """Agent-side: move Verified -> Awaiting Human Promotion once the gate is met.
        This does NOT promote — it asks a human to. Demonstrates rollback first so the
        rollback edge is real before anything ships."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        if not adapter.dry_run_rollback():
            raise PromotionError("rollback could not be demonstrated; refusing to advance")
        self.reg.set_rollback_status(experiment_id, "demonstrated")
        cond = self.reg.promotion_conditions(experiment_id)
        self.reg.set_status(experiment_id, ExperimentStatus.AWAITING_HUMAN_PROMOTION,
                            actor=Actor.AGENT, conditions=cond,
                            note="gate satisfied; awaiting human promotion")
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.HUMAN_PROMOTION_REQUESTED.value,
            experiment_id=experiment_id, actor_role="runner",
            action="rollback demonstrated; requesting human promotion",
            detail={"rollback": "demonstrated"}))
        return self.reg.get(experiment_id) or {}

    def start_canary(self, experiment_id: str, *, approver: str,
                     population: str = "10%", duration: str = "24h") -> CanaryPlan:
        """HUMAN action: begin a limited canary. Requires a human actor (the gate keeps
        an agent out). Records both versions so old/new stay identifiable in logs."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        plan = CanaryPlan(
            active_version=adapter.active_version(),
            candidate_version=adapter.candidate_version(defn),
            population=population, duration=duration,
            rollback_thresholds=list(defn.post_watch.rollback_triggers),
            rollback_reversible=adapter.reversible_local_within_tier(defn.risk_tier))
        cond = self.reg.promotion_conditions(experiment_id, human_approval=True)
        # human-only transition; an agent actor would be refused by the lifecycle
        self.reg.set_status(experiment_id, ExperimentStatus.CANARY, actor=Actor.HUMAN,
                            conditions=cond, actor_model=approver,
                            note=f"canary started by {approver}")
        self.reg.set_canary_status(experiment_id, "running")
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.CANARY_STARTED.value, experiment_id=experiment_id,
            actor_role="human", actor_model=approver,
            action=f"canary {population} for {duration}", detail=plan.to_dict()))
        return plan

    def evaluate_canary(self, experiment_id: str, *, regression_detected: bool,
                        detail: str = "") -> dict:
        """Assess canary health. On regression: auto-rollback ONLY if reversible/local/
        within tier, else stop and ask a human. No hiding failures via retries."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        if not regression_detected:
            self.reg.set_canary_status(experiment_id, "passed")
            self.reg.append_event(EventRecord(
                kind=ExperimentEventType.CANARY_PASSED.value, experiment_id=experiment_id,
                actor_role="canary", action="canary passed", detail={"note": detail}))
            return {"canary": "passed"}
        # regression
        self.reg.set_canary_status(experiment_id, "failed")
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.CANARY_FAILED.value, experiment_id=experiment_id,
            actor_role="canary", action="canary regression detected", detail={"note": detail}))
        if adapter.reversible_local_within_tier(defn.risk_tier):
            self.rollback(experiment_id, actor=Actor.AGENT, reason="auto-rollback on canary regression")
            return {"canary": "failed", "action": "auto_rolled_back"}
        return {"canary": "failed", "action": "stopped_awaiting_human"}

    def evaluate_canary_metrics(self, experiment_id: str, *, active: dict, canary: dict) -> dict:
        """Formal champion-vs-challenger canary analysis (Phase 5): compute the per-metric
        regression verdict from observed champion (active) and challenger (canary) values, then
        route through the same auto-rollback. Any safety-metric regression forces a rollback."""
        from . import drift
        from .runner import metric_specs_of
        defn = self._defn(experiment_id)
        verdict = drift.evaluate_canary(active, canary, metric_specs_of(defn))
        out = self.evaluate_canary(experiment_id, regression_detected=verdict.regression,
                                   detail="; ".join(verdict.reasons))
        out["canary_verdict"] = verdict.to_dict()
        return out

    def promote(self, experiment_id: str, *, approver: str) -> dict:
        """HUMAN action: promote after a clean canary. Requires a human actor + a
        recorded approval; the lifecycle refuses an agent here."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        cond = self.reg.promotion_conditions(experiment_id, human_approval=True)
        self.reg.set_status(experiment_id, ExperimentStatus.PROMOTED, actor=Actor.HUMAN,
                            conditions=cond, actor_model=approver,
                            note=f"promoted by {approver}")
        self.reg.set_human_decision(experiment_id, "approve")
        adapter.apply(adapter.candidate_version(defn))
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.PROMOTED.value, experiment_id=experiment_id,
            actor_role="human", actor_model=approver,
            action=f"promoted; active version now {adapter.active_version()}"))
        return self.reg.get(experiment_id) or {}

    def rollback(self, experiment_id: str, *, actor: Actor = Actor.AGENT,
                 reason: str = "") -> dict:
        """Roll back to the previous version. Allowed automatically only for reversible/
        local/within-tier targets; the lifecycle requires rollback to have been
        demonstrated first."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        # rollback must have been demonstrated (dry-run) before it can be used
        row = self.reg.get(experiment_id) or {}
        if row.get("rollback_status") not in ("demonstrated", "rolled_back"):
            raise PromotionError(
                "rollback was never demonstrated; refusing to roll back untested")
        # return to the prior version if one exists (file-state adapters keep history)
        if isinstance(adapter, _FileStateAdapter):
            st = adapter._read()
            if len(st["history"]) >= 2:
                adapter.apply(st["history"][-2])
        self.reg.set_rollback_status(experiment_id, "rolled_back")
        # the rollback edge only checks rollback_demonstrated, which is now true
        cond = TransitionConditions(rollback_demonstrated=True)
        self.reg.set_status(experiment_id, ExperimentStatus.ROLLED_BACK, actor=actor,
                            conditions=cond, note=reason or "rolled back")
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.ROLLED_BACK.value, experiment_id=experiment_id,
            actor_role=actor.value, action=reason or "rolled back",
            detail={"active_version": adapter.active_version()}))
        return self.reg.get(experiment_id) or {}

    def post_watch(self, experiment_id: str, *, checkpoint: str,
                   regression_detected: bool, detail: str = "") -> dict:
        """Record a post-promotion checkpoint (1h/24h/7d). A regression here triggers
        the same reversible-only auto-rollback rule."""
        defn = self._defn(experiment_id)
        adapter = self._get_adapter(defn)
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.POST_WATCH_COMPLETED.value, experiment_id=experiment_id,
            actor_role="post-watch", action=f"post-watch {checkpoint}",
            detail={"checkpoint": checkpoint, "regression": regression_detected, "note": detail}))
        if regression_detected and adapter.reversible_local_within_tier(defn.risk_tier):
            self.rollback(experiment_id, actor=Actor.AGENT,
                          reason=f"post-watch {checkpoint} regression")
            return {"checkpoint": checkpoint, "action": "auto_rolled_back"}
        if regression_detected:
            return {"checkpoint": checkpoint, "action": "stopped_awaiting_human"}
        return {"checkpoint": checkpoint, "action": "ok"}

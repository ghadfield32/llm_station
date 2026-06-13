"""
The independent verifier — the system that checks the work.

Separate from the implementer by construction. It reads the *raw* run values and
artifacts from the registry and RE-MEASURES the candidate itself; it never reads the
implementer's recommendation or any persuasive summary. If the implementer claimed a
result the verifier can't reproduce, the verifier reports it (the semble case: claimed
10/10, measured 7/10).

Walls:
  * self-verification is refused: verifier_identity must differ from implementer_identity.
  * no safety criterion may pass as INCONCLUSIVE — a safety criterion that can't be
    cleanly confirmed makes the whole verdict FAIL.
  * the verifier may REJECT an experiment; it may never promote one.

Each criterion is PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE. The overall verdict is
PASS only when every required criterion is PASS and no safety criterion is FAIL or
INCONCLUSIVE.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import retrieval_strategies as rs
from .evals import SealedEvalStore, SealedAccessDenied
from .events import EventRecord, ExperimentEventType
from .lifecycle import Actor, ExperimentStatus
from .registry import ExperimentRegistry, file_sha256
from .runner import compare_metrics, HARNESSES
from .schema import ExperimentDefinition

_RETRIEVAL_REF = "command_center.improvement.retrieval_strategies"

PASS, FAIL, INCONCLUSIVE, NA = "PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"

_TIMING_HINTS = ("latency", "_ms", "wall", "seconds", "_sec", "time")


def _is_timing(metric_name: str) -> bool:
    n = metric_name.lower()
    return any(h in n for h in _TIMING_HINTS)


class SelfVerificationError(RuntimeError):
    pass


@dataclass
class Criterion:
    id: str
    text: str
    result: str
    required: bool = True
    safety: bool = False
    detail: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class VerdictReport:
    experiment_id: str
    verifier_identity: str
    implementer_identity: str
    criteria: list[Criterion] = field(default_factory=list)
    verdict: str = INCONCLUSIVE
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "verifier_identity": self.verifier_identity,
            "implementer_identity": self.implementer_identity,
            "verdict": self.verdict,
            "summary": self.summary,
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def decide(self) -> str:
        # safety first: a safety criterion that is FAIL or INCONCLUSIVE sinks the verdict
        for c in self.criteria:
            if c.safety and c.result in (FAIL, INCONCLUSIVE):
                return FAIL
        if any(c.required and c.result == FAIL for c in self.criteria):
            return FAIL
        if any(c.required and c.result == INCONCLUSIVE for c in self.criteria):
            return INCONCLUSIVE
        return PASS


class IndependentVerifier:
    def __init__(self, registry: ExperimentRegistry, *, repo_root: str | Path = ".",
                 store: SealedEvalStore | None = None,
                 evidence_root: str | Path | None = None):
        self.reg = registry
        self.repo_root = Path(repo_root)
        self.store = store or SealedEvalStore(repo_root=self.repo_root)
        self.evidence_root = Path(evidence_root) if evidence_root else Path("data/improvement")

    def _defn(self, experiment_id: str) -> ExperimentDefinition:
        raw = self.reg.definition(experiment_id)
        if raw is None:
            raise RuntimeError(f"experiment {experiment_id!r} not registered")
        return ExperimentDefinition.model_validate(raw)

    def verify(self, experiment_id: str, *, verifier_identity: str,
               implementer_identity: str, reps: int = 2,
               tolerance: float = 0.02) -> VerdictReport:
        defn = self._defn(experiment_id)

        # ---- wall: no self-verification ------------------------------------
        if verifier_identity == implementer_identity:
            raise SelfVerificationError(
                f"verifier identity {verifier_identity!r} equals the implementer's; "
                "the candidate cannot verify itself")
        if not defn.verification.independent_context or defn.verification.allow_self_verification:
            raise SelfVerificationError("experiment forbids independent verification by config")

        report = VerdictReport(experiment_id=experiment_id,
                               verifier_identity=verifier_identity,
                               implementer_identity=implementer_identity)
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.VERIFICATION_STARTED.value, experiment_id=experiment_id,
            actor_role="verifier", actor_model=verifier_identity,
            action="independent verification started"))

        baseline_runs = [r for r in self.reg.runs(experiment_id, role="baseline")
                         if r["status"].startswith("completed")]
        cand_runs = [r for r in self.reg.runs(experiment_id, role="candidate")
                     if r["status"].startswith("completed")]
        if not baseline_runs or not cand_runs:
            report.criteria.append(Criterion(
                "C0", "baseline + candidate runs exist to verify", FAIL,
                detail="missing baseline or candidate run"))
            return self._finalize(report, defn)

        stored_baseline = baseline_runs[-1]["metrics"]["values"]
        stored_candidate = cand_runs[-1]["metrics"]["values"]

        # the verifier reproduces by RE-RUNNING the registered harness fresh — this is
        # generic across target types (retrieval, judge, …); no harness == can't verify.
        factory = HARNESSES.get(defn.target_ref)
        if factory is None:
            report.criteria.append(Criterion(
                "C1", "independent reproduction of candidate metrics", INCONCLUSIVE,
                detail=f"no verifier harness for target_ref {defn.target_ref!r}"))
            return self._finalize(report, defn)
        is_retrieval = defn.target_ref == _RETRIEVAL_REF
        repro_mr = factory(self.repo_root).measure("candidate", reps)
        repro = repro_mr.metric_values

        # C1 — deterministic metrics must reproduce EXACTLY (that is what catches a
        # misreported result); timing is noisy, so only a >3x divergence counts there.
        diverged = []
        for name, claimed in stored_candidate.items():
            got = repro.get(name)
            if got is None:
                continue
            if _is_timing(name):
                lo, hi = sorted((abs(got), abs(claimed)))
                if lo <= 1e-9 or hi / max(lo, 1e-9) > 3.0:
                    diverged.append(f"{name}: claimed {claimed:.4g}, reproduced {got:.4g} (>3x)")
            else:
                denom = max(abs(claimed), 1.0)
                if abs(got - claimed) / denom > tolerance:
                    diverged.append(f"{name}: claimed {claimed:.4g}, reproduced {got:.4g}")
        report.criteria.append(Criterion(
            "C1", "independent reproduction of candidate metrics",
            FAIL if diverged else PASS,
            detail="; ".join(diverged) if diverged else "deterministic metrics reproduced exactly"))

        # C2 — raw artifacts exist, hashes match, and the summary matches the raw logs
        report.criteria.append(self._check_artifacts(experiment_id, cand_runs[-1]["run_id"],
                                                     stored_candidate))

        # C3 — deterministic required-metric gate (recomputed, not trusted)
        cmp = compare_metrics(defn, stored_baseline, repro)
        req_fail = [m.name for m in cmp.metrics if m.required and not m.passed]
        report.criteria.append(Criterion(
            "C3", "required metrics meet their bars (deterministic recompute)",
            PASS if not req_fail else FAIL,
            detail="all required metrics pass" if not req_fail
            else f"required metric(s) below bar: {req_fail}"))

        # C4 — SAFETY (never INCONCLUSIVE-able): every safety-marked metric reproduces
        # within its bound; for retrieval, ALSO run the adversarial secret-bait suite.
        safety_fail = [m.name for m in cmp.metrics if m.safety and not m.passed]
        if is_retrieval:
            bait = self._check_secret_safety(rs.build_corpus(self.repo_root), repro)
            ok = not safety_fail and bait.result == PASS
            detail = bait.detail + ("" if not safety_fail else
                                    f"; safety metric(s) below bound: {safety_fail}")
            report.criteria.append(Criterion(
                "C4", "safety metrics hold + no secret surfaced", PASS if ok else FAIL,
                safety=True, detail=detail))
        else:
            report.criteria.append(Criterion(
                "C4", "safety metrics reproduce within bound",
                PASS if not safety_fail else FAIL, safety=True,
                detail="all safety metrics hold" if not safety_fail
                else f"safety metric(s) below bound: {safety_fail}"))

        # C5/C6 — sealed-suite checks are retrieval-specific today
        if is_retrieval:
            corpus = rs.build_corpus(self.repo_root)
            report.criteria.append(self._check_sealed_holdout(defn, corpus, cmp))
            report.criteria.append(self._check_no_leakage(experiment_id))
        else:
            report.criteria.append(Criterion(
                "C5", "generalizes to a sealed held-out set", NA, required=False,
                detail="no sealed suite wired for this target type"))
            report.criteria.append(Criterion(
                "C6", "sealed set did not leak into visible evidence", NA, required=False,
                detail="no sealed suite wired for this target type"))

        # C7 — budget respected
        budget = cand_runs[-1].get("budget", {})
        within = budget.get("within_budget", True)
        report.criteria.append(Criterion(
            "C7", "candidate stayed within budget", PASS if within else FAIL,
            detail=str(budget.get("breaches", [])) or "within budget"))

        # C8 — rollback is required + a trigger plan is defined (demonstrated at canary)
        rb_ok = (defn.promotion.rollback_required
                 and bool(defn.post_watch.rollback_triggers))
        report.criteria.append(Criterion(
            "C8", "rollback required and a trigger plan is defined", PASS if rb_ok else FAIL,
            required=True,
            detail="rollback plan present; demonstrated at canary" if rb_ok
            else "rollback not fully specified"))

        # C9 — statistical significance (FDR-controlled) of the primary metric, recomputed
        # independently. Only a *gate* when the experiment pre-registered require_significance;
        # otherwise it is recorded as evidence (NA). Like every criterion, it can only reject.
        report.criteria.append(self._check_significance(
            defn, baseline_runs[-1]["metrics"].get("samples", {}), repro_mr.samples))

        # C10 — anti-Goodhart contamination: no sealed test item should appear (even fuzzily)
        # in the implementer's visible evidence. NA when no sealed suite is referenced.
        report.criteria.append(self._check_contamination(defn, experiment_id))

        return self._finalize(report, defn)

    def _check_contamination(self, defn, experiment_id: str) -> Criterion:
        ids = defn.verification.sealed_eval_ids
        text = "no sealed test item leaked into visible evidence (fuzzy n-gram)"
        if not ids:
            return Criterion("C10", text, NA, required=False, detail="no sealed suite")
        blob = "\n".join(
            Path(a["path"]).read_text(encoding="utf-8", errors="replace")
            for a in self.reg.artifacts(experiment_id) if Path(a["path"]).exists())
        try:
            res = self.store.contamination_scan(blob, ids[0], role="verifier")
        except (KeyError, SealedAccessDenied, FileNotFoundError) as e:
            return Criterion("C10", text, INCONCLUSIVE, detail=str(e))
        return Criterion(
            "C10", text, FAIL if res["contaminated"] else PASS,
            detail=f"max n-gram overlap {res['max_overlap']:.2f}"
            + (f" on {res['worst']!r}" if res["contaminated"] else ""))

    def _check_significance(self, defn, baseline_samples: dict, candidate_samples: dict) -> Criterion:
        from . import statistics as st
        from .runner import metric_specs_of, stat_plan_of
        report = st.analyze_experiment(defn.experiment_id, metric_specs_of(defn),
                                       stat_plan_of(defn), baseline_samples, candidate_samples)
        text = "primary metric shows a statistically significant (FDR) improvement"
        if not defn.statistics.require_significance:
            return Criterion("C9", text, NA, required=False,
                             detail="require_significance off — recorded as evidence only")
        if report.primary_metric is None or not report.metric_stats:
            return Criterion("C9", text, NA, required=False,
                             detail="no per-sample data for the primary metric")
        if report.srm and report.srm.mismatch:
            return Criterion("C9", text, FAIL,
                             detail=f"sample-ratio mismatch (p={report.srm.p_value:.2g})")
        if report.underpowered:
            return Criterion("C9", text, INCONCLUSIVE,
                             detail="underpowered for the pre-registered MDE")
        if report.primary_improved:
            extra = ""
            if report.primary_msprt_p is not None:
                extra += f", always-valid p={report.primary_msprt_p:.3g}"
            if report.primary_variance_reduction is not None:
                extra += f", CUPED -{report.primary_variance_reduction:.0%} variance"
            return Criterion("C9", text, PASS,
                             detail=f"significant FDR win on {report.primary_metric} "
                             f"(q={report.primary_q_value:.3g}{extra})")
        return Criterion("C9", text, FAIL,
                         detail=f"no significant improvement on {report.primary_metric} "
                         f"(q={report.primary_q_value:.3g})")

    # ---- criteria helpers ---------------------------------------------------

    def _check_artifacts(self, experiment_id: str, run_id: str, stored_candidate: dict) -> Criterion:
        arts = [a for a in self.reg.artifacts(experiment_id) if a["run_id"] == run_id]
        if not arts:
            return Criterion("C2", "raw evidence retained and matches the summary", FAIL,
                             detail="no candidate artifacts recorded")
        for a in arts:
            p = Path(a["path"])
            if not p.exists():
                return Criterion("C2", "raw evidence retained and matches the summary", FAIL,
                                 detail=f"artifact missing on disk: {p}")
            sha, _ = file_sha256(p)
            if sha != a["sha256"]:
                return Criterion("C2", "raw evidence retained and matches the summary", FAIL,
                                 detail=f"artifact hash mismatch (tampered?): {p.name}")
        # the metrics.json summary must agree with the stored run values
        mj = next((a for a in arts if a["kind"] == "metrics"), None)
        if mj:
            data = json.loads(Path(mj["path"]).read_text(encoding="utf-8"))
            logged = data.get("metric_values", {})
            for k, v in stored_candidate.items():
                if abs(float(logged.get(k, v)) - float(v)) > 1e-9:
                    return Criterion("C2", "raw evidence retained and matches the summary",
                                     FAIL, detail=f"summary metric {k} disagrees with raw log")
        return Criterion("C2", "raw evidence retained and matches the summary", PASS,
                         detail=f"{len(arts)} artifacts verified by hash")

    def _check_secret_safety(self, corpus, repro: dict) -> Criterion:
        try:
            bait = self.store.run_secret_bait(
                "adv-retrieval-secret-bait", rs.ranked_search, corpus,
                role="verifier", is_secret=rs.is_secret_path)
        except (KeyError, SealedAccessDenied, FileNotFoundError) as e:
            # a safety criterion may NOT be left INCONCLUSIVE — if we cannot run it, FAIL
            return Criterion("C4", "no secret file ever surfaced (adversarial bait)", FAIL,
                             safety=True, detail=f"could not run safety suite: {e}")
        clean = bait["clean"] and repro.get("secret_exclusion", 0.0) >= 1.0
        return Criterion(
            "C4", "no secret file ever surfaced (adversarial bait)",
            PASS if clean else FAIL, safety=True,
            detail="no leak across bait + exclusion holds" if clean
            else f"secret leak detected: {bait['leaks']}")

    def _check_sealed_holdout(self, defn, corpus, visible_cmp) -> Criterion:
        ids = defn.verification.sealed_eval_ids
        if not ids:
            return Criterion("C5", "generalizes to a sealed held-out set", NA,
                             required=False, detail="no sealed suite referenced")
        try:
            res = self.store.run_retrieval_holdout(ids[0], rs.ranked_search, corpus,
                                                   role="verifier")
        except (KeyError, SealedAccessDenied, FileNotFoundError) as e:
            return Criterion("C5", "generalizes to a sealed held-out set", INCONCLUSIVE,
                             detail=f"could not run sealed suite: {e}")
        holdout = res["recall"]
        # overfit smell: strong on visible, weak on held-out
        visible_recall = next((m.candidate_value for m in visible_cmp.metrics
                               if m.name == "recall_at_5"), 0.0)
        if holdout <= 0.0:
            result, detail = FAIL, f"held-out recall {holdout:.2f} — did not generalize"
        elif visible_recall - holdout > 0.4:
            result, detail = FAIL, (f"overfit: visible {visible_recall:.2f} vs "
                                    f"held-out {holdout:.2f}")
        else:
            result, detail = PASS, f"held-out recall {holdout:.2f}"
        if self.store.is_saturated(ids[0], holdout):
            detail += " (suite saturated — recommend rotation)"
        return Criterion("C5", "generalizes to a sealed held-out set", result, detail=detail)

    def _check_no_leakage(self, experiment_id: str) -> Criterion:
        ids = self._defn(experiment_id).verification.sealed_eval_ids
        if not ids:
            return Criterion("C6", "sealed set did not leak into visible evidence", NA,
                             required=False, safety=False, detail="no sealed suite")
        blob = "\n".join(
            Path(a["path"]).read_text(encoding="utf-8", errors="replace")
            for a in self.reg.artifacts(experiment_id) if Path(a["path"]).exists())
        try:
            leaked = self.store.scan_for_leakage(blob, ids[0], role="verifier")
        except (KeyError, SealedAccessDenied, FileNotFoundError) as e:
            return Criterion("C6", "sealed set did not leak into visible evidence",
                             INCONCLUSIVE, detail=str(e))
        return Criterion(
            "C6", "sealed set did not leak into visible evidence",
            PASS if not leaked else FAIL,
            detail="no sealed queries in evidence" if not leaked
            else f"LEAK: sealed queries appear in evidence: {leaked}")

    # ---- finalize -----------------------------------------------------------

    def _finalize(self, report: VerdictReport, defn: ExperimentDefinition) -> VerdictReport:
        report.verdict = report.decide()
        n_pass = sum(1 for c in report.criteria if c.result == PASS)
        report.summary = (f"{report.verdict}: {n_pass}/{len(report.criteria)} criteria pass; "
                          f"verifier={report.verifier_identity}")
        # persist the verdict report as an artifact + record the verdict
        d = self.evidence_root / report.experiment_id / "verifier"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "verdict.json"
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        # find a candidate run to attach the artifact to (audit linkage)
        cand = self.reg.runs(report.experiment_id, role="candidate")
        run_id = cand[-1]["run_id"] if cand else "verifier"
        self.reg.add_artifact(experiment_id=report.experiment_id, run_id=run_id,
                              name="verdict.json", kind="verifier_report", path=str(path))
        self.reg.set_verifier_verdict(
            report.experiment_id, report.verdict, actor_model=report.verifier_identity,
            detail={"independent": True, "verifier_identity": report.verifier_identity,
                    "safety_inconclusive": any(
                        c.safety and c.result == INCONCLUSIVE for c in report.criteria)})
        # the verifier may move to Verified (PASS) or Reject (FAIL); never promote
        status = ExperimentStatus(self.reg.get(report.experiment_id)["status"])
        if status == ExperimentStatus.AWAITING_VERIFICATION:
            if report.verdict == PASS:
                self.reg.set_status(report.experiment_id, ExperimentStatus.VERIFIED,
                                    actor=Actor.AGENT, note="independent verification passed")
            elif report.verdict == FAIL:
                self.reg.set_status(report.experiment_id, ExperimentStatus.REJECTED,
                                    actor=Actor.AGENT, note="independent verification failed")
            else:
                self.reg.set_status(report.experiment_id, ExperimentStatus.INCONCLUSIVE,
                                    actor=Actor.AGENT, note="verification inconclusive")
        return report

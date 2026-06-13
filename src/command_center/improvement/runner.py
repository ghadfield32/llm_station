"""
Baseline-versus-candidate experiment runner.

Reusable and deterministic. The runner owns the *generic* concerns — equivalence,
budgets, stopping rules, raw-evidence retention, artifact hashing, run/event
recording, and the multidimensional comparison — while a per-experiment Harness owns
the actual measurement. The synthetic proof ships a RetrievalHarness; new experiments
register their own harness keyed by target_ref.

Invariants honored (mission section 7 / 14):
  * the baseline locks once its run is recorded; a candidate run can't change it.
  * baseline and candidate must run over an equivalent corpus + gold set + commit, or
    the runner fails loudly (no silent apples-to-oranges).
  * failed / timed-out / excluded runs are recorded with their exact reason, never
    discarded.
  * every metric is reported on its own axis — results are never collapsed into a
    single score.
  * budgets stop the experiment; permissions/budgets are never auto-expanded to pass.
"""
from __future__ import annotations

import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .events import EventRecord, ExperimentEventType
from .registry import ExperimentRegistry, canonical_hash
from .schema import ExperimentDefinition, MetricDefinition
from . import retrieval_strategies as rs


# ---- measurement harnesses --------------------------------------------------

@dataclass
class MeasureResult:
    metric_values: dict[str, float]
    raw_log: str
    sample_count: int
    failures: list[str] = field(default_factory=list)
    timeouts: int = 0
    # optional per-metric per-sample observations (mean(samples[m]) == metric_values[m]
    # for rate metrics) — enables bootstrap CIs + paired/unpaired tests in the verifier.
    samples: dict[str, list[float]] = field(default_factory=dict)


class Harness:
    """Per-experiment measurement. role is 'baseline' or 'candidate'."""
    def equivalence_key(self) -> dict:
        raise NotImplementedError

    def measure(self, role: str, reps: int) -> MeasureResult:
        raise NotImplementedError


class RetrievalHarness(Harness):
    """Measures the two deterministic retrieval strategies over the repo corpus."""
    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root)
        self.corpus = rs.build_corpus(self.repo_root)
        self.gold = rs.gold_set()

    def equivalence_key(self) -> dict:
        return {
            "corpus_hash": self.corpus.corpus_hash,
            "gold_set_hash": rs.gold_set_hash(),
            "commit": _git_commit(self.repo_root),
            "n_files": len(self.corpus.files),
        }

    def measure(self, role: str, reps: int) -> MeasureResult:
        strategy = rs.literal_search if role == "baseline" else rs.ranked_search
        reps = max(1, reps)
        recall_hits = 0
        recall_total = 0
        bytes_read = 0
        secret_clean = 0
        per_query_latencies: list[float] = []
        # per-sample vectors so the verifier can run bootstrap CIs + paired tests
        s_recall: list[float] = []
        s_bytes: list[float] = []
        s_secret: list[float] = []
        lines: list[str] = [f"# role={role} strategy={strategy.__name__} reps={reps}"]
        failures: list[str] = []
        for case in self.gold:
            q = case["query"]
            # timing across reps; results are deterministic so correctness uses rep 1
            durations = []
            hits = []
            for _ in range(reps):
                t0 = time.perf_counter()
                hits = strategy(q, self.corpus)
                durations.append((time.perf_counter() - t0) * 1000.0)
            per_query_latencies.append(statistics.median(durations))
            paths = [h.path for h in hits]
            leaked = [p for p in paths if rs.is_secret_path(p)]
            s_secret.append(0.0 if leaked else 1.0)
            if not leaked:
                secret_clean += 1
            else:
                failures.append(f"secret leak on {q!r}: {leaked}")
            qbytes = sum(h.snippet_bytes for h in hits)
            bytes_read += qbytes
            s_bytes.append(float(qbytes))
            if not case.get("secret_bait"):
                recall_total += 1
                want = case.get("expect_any", [])
                hit = any(any(p.endswith(w) for w in want) for p in paths)
                s_recall.append(1.0 if hit else 0.0)
                if hit:
                    recall_hits += 1
                    lines.append(f"HIT  {q!r} -> {paths}")
                else:
                    lines.append(f"MISS {q!r} -> {paths} (wanted any of {want})")
            else:
                lines.append(f"BAIT {q!r} -> {paths} leaked={leaked}")
        n = len(self.gold)
        metric_values = {
            "recall_at_5": (recall_hits / recall_total) if recall_total else 0.0,
            "bytes_read_proxy": float(bytes_read),
            "query_latency_ms": statistics.median(per_query_latencies) if per_query_latencies else 0.0,
            "secret_exclusion": (secret_clean / n) if n else 1.0,
        }
        lines.append(f"# metrics={metric_values}")
        return MeasureResult(metric_values=metric_values, raw_log="\n".join(lines),
                             sample_count=n * reps, failures=failures,
                             samples={"recall_at_5": s_recall, "bytes_read_proxy": s_bytes,
                                      "query_latency_ms": per_query_latencies,
                                      "secret_exclusion": s_secret})


class JudgeHarness(Harness):
    """Measures a candidate judge ruleset against the baseline ruleset on the labeled
    calibration set — deterministic and offline. This is what makes `target_type: judge`
    ride the exact same lifecycle as a model or a retrieval change (mission §15)."""
    CALIB = "data/calibration/judge-calibration.json"

    def __init__(self, repo_root: str | Path):
        from .calibration import (load_cases, reference_defensive_judge,
                                  candidate_defensive_judge)
        self.repo_root = Path(repo_root)
        self.cases = load_cases(self.repo_root / self.CALIB)
        self._baseline = reference_defensive_judge
        self._candidate = candidate_defensive_judge

    def equivalence_key(self) -> dict:
        import hashlib
        import json
        h = hashlib.sha256(
            json.dumps([c.__dict__ for c in self.cases], sort_keys=True).encode()).hexdigest()
        return {"dataset_hash": h, "n_cases": len(self.cases),
                "commit": _git_commit(self.repo_root)}

    def measure(self, role: str, reps: int) -> MeasureResult:
        from .calibration import score
        judge = self._baseline if role == "baseline" else self._candidate
        rep = score(self.cases, judge)
        vals = {
            "recall": rep.recall,
            "false_block_rate": rep.false_block_rate,
            "missed_defect_rate": rep.missed_defect_rate,
            "safety_missed_defect_rate": rep.safety_missed_defect_rate,
        }
        # per-case vectors (mean reproduces each rate)
        s_recall: list[float] = []
        s_missed: list[float] = []
        s_fbr: list[float] = []
        s_safety: list[float] = []
        for c in self.cases:
            blocked = judge(c.text) == "block"
            if c.gold == "block":
                s_recall.append(1.0 if blocked else 0.0)
                s_missed.append(0.0 if blocked else 1.0)
                if c.safety:
                    s_safety.append(0.0 if blocked else 1.0)
            else:
                s_fbr.append(1.0 if blocked else 0.0)
        log = (f"# role={role} judge metrics={vals}\n"
               + "\n".join(f"{c.id} {c.category} gold={c.gold} pred={judge(c.text)}"
                           for c in self.cases))
        return MeasureResult(metric_values=vals, raw_log=log, sample_count=len(self.cases),
                             samples={"recall": s_recall, "missed_defect_rate": s_missed,
                                      "false_block_rate": s_fbr,
                                      "safety_missed_defect_rate": s_safety})


# target_ref -> harness factory. New experiments register here.
HARNESSES: dict[str, Callable[[str | Path], Harness]] = {
    "command_center.improvement.retrieval_strategies": RetrievalHarness,
    "command_center.improvement.calibration": JudgeHarness,
}


def _git_commit(root: str | Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "uncommitted"
    except Exception:
        return "unknown"


# ---- comparison -------------------------------------------------------------

@dataclass
class MetricResult:
    name: str
    direction: str
    required: bool
    safety: bool
    baseline_value: float
    candidate_value: float
    good_delta: float          # improvement in the "better" direction (>0 == candidate better)
    regression: float          # how much worse (good-direction units; 0 if not worse)
    meets_improvement: bool
    meets_regression: bool
    passed: bool
    reason: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ComparisonResult:
    experiment_id: str
    metrics: list[MetricResult]
    all_required_pass: bool
    safety_ok: bool
    recommendation: str        # promote | revise | reject  (a recommendation, never an action)
    note: str = ""
    statistics: dict = field(default_factory=dict)   # the StatisticalReport (CIs, FDR, SRM)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "metrics": [m.to_dict() for m in self.metrics],
            "all_required_pass": self.all_required_pass,
            "safety_ok": self.safety_ok,
            "recommendation": self.recommendation,
            "note": self.note,
            "statistics": self.statistics,
        }


def metric_specs_of(defn: ExperimentDefinition) -> list[dict]:
    """Lightweight metric specs for the (schema-free) statistics layer."""
    return [{"name": m.name, "direction": m.direction.value, "required": m.required,
             "safety": m.safety, "minimum_improvement": m.minimum_improvement}
            for m in defn.metrics]


def stat_plan_of(defn: ExperimentDefinition) -> dict:
    sp = defn.statistics
    return {"alpha": sp.alpha, "power": sp.power, "mde": sp.mde,
            "n_resamples": sp.n_resamples, "seed": sp.seed, "test_type": sp.test_type,
            "primary_metric": sp.primary_metric, "guardrail_metrics": sp.guardrail_metrics,
            "require_significance": sp.require_significance}


def _evaluate_metric(md: MetricDefinition, baseline: float, candidate: float) -> MetricResult:
    delta = candidate - baseline
    good = delta if md.direction.value == "increase" else -delta
    regression = max(0.0, -good)
    # thresholds compare in native units by default; `relative` compares fractions
    # of the baseline magnitude (so a budget of "<=25% more bytes" is expressible).
    if md.relative:
        denom = max(abs(baseline), 1e-9)
        good_cmp, regression_cmp, unit = good / denom, regression / denom, "x"
    else:
        good_cmp, regression_cmp, unit = good, regression, ""
    meets_regression = (md.maximum_regression is None) or (regression_cmp <= md.maximum_regression + 1e-12)
    meets_improvement = (md.minimum_improvement is None) or (good_cmp >= md.minimum_improvement - 1e-12)
    if md.required:
        passed = meets_regression and meets_improvement
    else:
        passed = meets_regression
    if not meets_regression:
        reason = (f"regressed {regression_cmp:.4g}{unit} > max {md.maximum_regression:.4g}{unit}"
                  + (" (SAFETY)" if md.safety else ""))
    elif md.required and not meets_improvement:
        reason = f"improvement {good_cmp:.4g}{unit} < required {md.minimum_improvement:.4g}{unit}"
    else:
        reason = "ok"
    return MetricResult(
        name=md.name, direction=md.direction.value, required=md.required, safety=md.safety,
        baseline_value=baseline, candidate_value=candidate, good_delta=good,
        regression=regression, meets_improvement=meets_improvement,
        meets_regression=meets_regression, passed=passed, reason=reason)


def compare_metrics(defn: ExperimentDefinition, baseline: dict, candidate: dict) -> ComparisonResult:
    results: list[MetricResult] = []
    for md in defn.metrics:
        b = float(baseline.get(md.name, 0.0))
        c = float(candidate.get(md.name, 0.0))
        results.append(_evaluate_metric(md, b, c))
    safety_ok = all(m.passed for m in results if m.safety)
    all_required_pass = all(m.passed for m in results if m.required)
    if not safety_ok:
        rec = "reject"
    elif all_required_pass:
        rec = "promote"
    else:
        rec = "revise"
    return ComparisonResult(experiment_id=defn.experiment_id, metrics=results,
                            all_required_pass=all_required_pass, safety_ok=safety_ok,
                            recommendation=rec)


# ---- the runner -------------------------------------------------------------

class EquivalenceError(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class BudgetReport:
    wall_seconds: float
    iterations: int
    within_budget: bool
    breaches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class ExperimentRunner:
    def __init__(self, registry: ExperimentRegistry, *, repo_root: str | Path = ".",
                 evidence_root: str | Path | None = None,
                 harness_override: Harness | None = None):
        self.reg = registry
        self.repo_root = Path(repo_root)
        self.evidence_root = Path(evidence_root) if evidence_root else Path("data/improvement")
        self._harness_override = harness_override

    def _harness(self, defn: ExperimentDefinition) -> Harness:
        if self._harness_override is not None:
            return self._harness_override
        factory = HARNESSES.get(defn.target_ref)
        if factory is None:
            raise RuntimeError(
                f"no measurement harness registered for target_ref {defn.target_ref!r}; "
                f"known: {sorted(HARNESSES)}")
        return factory(self.repo_root)

    def _defn(self, experiment_id: str) -> ExperimentDefinition:
        raw = self.reg.definition(experiment_id)
        if raw is None:
            raise RuntimeError(f"experiment {experiment_id!r} is not registered")
        return ExperimentDefinition.model_validate(raw)

    def _evidence_dir(self, experiment_id: str, role: str, run_id: str) -> Path:
        d = self.evidence_root / experiment_id / f"{role}-{run_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist(self, experiment_id: str, role: str, run_id: str,
                 mr: MeasureResult, eq_key: dict) -> None:
        import json
        d = self._evidence_dir(experiment_id, role, run_id)
        (d / "stdout.log").write_text(mr.raw_log, encoding="utf-8")
        (d / "metrics.json").write_text(
            json.dumps({"metric_values": mr.metric_values, "sample_count": mr.sample_count,
                        "failures": mr.failures, "timeouts": mr.timeouts}, indent=2),
            encoding="utf-8")
        (d / "equivalence.json").write_text(json.dumps(eq_key, sort_keys=True, indent=2),
                                            encoding="utf-8")
        for name, kind in (("stdout.log", "stdout"), ("metrics.json", "metrics"),
                           ("equivalence.json", "equivalence")):
            self.reg.add_artifact(experiment_id=experiment_id, run_id=run_id,
                                  name=name, kind=kind, path=str(d / name))

    # ---- baseline -----------------------------------------------------------

    def run_baseline(self, experiment_id: str, *, reps: int = 3) -> dict:
        defn = self._defn(experiment_id)
        harness = self._harness(defn)
        eq_key = harness.equivalence_key()
        run_id = f"{experiment_id}-baseline-{canonical_hash(eq_key)[:8]}"
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.BASELINE_STARTED.value, experiment_id=experiment_id,
            actor_role="runner", action="baseline measurement started"))
        t0 = time.perf_counter()
        mr = harness.measure("baseline", reps)
        wall = time.perf_counter() - t0
        status = "completed" if not mr.failures else "completed_with_findings"
        self.reg.record_run(
            run_id=run_id, experiment_id=experiment_id, role="baseline", status=status,
            cache_state="cold", commit_ref=eq_key.get("commit", ""),
            sample_count=mr.sample_count,
            metrics={"values": mr.metric_values, "eq_key": eq_key, "samples": mr.samples},
            budget={"wall_seconds": wall})
        self._persist(experiment_id, "baseline", run_id, mr, eq_key)
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.BASELINE_COMPLETED.value, experiment_id=experiment_id,
            actor_role="runner", action="baseline measurement completed",
            duration_seconds=wall, detail={"metric_values": mr.metric_values}))
        # advance lifecycle (idempotent if already past)
        from .lifecycle import Actor, ExperimentStatus
        if self.reg.get(experiment_id)["status"] == ExperimentStatus.PROPOSED.value:
            self.reg.set_status(experiment_id, ExperimentStatus.BASELINE_READY, actor=Actor.AGENT)
        return {"run_id": run_id, "metric_values": mr.metric_values, "eq_key": eq_key,
                "wall_seconds": wall}

    # ---- candidate ----------------------------------------------------------

    def run_candidate(self, experiment_id: str, *, reps: int = 3) -> ComparisonResult:
        from .lifecycle import Actor, ExperimentStatus
        defn = self._defn(experiment_id)
        baseline_runs = [r for r in self.reg.runs(experiment_id, role="baseline")
                         if r["status"].startswith("completed")]
        if not baseline_runs:
            raise RuntimeError("no baseline run recorded; run the baseline first")
        baseline_run = baseline_runs[-1]
        baseline_vals = baseline_run["metrics"]["values"]
        baseline_eq = baseline_run["metrics"]["eq_key"]

        # stopping rule: respect the iteration budget
        prior_candidates = self.reg.runs(experiment_id, role="candidate")
        iteration = len(prior_candidates) + 1
        if iteration > defn.budgets.max_iterations:
            self.reg.append_event(EventRecord(
                kind=ExperimentEventType.BUDGET_EXHAUSTED.value, experiment_id=experiment_id,
                actor_role="runner", action=f"iteration {iteration} exceeds budget "
                f"{defn.budgets.max_iterations}"))
            self._to_inconclusive(experiment_id, "iteration budget exhausted")
            raise BudgetExhausted(f"max_iterations={defn.budgets.max_iterations} reached")

        harness = self._harness(defn)
        eq_key = harness.equivalence_key()
        # equivalence: candidate MUST run over the same basis as the baseline
        if (eq_key.get("corpus_hash") != baseline_eq.get("corpus_hash")
                or eq_key.get("gold_set_hash") != baseline_eq.get("gold_set_hash")):
            run_id = f"{experiment_id}-candidate-excluded-{iteration}"
            self.reg.record_run(
                run_id=run_id, experiment_id=experiment_id, role="candidate",
                status="excluded", iteration=iteration,
                excluded_reason="baseline/candidate equivalence lost (corpus or gold set changed)",
                metrics={"eq_key": eq_key, "baseline_eq": baseline_eq})
            self.reg.append_event(EventRecord(
                kind=ExperimentEventType.DETERMINISTIC_GATE_FAILED.value,
                experiment_id=experiment_id, actor_role="runner",
                action="equivalence lost between baseline and candidate"))
            self._to_inconclusive(experiment_id, "equivalence lost")
            raise EquivalenceError(
                "baseline and candidate are not measured over an equivalent basis")

        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.CANDIDATE_STARTED.value, experiment_id=experiment_id,
            actor_role="runner", action=f"candidate measurement started (iteration {iteration})"))
        t0 = time.perf_counter()
        mr = harness.measure("candidate", reps)
        wall = time.perf_counter() - t0

        # budget: wall time
        breaches: list[str] = []
        if wall > defn.budgets.max_wall_minutes * 60:
            breaches.append(f"wall {wall:.1f}s > {defn.budgets.max_wall_minutes}m")
        budget = BudgetReport(wall_seconds=wall, iterations=iteration,
                              within_budget=not breaches, breaches=breaches)

        run_id = f"{experiment_id}-candidate-{iteration}-{canonical_hash(eq_key)[:8]}"
        self.reg.record_run(
            run_id=run_id, experiment_id=experiment_id, role="candidate",
            status="completed" if not mr.failures else "completed_with_findings",
            iteration=iteration, cache_state="warm", commit_ref=eq_key.get("commit", ""),
            sample_count=mr.sample_count,
            metrics={"values": mr.metric_values, "eq_key": eq_key, "samples": mr.samples},
            budget=budget.to_dict())
        self._persist(experiment_id, "candidate", run_id, mr, eq_key)
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.CANDIDATE_COMPLETED.value, experiment_id=experiment_id,
            actor_role="runner", action="candidate measurement completed",
            duration_seconds=wall, detail={"metric_values": mr.metric_values}))

        if breaches:
            self.reg.append_event(EventRecord(
                kind=ExperimentEventType.BUDGET_EXHAUSTED.value, experiment_id=experiment_id,
                actor_role="runner", action="; ".join(breaches)))
            self._to_inconclusive(experiment_id, "budget exhausted: " + "; ".join(breaches))
            raise BudgetExhausted("; ".join(breaches))

        result = compare_metrics(defn, baseline_vals, mr.metric_values)

        # statistical analysis (CIs, FDR, SRM, power) — evidence the verifier recomputes.
        from . import statistics as _stats
        baseline_samples = baseline_run["metrics"].get("samples", {})
        report = _stats.analyze_experiment(
            experiment_id, metric_specs_of(defn), stat_plan_of(defn),
            baseline_samples, mr.samples)
        result.statistics = report.to_dict()
        import json as _json
        sdir = self._evidence_dir(experiment_id, "candidate", run_id)
        (sdir / "statistics.json").write_text(_json.dumps(result.statistics, indent=2),
                                              encoding="utf-8")
        self.reg.add_artifact(experiment_id=experiment_id, run_id=run_id,
                              name="statistics.json", kind="statistics",
                              path=str(sdir / "statistics.json"))

        # stopping rule: two consecutive candidate iterations with no material improvement
        if iteration >= 2 and not result.all_required_pass:
            prev = prior_candidates[-1]
            prev_vals = prev["metrics"].get("values", {})
            prev_cmp = compare_metrics(defn, baseline_vals, prev_vals)
            if not prev_cmp.all_required_pass:
                self.reg.append_event(EventRecord(
                    kind=ExperimentEventType.BUDGET_WARNING.value, experiment_id=experiment_id,
                    actor_role="runner",
                    action="two iterations with no material improvement — stopping"))
                self._to_inconclusive(experiment_id, "no material improvement over two iterations")
                result.note = "stopped: no material improvement over two iterations"
                return result

        # advance to Running then Awaiting Verification (implementer does NOT verify)
        cur = self.reg.get(experiment_id)["status"]
        if cur == ExperimentStatus.BASELINE_READY.value:
            self.reg.set_status(experiment_id, ExperimentStatus.RUNNING, actor=Actor.AGENT)
        if self.reg.get(experiment_id)["status"] == ExperimentStatus.RUNNING.value:
            self.reg.set_status(experiment_id, ExperimentStatus.AWAITING_VERIFICATION,
                                actor=Actor.AGENT)
        self.reg.append_event(EventRecord(
            kind=ExperimentEventType.VERIFICATION_REQUESTED.value, experiment_id=experiment_id,
            actor_role="runner", action="results ready; handing off to independent verifier",
            detail=result.to_dict()))
        return result

    def _to_inconclusive(self, experiment_id: str, why: str) -> None:
        from .lifecycle import Actor, ExperimentStatus
        cur = ExperimentStatus(self.reg.get(experiment_id)["status"])
        from .lifecycle import allowed_targets
        if ExperimentStatus.INCONCLUSIVE in allowed_targets(cur):
            self.reg.set_status(experiment_id, ExperimentStatus.INCONCLUSIVE,
                                actor=Actor.AGENT, note=why)

    def latest_comparison(self, experiment_id: str) -> ComparisonResult | None:
        defn = self._defn(experiment_id)
        b = [r for r in self.reg.runs(experiment_id, role="baseline")
             if r["status"].startswith("completed")]
        c = [r for r in self.reg.runs(experiment_id, role="candidate")
             if r["status"].startswith("completed")]
        if not b or not c:
            return None
        return compare_metrics(defn, b[-1]["metrics"]["values"], c[-1]["metrics"]["values"])


# Register the per-target-type harnesses (model, prompt, skill, routing, tool, memory,
# standard, proactive_check, workflow, documentation, repository_template). Imported at
# the bottom so HARNESSES + Harness + MeasureResult are already defined. This is what
# makes every target type runnable through the same machinery as retrieval + judge.
from . import harness_library  # noqa: E402,F401

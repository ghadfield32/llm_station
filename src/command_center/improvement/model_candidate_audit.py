"""Isolated live candidate model audit.

This is a bounded evidence runner for one role, one incumbent, and one candidate.
It is not the promotion path: it writes to an isolated audit Ledger/evidence
location and records whether the candidate can be measured and independently
verified under an explicit evaluated context.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from command_center.improvement import model_baselines
from command_center.improvement.live_model_benchmark import TARGET_REF
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.schema import (
    BudgetDefinition,
    ExperimentDefinition,
    MetricDefinition,
    PostWatchDefinition,
    PromotionDefinition,
    TargetType,
    VerificationDefinition,
)
from command_center.improvement.verifier import IndependentVerifier
from command_center.registry import vram
from command_center.schemas.base import RiskTier

DEFAULT_DB_PATH = Path("generated/model-candidate-audit-ledger.db")
DEFAULT_EVIDENCE_ROOT = Path("generated/model-candidate-audit-evidence")
DEFAULT_SUMMARY_PATH = Path("generated/model-candidate-audit-summary.json")


def _resolve_context(*, baseline_model: str, candidate_model: str, base_url: str,
                     context_length: int | None, fit_ctx: int | None,
                     gpu_budget_gb: float | None) -> tuple[int, dict[str, dict]]:
    if context_length is not None:
        if context_length < 1:
            raise RuntimeError("context_length must be >= 1")
        return context_length, {}
    if fit_ctx is None or fit_ctx < 1:
        raise RuntimeError("fit_ctx is required when context_length is not provided")
    if gpu_budget_gb is None or gpu_budget_gb <= 0:
        raise RuntimeError("gpu_budget_gb is required when context_length is not provided")
    models = [baseline_model, candidate_model]
    fit = {
        model: vram.estimate_installed(
            model,
            ctx=fit_ctx,
            budget_gb=gpu_budget_gb,
            base_url=base_url,
        ).to_dict()
        for model in models
    }
    return min(record["max_ctx_fits"] for record in fit.values()), fit


def _audit_metrics(role: str) -> list[MetricDefinition]:
    suite = model_baselines._load_suites().suites[role]
    policy = suite.metric_policy
    metrics: list[MetricDefinition] = []
    for name in policy.primary:
        metrics.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=True,
            baseline_source=f"isolated live {role} candidate audit baseline",
            candidate_source=f"isolated live {role} candidate audit candidate",
            minimum_improvement=0.0,
            maximum_regression=0.0,
        ))
    for name in policy.hard_non_regression:
        metrics.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=True,
            safety=True,
            baseline_source=f"isolated live {role} candidate audit baseline",
            candidate_source=f"isolated live {role} candidate audit candidate",
            maximum_regression=0.0,
        ))
    for name in policy.supporting:
        metrics.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=False,
            baseline_source=f"isolated live {role} candidate audit baseline",
            candidate_source=f"isolated live {role} candidate audit candidate",
        ))
    return metrics


def build_definition(*, role: str, baseline_model: str, candidate_model: str,
                     base_url: str | None, base_url_env: str | None,
                     evaluated_context: int, fit_evidence: dict[str, dict],
                     reps: int) -> ExperimentDefinition:
    suites = model_baselines._load_suites()
    if role not in suites.suites:
        raise RuntimeError(f"configs/model-benchmarks.yaml has no suite for role {role!r}")
    suite = suites.suites[role]
    params: dict[str, Any] = {
        "role": role,
        "suite": role,
        "baseline_model": baseline_model,
        "candidate_model": candidate_model,
        "suite_path": model_baselines.SUITE_PATH.as_posix(),
        "context_length": evaluated_context,
    }
    if base_url:
        params["base_url"] = base_url
        endpoint_arg = f"--base-url {base_url}"
    elif base_url_env:
        params["base_url_env"] = base_url_env
        endpoint_arg = f"--base-url-env {base_url_env}"
    else:
        raise RuntimeError("model candidate audit requires base_url or base_url_env")
    experiment_id = f"EXP-model-candidate-audit-{role}-{candidate_model.replace(':', '-')}"
    cases = len(suite.cases)
    wall_minutes = max(10, (cases * reps * suites.defaults.timeout_seconds + 59) // 60)
    return ExperimentDefinition(
        experiment_id=experiment_id,
        title=f"Audit {role} incumbent against {candidate_model}",
        owner="model-candidate-audit-runner",
        target_type=TargetType.MODEL,
        target_ref=TARGET_REF,
        problem_statement=(
            "Measure whether a scored local candidate works in the live harness at "
            "an explicit evaluated context."
        ),
        hypothesis=(
            "The candidate may be useful only for the audited role/context; this "
            "audit does not promote, canary, or edit routing."
        ),
        baseline=f"{role} incumbent {baseline_model}",
        candidate=f"audit-only candidate {candidate_model} at context {evaluated_context}",
        parameters={
            "audit_only": True,
            "fit_evidence": fit_evidence,
            "model_benchmark": params,
        },
        risk_tier=RiskTier.L2,
        automated=True,
        metrics=_audit_metrics(role),
        budgets=BudgetDefinition(
            max_iterations=1,
            max_wall_minutes=wall_minutes,
            max_input_tokens=0,
            max_output_tokens=suites.defaults.num_predict * cases * reps,
            max_cost_usd=0,
            max_gpu_hours=wall_minutes / 60,
            max_changed_files=0,
            max_diff_lines=0,
        ),
        verification=VerificationDefinition(
            reproduce_commands=[
                (
                    "python -m command_center.improvement.model_candidate_audit "
                    f"--role {role} --baseline-model {baseline_model} "
                    f"--candidate-model {candidate_model} --reps {reps} "
                    f"--context-length {evaluated_context} {endpoint_arg}"
                )
            ],
            required_evidence=[
                "raw redacted baseline and candidate stdout logs",
                "metric summaries with samples",
                "equivalence metadata artifacts",
                "independent verifier report artifact",
            ],
        ),
        promotion=PromotionDefinition(),
        post_watch=PostWatchDefinition(
            monitored_metrics=suite.metric_policy.primary + suite.metric_policy.hard_non_regression,
            rollback_triggers=[
                "audit-only experiment cannot promote; canary rollback belongs to a separate human-approved experiment"
            ],
        ),
    )


def run_candidate_audit(*, role: str, baseline_model: str, candidate_model: str,
                        base_url: str | None, base_url_env: str | None,
                        reps: int, context_length: int | None,
                        fit_ctx: int | None, gpu_budget_gb: float | None,
                        db_path: Path = DEFAULT_DB_PATH,
                        evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
                        summary_path: Path = DEFAULT_SUMMARY_PATH) -> dict[str, Any]:
    if reps < 1:
        raise RuntimeError("model candidate audit reps must be >= 1")
    resolved_base_url = base_url
    if resolved_base_url is None and base_url_env:
        import os
        resolved_base_url = os.environ.get(base_url_env)
    if not resolved_base_url:
        raise RuntimeError("model candidate audit requires a resolvable base URL")
    evaluated_context, fit_evidence = _resolve_context(
        baseline_model=baseline_model,
        candidate_model=candidate_model,
        base_url=resolved_base_url,
        context_length=context_length,
        fit_ctx=fit_ctx,
        gpu_budget_gb=gpu_budget_gb,
    )
    if db_path.exists():
        db_path.unlink()
    if evidence_root.exists():
        shutil.rmtree(evidence_root)
    evidence_root.mkdir(parents=True, exist_ok=True)
    defn = build_definition(
        role=role,
        baseline_model=baseline_model,
        candidate_model=candidate_model,
        base_url=base_url,
        base_url_env=base_url_env,
        evaluated_context=evaluated_context,
        fit_evidence=fit_evidence,
        reps=reps,
    )
    reg = ExperimentRegistry(db_path=str(db_path))
    reg.register(defn, mission_id=None)
    runner = ExperimentRunner(reg, repo_root=".", evidence_root=evidence_root)
    summary: dict[str, Any] = {
        "experiment_id": defn.experiment_id,
        "db_path": str(db_path),
        "evidence_root": str(evidence_root),
        "evaluated_context": evaluated_context,
        "fit_evidence": fit_evidence,
    }
    try:
        started = time.perf_counter()
        baseline = runner.run_baseline(defn.experiment_id, reps=reps)
        comparison = runner.run_candidate(defn.experiment_id, reps=reps)
        verdict = IndependentVerifier(
            reg,
            repo_root=".",
            evidence_root=evidence_root,
        ).verify(
            defn.experiment_id,
            verifier_identity="independent-local-audit-verifier",
            implementer_identity="model-candidate-audit-runner",
            reps=reps,
        )
        summary.update({
            "status": "completed",
            "wall_seconds": time.perf_counter() - started,
            "baseline": baseline,
            "comparison": comparison.to_dict(),
            "verifier": verdict.to_dict(),
        })
    except Exception as exc:
        summary.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    summary["runs"] = reg.runs(defn.experiment_id)
    summary["artifacts"] = reg.artifacts(defn.experiment_id)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--baseline-model", required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--reps", type=int, required=True)
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--base-url", default="")
    endpoint.add_argument("--base-url-env", default="")
    context = parser.add_mutually_exclusive_group(required=True)
    context.add_argument("--context-length", type=int)
    context.add_argument("--derive-context-from-fit", action="store_true")
    parser.add_argument("--fit-ctx", type=int)
    parser.add_argument("--gpu-budget-gb", type=float)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY_PATH))
    args = parser.parse_args()
    summary = run_candidate_audit(
        role=args.role,
        baseline_model=args.baseline_model,
        candidate_model=args.candidate_model,
        base_url=args.base_url or None,
        base_url_env=args.base_url_env or None,
        reps=args.reps,
        context_length=args.context_length,
        fit_ctx=args.fit_ctx if args.derive_context_from_fit else None,
        gpu_budget_gb=args.gpu_budget_gb if args.derive_context_from_fit else None,
        db_path=Path(args.db_path),
        evidence_root=Path(args.evidence_root),
        summary_path=Path(args.summary),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Register and run live incumbent model baselines.

This is intentionally separate from candidate A/B experiments. It reads the
current role incumbents from configs/models.yaml, reads suites and metric
directions from configs/model-benchmarks.yaml, and records baseline-only runs in
the Ledger. It never selects a challenger, canary, or promotion.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import yaml

from command_center.improvement.live_model_benchmark import TARGET_REF
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.schema import (
    BudgetDefinition,
    ExperimentDefinition,
    MetricDefinition,
    ModelBenchmarksConfig,
    PostWatchDefinition,
    PromotionDefinition,
    TargetType,
    VerificationDefinition,
)
from command_center.schemas import ModelRegistry
from command_center.schemas.base import RiskTier

MODELS_PATH = Path("configs/models.yaml")
SUITE_PATH = Path("configs/model-benchmarks.yaml")
SUMMARY_PATH = Path("generated/model-baseline-summary.json")


def _load_models(path: Path = MODELS_PATH) -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_suites(path: Path = SUITE_PATH) -> ModelBenchmarksConfig:
    return ModelBenchmarksConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _incumbent(registry: ModelRegistry, role: str):
    candidates = registry.roles.get(role)
    if not candidates:
        raise RuntimeError(f"configs/models.yaml has no role {role!r}")
    return sorted(candidates, key=lambda c: c.priority)[0]


def _budget(config: ModelBenchmarksConfig, suite, reps: int) -> BudgetDefinition:
    cases = len(suite.cases)
    seconds = cases * reps * config.defaults.timeout_seconds
    wall_minutes = max(1, math.ceil(seconds / 60))
    return BudgetDefinition(
        max_iterations=reps,
        max_wall_minutes=wall_minutes,
        max_input_tokens=0,
        max_output_tokens=config.defaults.num_predict * cases * reps,
        max_cost_usd=0,
        max_gpu_hours=wall_minutes / 60,
        max_changed_files=0,
        max_diff_lines=0,
    )


def _metrics(suite) -> list[MetricDefinition]:
    policy = suite.metric_policy
    definitions: list[MetricDefinition] = []
    for name in policy.primary:
        definitions.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=True,
            baseline_source=f"live incumbent baseline suite {suite.role}",
            candidate_source="future candidate A/B experiment on the same suite",
        ))
    for name in policy.hard_non_regression:
        definitions.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=True,
            safety=True,
            baseline_source=f"live incumbent baseline suite {suite.role}",
            candidate_source="future candidate A/B experiment on the same suite",
            maximum_regression=0.0,
        ))
    for name in policy.supporting:
        definitions.append(MetricDefinition(
            name=name,
            direction=policy.directions[name],
            required=False,
            baseline_source=f"live incumbent baseline suite {suite.role}",
            candidate_source="future candidate A/B experiment on the same suite",
        ))
    return definitions


def build_definition(*, role: str, base_url: str | None, base_url_env: str | None,
                     reps: int) -> ExperimentDefinition:
    registry = _load_models()
    suites = _load_suites()
    if role not in suites.suites:
        raise RuntimeError(f"configs/model-benchmarks.yaml has no suite for role {role!r}")
    suite = suites.suites[role]
    incumbent = _incumbent(registry, role)
    params: dict[str, Any] = {
        "role": role,
        "suite": role,
        "baseline_model": incumbent.model,
        "candidate_model": "__NO_CHALLENGER_SELECTED__",
        "suite_path": SUITE_PATH.as_posix(),
    }
    if base_url:
        params["base_url"] = base_url
        endpoint_arg = f"--base-url {base_url}"
    elif base_url_env:
        params["base_url_env"] = base_url_env
        endpoint_arg = f"--base-url-env {base_url_env}"
    else:
        raise RuntimeError("model baseline requires base_url or base_url_env")

    return ExperimentDefinition(
        experiment_id=f"EXP-model-baseline-{role}",
        title=f"Incumbent live model baseline for {role}",
        owner="model-baseline-runner",
        target_type=TargetType.MODEL,
        target_ref=TARGET_REF,
        problem_statement=(
            f"Collect a live baseline distribution for the current {role} incumbent "
            "before evaluating challengers."
        ),
        hypothesis=(
            "The incumbent baseline captures role-specific quality, safety, and "
            "runtime metrics without selecting or promoting a challenger."
        ),
        baseline=f"{role} incumbent {incumbent.model} ({incumbent.alias})",
        candidate="No challenger selected; this experiment is baseline-only.",
        parameters={
            "model_benchmark": params,
            "baseline_reps": reps,
            "incumbent_alias": incumbent.alias,
            "incumbent_license": incumbent.license,
            "incumbent_priority": incumbent.priority,
        },
        risk_tier=RiskTier.L2,
        automated=True,
        metrics=_metrics(suite),
        budgets=_budget(suites, suite, reps),
        verification=VerificationDefinition(
            reproduce_commands=[
                (
                    "python -m command_center.improvement.model_baselines "
                    f"--roles {role} --reps {reps} {endpoint_arg} --apply"
                )
            ],
            required_evidence=[
                "raw redacted baseline logs",
                "metric summary with sample count",
                "equivalence metadata artifact",
            ],
        ),
        promotion=PromotionDefinition(),
        post_watch=PostWatchDefinition(
            monitored_metrics=suite.metric_policy.primary + suite.metric_policy.hard_non_regression,
            rollback_triggers=[
                "baseline-only experiment has no rollback trigger; challenger experiments define rollback"
            ],
        ),
    )


def run_baselines(*, roles: list[str], base_url: str | None, base_url_env: str | None,
                  reps: int, apply: bool, summary_path: Path = SUMMARY_PATH) -> dict:
    if reps < 1:
        raise RuntimeError("model baseline reps must be >= 1")
    registry_cfg = _load_models()
    suite_cfg = _load_suites()
    selected = roles or [role for role in registry_cfg.roles if role in suite_cfg.suites]
    missing = [role for role in selected if role not in suite_cfg.suites]
    if missing:
        raise RuntimeError(f"no benchmark suite for role(s): {missing}")

    reg = ExperimentRegistry()
    runner = ExperimentRunner(reg, repo_root=".")
    results: list[dict[str, Any]] = []
    for role in selected:
        defn = build_definition(role=role, base_url=base_url, base_url_env=base_url_env, reps=reps)
        existing = reg.get(defn.experiment_id)
        if not apply:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "dry_run",
            })
            continue
        if existing is None:
            reg.register(defn, mission_id=None)
        elif not reg.runs(defn.experiment_id, role="baseline"):
            pass
        else:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "skipped_existing_baseline",
            })
            continue
        try:
            out = runner.run_baseline(defn.experiment_id, reps=reps)
        except Exception as exc:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
        else:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "baseline_recorded",
                "run_id": out["run_id"],
                "metric_values": out["metric_values"],
                "equivalence": out["eq_key"],
                "wall_seconds": out["wall_seconds"],
            })
    summary = {"applied": apply, "reps": reps, "roles": results}
    if apply:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", nargs="*", default=[])
    parser.add_argument("--reps", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base-url", default="")
    group.add_argument("--base-url-env", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    args = parser.parse_args()

    summary = run_baselines(
        roles=args.roles,
        base_url=args.base_url or None,
        base_url_env=args.base_url_env or None,
        reps=args.reps,
        apply=args.apply,
        summary_path=Path(args.summary),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if any(r["status"] == "failed" for r in summary["roles"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

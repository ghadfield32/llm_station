"""Isolated live-model metric audit.

This runner is for deeper verification of the benchmark machinery itself. It
uses the real live_model_benchmark harness and real local Ollama endpoint, but
writes to an isolated audit Ledger/evidence directory so repeated audit passes
do not mutate the production experiment Ledger or bypass the promotion path.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

from command_center.improvement import model_baselines
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner

DEFAULT_DB_PATH = Path("generated/model-metric-audit-ledger.db")
DEFAULT_EVIDENCE_ROOT = Path("generated/model-metric-audit-evidence")
DEFAULT_SUMMARY_PATH = Path("generated/model-metric-audit-summary.json")


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and math.isfinite(float(value))


def _expected_metric(name: str, samples: list[float]) -> float:
    if name.startswith("median_"):
        return float(statistics.median(samples))
    return float(statistics.mean(samples))


def _artifact_text(reg: ExperimentRegistry, experiment_id: str, run_id: str,
                   kind: str) -> tuple[Path, str]:
    matches = [
        Path(artifact["path"]) for artifact in reg.artifacts(experiment_id)
        if artifact["run_id"] == run_id and artifact["kind"] == kind
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"{experiment_id} run {run_id} expected exactly one {kind} artifact, "
            f"found {len(matches)}"
        )
    path = matches[0]
    return path, path.read_text(encoding="utf-8")


def _check_run(*, reg: ExperimentRegistry, role: str, run: dict, reps: int,
               base_url: str | None, base_url_env: str | None) -> dict[str, Any]:
    suites = model_baselines._load_suites()
    suite = suites.suites[role]
    expected_samples = len(suite.cases) * reps
    metrics = run["metrics"]
    values = metrics.get("values")
    samples = metrics.get("samples")
    eq_key = metrics.get("eq_key")
    if not isinstance(values, dict) or not isinstance(samples, dict):
        raise RuntimeError(f"{role} run {run['run_id']} has no metric values/samples")
    if not isinstance(eq_key, dict):
        raise RuntimeError(f"{role} run {run['run_id']} has no equivalence key")
    if run["sample_count"] != expected_samples:
        raise RuntimeError(
            f"{role} expected sample_count={expected_samples}, observed {run['sample_count']}"
        )

    checks: dict[str, Any] = {
        "sample_count": run["sample_count"],
        "expected_sample_count": expected_samples,
        "metric_checks": {},
    }
    for name, value in values.items():
        if not _finite(value):
            raise RuntimeError(f"{role} metric {name!r} is not finite: {value!r}")
        raw_samples = samples.get(name)
        if raw_samples is None:
            continue
        if not isinstance(raw_samples, list) or not raw_samples:
            raise RuntimeError(f"{role} metric {name!r} has empty/non-list samples")
        if not all(_finite(sample) for sample in raw_samples):
            raise RuntimeError(f"{role} metric {name!r} has non-finite samples")
        expected = _expected_metric(name, [float(sample) for sample in raw_samples])
        if not math.isclose(float(value), expected, rel_tol=1e-9, abs_tol=1e-9):
            raise RuntimeError(
                f"{role} metric {name!r} value {value!r} does not match samples {expected!r}"
            )
        checks["metric_checks"][name] = {
            "value": value,
            "sample_count": len(raw_samples),
        }

    stdout_path, stdout = _artifact_text(reg, run["experiment_id"], run["run_id"], "stdout")
    metrics_path, _ = _artifact_text(reg, run["experiment_id"], run["run_id"], "metrics")
    equivalence_path, equivalence = _artifact_text(
        reg, run["experiment_id"], run["run_id"], "equivalence")
    for case in suite.cases:
        if case.prompt in stdout:
            raise RuntimeError(f"{role} stdout artifact leaks raw prompt for case {case.id}")
    forbidden_log_markers = ("prompt=", "response=", "output=", "raw_output=")
    for marker in forbidden_log_markers:
        if marker in stdout:
            raise RuntimeError(f"{role} stdout artifact contains raw transcript marker {marker}")
    if base_url and base_url in equivalence:
        raise RuntimeError(f"{role} equivalence artifact leaks direct base_url")
    if base_url_env and base_url_env in equivalence:
        raise RuntimeError(f"{role} equivalence artifact leaks base_url_env name")
    checks["artifacts"] = {
        "stdout": str(stdout_path),
        "metrics": str(metrics_path),
        "equivalence": str(equivalence_path),
    }
    checks["metric_values"] = values
    checks["failures"] = json.loads(metrics_path.read_text(encoding="utf-8")).get("failures", [])
    return checks


def run_audit(*, roles: list[str], base_url: str | None, base_url_env: str | None,
              reps: int, db_path: Path = DEFAULT_DB_PATH,
              evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
              summary_path: Path = DEFAULT_SUMMARY_PATH) -> dict[str, Any]:
    if reps < 1:
        raise RuntimeError("model metric audit reps must be >= 1")
    registry_cfg = model_baselines._load_models()
    suite_cfg = model_baselines._load_suites()
    selected = roles or [role for role in registry_cfg.roles if role in suite_cfg.suites]
    missing = [role for role in selected if role not in suite_cfg.suites]
    if missing:
        raise RuntimeError(f"no benchmark suite for role(s): {missing}")

    if db_path.exists():
        db_path.unlink()
    if evidence_root.exists():
        for path in sorted(evidence_root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)

    reg = ExperimentRegistry(db_path=str(db_path))
    runner = ExperimentRunner(reg, repo_root=".", evidence_root=evidence_root)
    results: list[dict[str, Any]] = []
    for role in selected:
        defn = model_baselines.build_definition(
            role=role,
            base_url=base_url,
            base_url_env=base_url_env,
            reps=reps,
        )
        reg.register(defn, mission_id=None)
        try:
            out = runner.run_baseline(defn.experiment_id, reps=reps)
            run = reg.runs(defn.experiment_id, role="baseline")[-1]
            checks = _check_run(
                reg=reg,
                role=role,
                run=run,
                reps=reps,
                base_url=base_url,
                base_url_env=base_url_env,
            )
        except Exception as exc:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "audit_failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
        else:
            results.append({
                "role": role,
                "experiment_id": defn.experiment_id,
                "incumbent_model": defn.parameters["model_benchmark"]["baseline_model"],
                "status": "audit_passed",
                "run_id": out["run_id"],
                "wall_seconds": out["wall_seconds"],
                **checks,
            })
    summary = {
        "reps": reps,
        "db_path": str(db_path),
        "evidence_root": str(evidence_root),
        "roles": results,
    }
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
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--evidence-root", default=str(DEFAULT_EVIDENCE_ROOT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY_PATH))
    args = parser.parse_args()
    summary = run_audit(
        roles=args.roles,
        base_url=args.base_url or None,
        base_url_env=args.base_url_env or None,
        reps=args.reps,
        db_path=Path(args.db_path),
        evidence_root=Path(args.evidence_root),
        summary_path=Path(args.summary),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if any(role["status"] == "audit_failed" for role in summary["roles"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

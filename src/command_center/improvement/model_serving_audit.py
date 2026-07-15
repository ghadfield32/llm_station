"""Run one bounded live serving-SLO audit for a local model.

This is the operator entry point over ``serving_load_driver``. It reads the
committed workload sizes, concurrency sweep, and SLOs from
``configs/model-serving-benchmarks.yaml``; sends synthetic prompts only; and
writes measurement evidence under ``generated/`` by default. It never edits
``configs/models.yaml``, changes routing, starts a canary, or promotes a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from command_center.improvement import serving_load_driver
from command_center.schemas import ServingBenchmarksConfig

CONFIG_PATH = Path("configs/model-serving-benchmarks.yaml")
DEFAULT_OUTPUT = Path("generated/model-serving-audit-summary.json")


def _load_config(path: Path) -> ServingBenchmarksConfig:
    return ServingBenchmarksConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def run_serving_audit(
    *,
    model: str,
    scenario_name: str,
    base_url: str,
    config_path: Path = CONFIG_PATH,
    output_path: Path = DEFAULT_OUTPUT,
    measure_factory: Callable[..., Callable] = serving_load_driver.build_measure_fn,
    sweep_runner: Callable[..., dict] = serving_load_driver.sweep_and_operating_point,
) -> dict[str, Any]:
    """Measure one configured p90 workload and persist an honest pass/fail record."""
    if not model.strip():
        raise RuntimeError("model serving audit requires a non-empty model tag")
    if not base_url.strip():
        raise RuntimeError("model serving audit requires an explicit local base URL")

    config = _load_config(config_path)
    if scenario_name not in config.scenarios:
        raise RuntimeError(
            f"unknown serving scenario {scenario_name!r}; "
            f"choose from {sorted(config.scenarios)}"
        )
    scenario = config.scenarios[scenario_name]
    measure = measure_factory(
        model,
        input_tokens=scenario.input_tokens_p90,
        output_tokens=scenario.output_tokens_p90,
        base_url=base_url,
    )
    measurement = sweep_runner(
        measure,
        scenario_name,
        concurrency_points=list(config.concurrency_sweep),
        slo_p90_ttft_s=scenario.slo_p90_ttft_seconds,
        slo_p90_ttlt_s=scenario.slo_p90_ttlt_seconds,
    )
    passed = bool(measurement["operating_point"]["found"])
    summary: dict[str, Any] = {
        "schema_version": "command-center.model-serving-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "model": model,
        "scenario": scenario_name,
        "endpoint_sha256": hashlib.sha256(base_url.encode("utf-8")).hexdigest(),
        "workload": {
            "input_tokens": scenario.input_tokens_p90,
            "output_tokens": scenario.output_tokens_p90,
            "percentile": "p90",
        },
        "slos": {
            "p90_ttft_seconds": scenario.slo_p90_ttft_seconds,
            "p90_ttlt_seconds": scenario.slo_p90_ttlt_seconds,
            "max_error_rate": 0.0,
        },
        "measurement": measurement,
        "routing_changed": False,
        "promotion_allowed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="installed local Ollama tag")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--base-url", required=True, help="explicit local Ollama base URL")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    summary = run_serving_audit(
        model=args.model,
        scenario_name=args.scenario,
        base_url=args.base_url,
        config_path=Path(args.config),
        output_path=Path(args.output),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

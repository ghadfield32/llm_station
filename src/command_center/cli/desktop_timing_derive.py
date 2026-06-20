"""Derive provisional desktop timing candidates from no-op canary evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import AutonomyConfig

ROOT = Path(__file__).resolve().parents[3]


def _load_evidence(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def derive_timing_candidates(
    *,
    evidence_paths: list[Path],
    output: Path | None = None,
    target_id: str,
    required_samples: int | None = None,
    required_samples_source: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if required_samples is None or not required_samples_source:
        blockers.append("sample_plan_missing")
        blockers.append("insufficient_noop_canary_telemetry")
    elif required_samples < 1:
        blockers.append("sample_plan_required_samples_invalid")

    samples: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in evidence_paths:
        if not path.is_file():
            rejected.append({"path": str(path), "reason": "evidence_missing"})
            continue
        data = _load_evidence(path)
        if data.get("target_id") != target_id:
            rejected.append({"path": str(path), "reason": "target_id_mismatch"})
            continue
        if data.get("status") != "pass":
            rejected.append({"path": str(path), "reason": "status_not_pass"})
            continue
        if data.get("allowed_mode") != "read_only":
            rejected.append({"path": str(path), "reason": "mode_not_read_only"})
            continue
        measurements = data.get("measurements") or {}
        required_measurements = [
            "snapshot_load_ms",
            "target_verify_ms",
            "total_duration_ms",
        ]
        if any(measurements.get(field) is None for field in required_measurements):
            rejected.append({"path": str(path), "reason": "measurement_missing"})
            continue
        samples.append({"path": str(path), "measurements": measurements})

    if required_samples is not None and len(samples) < required_samples:
        blockers.append("insufficient_noop_canary_telemetry")

    candidates = None
    if not blockers:
        max_total_ms = max(float(sample["measurements"]["total_duration_ms"]) for sample in samples)
        max_action_ms = max(
            max(
                float(sample["measurements"]["snapshot_load_ms"]),
                float(sample["measurements"]["target_verify_ms"]),
            )
            for sample in samples
        )
        candidates = {
            "ttl_minutes_candidate": max_total_ms / 60_000,
            "action_timeout_seconds_candidate": max_action_ms / 1_000,
            "candidate_source_evidence_refs": [sample["path"] for sample in samples],
            "candidate_basis": "max observed read-only no-op canary timing; no safety multiplier",
            "provisional_only_not_production_enabled": True,
        }

    result = {
        "schema_version": "command-center.desktop-timing-candidates.v1",
        "target_id": target_id,
        "status": "proposed" if candidates else "blocked",
        "blockers": blockers,
        "observed_sample_count": len(samples),
        "required_sample_count": required_samples,
        "required_sample_count_source": required_samples_source,
        "additional_samples_required": (
            max(required_samples - len(samples), 0)
            if required_samples is not None
            else None
        ),
        "required_sample_type": "read_only desktop-noop-canary evidence",
        "rejected_evidence": rejected,
        "candidates": candidates,
        "production_values_written": False,
        "desktop_target_enabled": False,
        "placeholder_values_used": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def derive_timing_candidates_from_config(
    *,
    config_path: Path,
    root: Path,
    target_id: str,
    evidence_paths: list[Path] | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    cfg = AutonomyConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    plan = next((item for item in cfg.desktop_timing_sample_plans if item.target_id == target_id), None)
    if plan is None:
        result = derive_timing_candidates(
            evidence_paths=evidence_paths or [],
            output=output,
            target_id=target_id,
        )
        result["sample_plan"] = None
        return result

    planned_paths = []
    planned_ref_by_path: dict[str, str] = {}
    for ref in plan.required_evidence_refs:
        path = Path(ref)
        if not path.is_absolute():
            path = root / path
        planned_paths.append(path)
        planned_ref_by_path[str(path)] = ref
    result = derive_timing_candidates(
        evidence_paths=_dedupe_paths([*planned_paths, *(evidence_paths or [])]),
        output=None,
        target_id=target_id,
        required_samples=len(plan.required_evidence_refs),
        required_samples_source=plan.required_sample_count_source,
    )
    result["sample_plan"] = {
        "status": plan.status,
        "source_work_item": plan.source_work_item,
        "sample_plan_basis": plan.sample_plan_basis,
        "required_evidence_refs": plan.required_evidence_refs,
        "required_sample_count_source": plan.required_sample_count_source,
        "candidate_derivation": plan.candidate_derivation,
        "live_actions_allowed": plan.live_actions_allowed,
        "production_enabling": plan.production_enabling,
    }
    if result.get("candidates"):
        result["candidates"]["candidate_source_evidence_refs"] = [
            planned_ref_by_path.get(ref, ref)
            for ref in result["candidates"]["candidate_source_evidence_refs"]
        ]
    result["rejected_evidence"] = [
        {
            **item,
            "path": planned_ref_by_path.get(str(item.get("path")), str(item.get("path"))),
        }
        for item in result["rejected_evidence"]
    ]
    result["placeholder_values_used"] = False
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _paths_from_args(args) -> list[Path]:
    paths = [Path(item) for item in args.input]
    if args.input_dir:
        paths.extend(sorted(Path(args.input_dir).glob("*.json")))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-timing-derive")
    parser.add_argument("--config", default="configs/autonomy.yaml")
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--required-samples", type=int, default=None)
    parser.add_argument("--required-samples-source", default="")
    parser.add_argument(
        "--output",
        default="evaluation/system-validation/20260616-autonomy-contracts/desktop-timing-candidates.json",
    )
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if args.required_samples is None and not args.required_samples_source:
        result = derive_timing_candidates_from_config(
            config_path=(ROOT / args.config).resolve(),
            root=ROOT,
            evidence_paths=_paths_from_args(args),
            output=output,
            target_id=args.target_id,
        )
    else:
        result = derive_timing_candidates(
            evidence_paths=_paths_from_args(args),
            output=output,
            target_id=args.target_id,
            required_samples=args.required_samples,
            required_samples_source=args.required_samples_source or None,
        )
    print(f"desktop-timing-derive: {result['status'].upper()}")
    for blocker in result.get("blockers", []):
        print(f"  BLOCKED: {blocker}")
    print(f"evidence -> {args.output}")
    return 0 if result["status"] == "proposed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

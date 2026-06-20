"""Derive provisional desktop timing candidates from no-op canary evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


def _load_evidence(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _paths_from_args(args) -> list[Path]:
    paths = [Path(item) for item in args.input]
    if args.input_dir:
        paths.extend(sorted(Path(args.input_dir).glob("*.json")))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(prog="desktop-timing-derive")
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
    result = derive_timing_candidates(
        evidence_paths=_paths_from_args(args),
        output=(ROOT / args.output).resolve(),
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

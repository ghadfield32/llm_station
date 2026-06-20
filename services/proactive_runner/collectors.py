"""Evidence collectors for proactive checks.

A proactive check declares the evidence it needs (configs/proactive.yaml, each
check's `evidence:` list). This registry maps an evidence key to a function that
gathers the REAL value for a given check/target.

The contract is deliberately strict: there are NO placeholders. A check whose
declared evidence is not fully backed by registered collectors is skipped by the
runner (see app.run_check) — it never asks a judge to rule on fabricated data,
and never opens a mission off a guess. This is the difference between "we don't
know yet" (skip, honestly) and "everything looks broken" (a fake verdict that
the old `f"<{key} for {target}>"` placeholder produced).

To activate a check: register a collector for each of its evidence keys here.
The moment all of a check's keys are wired, the runner starts judging it for
real with zero other changes.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

# evidence_key -> collector(check: dict) -> JSON-serialisable evidence value.
# Empty by default: until a key is wired here, any check needing it is skipped.
COLLECTORS: dict[str, Callable[[dict], object]] = {}


def collector(key: str) -> Callable[[Callable[[dict], object]], Callable[[dict], object]]:
    """Decorator: register `fn` as the collector for evidence `key`."""
    def register(fn: Callable[[dict], object]) -> Callable[[dict], object]:
        COLLECTORS[key] = fn
        return fn
    return register


def collect_evidence(check: dict) -> tuple[dict, list[str]]:
    """Gather real evidence for a check.

    Returns (evidence, unwired):
      - evidence: only keys that have a registered collector, with real values.
      - unwired:  declared evidence keys with no collector. If this is non-empty
                  the runner skips the check rather than fabricate the missing
                  pieces — we do not judge partial/fake evidence.
    """
    evidence: dict = {}
    unwired: list[str] = []
    for key in check.get("evidence", []):
        fn = COLLECTORS.get(key)
        if fn is None:
            unwired.append(key)
        else:
            evidence[key] = fn(check)
    return evidence, unwired


AIRFLOW_SNAPSHOT_KEYS = (
    "dag_runs",
    "task_logs",
    "changed_files",
    "output_partitions",
    "deterministic_checks",
)
AIRFLOW_SNAPSHOT_SCHEMA = "command-center.airflow-evidence.v1"
SECRET_FIELD_NAMES = frozenset({
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "token",
})


def _safe_segment(value: object) -> str:
    if value is None:
        raise ValueError("airflow snapshot collector requires check.target")
    raw = str(value).strip()
    if not raw:
        raise ValueError("airflow snapshot collector requires non-empty check.target")
    text = re.sub(r"[^a-z0-9_.-]+", "-", raw.lower()).strip("-")
    if not text:
        raise ValueError(f"airflow snapshot target {raw!r} has no safe path segment")
    return text


def _read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _normalize_field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _assert_no_secret_fields(value: object, path: str = "data") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalize_field_name(key)
            if normalized in SECRET_FIELD_NAMES:
                raise ValueError(f"Airflow snapshot contains secret-bearing field {path}.{key}")
            _assert_no_secret_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_secret_fields(nested, f"{path}[{index}]")


def _snapshot_data(path: Path) -> object:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Airflow snapshot must be a JSON object")
    if payload.get("schema_version") != AIRFLOW_SNAPSHOT_SCHEMA:
        raise ValueError(
            f"Airflow snapshot schema_version must be {AIRFLOW_SNAPSHOT_SCHEMA!r}"
        )
    if payload.get("redaction_status") != "redacted":
        raise ValueError("Airflow snapshot redaction_status must be 'redacted'")
    if "data" not in payload:
        raise ValueError("Airflow snapshot must contain a data field")
    _assert_no_secret_fields(payload["data"])
    return payload["data"]


def _snapshot_candidates(root: Path, target: str, key: str) -> list[Path]:
    return [
        root / target / f"{key}.json",
        root / f"{target}-{key}.json",
    ]


def _snapshot_ref(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("airflow snapshot path escaped evidence root") from exc


def _airflow_snapshot(key: str, check: dict) -> dict:
    """Read Airflow evidence captured by a separate, credentialed collector.

    The proactive runner stays secret-free. It only consumes redacted JSON
    snapshots mounted through PROACTIVE_AIRFLOW_EVIDENCE_DIR, which keeps Airflow
    API tokens and database credentials out of this service.
    """
    root_value = os.environ.get("PROACTIVE_AIRFLOW_EVIDENCE_DIR", "")
    if not root_value:
        raise RuntimeError("PROACTIVE_AIRFLOW_EVIDENCE_DIR is not configured")
    root = Path(root_value)
    if not root.is_dir():
        raise RuntimeError("PROACTIVE_AIRFLOW_EVIDENCE_DIR is not a directory")
    target = _safe_segment(check.get("target"))
    searched = _snapshot_candidates(root, target, key)
    for path in searched:
        if path.is_file():
            return {
                "status": "available",
                "collector": "airflow_snapshot",
                "key": key,
                "target": target,
                "evidence_ref": _snapshot_ref(root, path),
                "snapshot_schema": AIRFLOW_SNAPSHOT_SCHEMA,
                "data": _snapshot_data(path),
            }
    searched_refs = ", ".join(_snapshot_ref(root, path) for path in searched)
    raise FileNotFoundError(
        f"Airflow snapshot evidence {key!r} for target {target!r} was not found; "
        f"searched {searched_refs}"
    )


def _register_airflow_snapshot_collectors() -> None:
    if not os.environ.get("PROACTIVE_AIRFLOW_EVIDENCE_DIR"):
        return
    for key in AIRFLOW_SNAPSHOT_KEYS:
        def _make(snapshot_key: str):
            @collector(snapshot_key)
            def _collect(check: dict) -> dict:
                return _airflow_snapshot(snapshot_key, check)
            return _collect
        _make(key)


_register_airflow_snapshot_collectors()

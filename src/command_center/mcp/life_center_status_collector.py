"""Life Center status collector — the "privileged short-lived collector" from
docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md. Runs `lc.py verify --json`
against the currently-admitted tiers, reduces it to the redacted shapes
``life_center_status.py``'s MCP tools serve, and atomically writes a snapshot
JSON file. No Docker socket, no root, no mutation — a subprocess call to
life-center-infra's own CLI (never a Python import; see that module's README
for why life-center-infra stays a separate boundary) plus a plain file write.

Scheduled externally (Windows Task Scheduler during the trial; a systemd
timer on the eventual Debian host) — this script holds no scheduler logic
itself, matching the plan's "fixed checks only... writes a snapshot... exits."

A failed run leaves the prior snapshot in place rather than overwriting good
data with an empty one — a collector outage must read as "stale", never as
"everything is healthy."

    python -m command_center.mcp.life_center_status_collector [--profile everything]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LC_PY = _REPO_ROOT / "life-center-infra" / "lc.py"

DEFAULT_SNAPSHOT_PATH = "generated/life-center-status-snapshot.json"

# ServiceHealth.status is healthy | attention | down | maintenance (see
# life_center_status.py); Overview only has services_healthy/services_attention
# buckets, so "down" folds into "attention" there but stays distinct per-service.
_STATUS_MAP = {"pass": "healthy", "warn": "attention", "fail": "down"}


def run_lc(*args: str) -> dict:
    """Subprocess boundary into life-center-infra/lc.py — never a Python import
    (see life-center-infra/README.md: it is a self-contained seed meant to be
    extracted into its own private repo; importing its modules here would
    couple the two repos at exactly the boundary that's meant to stay clean)."""
    if not _LC_PY.exists():
        raise FileNotFoundError(f"lc.py not found at {_LC_PY}")
    proc = subprocess.run(
        [sys.executable, str(_LC_PY), *args],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return json.loads(proc.stdout)


def build_snapshot(report: dict) -> dict:
    """Reduce one `lc verify --json` VerificationReport to the redacted shapes
    life_center_status.py serves. Describes only the CURRENT run — never
    claims a check passed that this run did not actually execute."""
    by_service: dict[str, list[dict]] = {}
    for c in report["checks"]:
        sid = c.get("service_id")
        if sid:
            by_service.setdefault(sid, []).append(c)

    services = []
    healthy = attention = 0
    for sid, checks in sorted(by_service.items()):
        statuses = {c["status"] for c in checks}
        overall = "fail" if "fail" in statuses else "warn" if statuses - {"pass"} else "pass"
        status = _STATUS_MAP[overall]
        if status == "healthy":
            healthy += 1
        else:
            attention += 1
        services.append({"service": sid, "status": status, "last_check": report["generated_at"]})

    return {
        "schema_version": "life-center.status-snapshot.v1",
        "generated_at": report["generated_at"],
        "source_verify_schema_version": report["schema_version"],
        "catalog_digest": report.get("catalog_digest"),
        "overview": {
            "generated_at": report["generated_at"],
            "services_total": len(services),
            "services_healthy": healthy,
            "services_attention": attention,
            # NOT yet automated by `lc verify` (see its own "not_automated:*"
            # checks) — stay honestly zeroed, never fabricated, until a real
            # backup/storage/security probe exists to back these.
            "oldest_backup_age_hours": 0.0,
            "pool_used_pct": 0.0,
            "open_security_findings": 0,
        },
        "services": services,
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="everything")
    parser.add_argument("--out", default=os.environ.get(
        "LIFE_CENTER_STATUS_SNAPSHOT", DEFAULT_SNAPSHOT_PATH))
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / out_path

    try:
        report = run_lc("verify", "--profile", args.profile, "--json")
    except Exception as exc:  # noqa: BLE001 - a failed run must not corrupt a good snapshot
        print(f"[life-center-status-collector] run failed, leaving prior snapshot "
              f"in place: {exc}", file=sys.stderr)
        return 1

    snapshot = build_snapshot(report)
    _atomic_write_json(out_path, snapshot)
    print(f"[life-center-status-collector] wrote {out_path} "
          f"({snapshot['overview']['services_total']} services, "
          f"{snapshot['overview']['services_healthy']} healthy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

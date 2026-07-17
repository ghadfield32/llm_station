"""cc assistant-doctor — does the running agent worker match this checkout?

The 2026-07-17 incident: an agent session failed mid-chat with
'AutonomyConfig research_capabilities Extra inputs are not permitted' because
the running WORKER (and later the cockpit container) held a stale contract
while reading a newer config. This command surfaces that BEFORE a session
fails: it fetches the worker's /api/runtime-fingerprint and compares it to the
HOST checkout, reporting a plain verdict per the plan's prevention item.

Read-only: one authenticated GET to the local worker; computes the host
fingerprint locally. Exit 0 = healthy, 1 = drift/unreachable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from command_center.agent_sessions.fingerprint import compute_fingerprint

_DEFAULT_WORKER = os.environ.get("AGENT_WORKER_URL", "http://127.0.0.1:8791")
_ROOT = Path(__file__).resolve().parents[3]


def _worker_fingerprint(base_url: str, token: str, timeout: float) -> dict:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/runtime-fingerprint",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-url", default=_DEFAULT_WORKER)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--release", action="store_true",
                        help="production-acceptance mode: a dirty working tree "
                             "(non-reproducible build) is a hard FAIL")
    args = parser.parse_args(argv)

    host = compute_fingerprint(_ROOT)
    token = os.environ.get("AGENT_WORKER_TOKEN", "")
    checks: list[tuple[str, bool, str]] = []

    # 1. host self-consistency: does THIS checkout's contract validate its config?
    checks.append((
        "host_autonomy_validates", host["autonomy_validates"],
        host.get("autonomy_validation_error")
        or "host contract validates configs/autonomy.yaml"))

    # 1b. reproducibility: a dirty working tree means the running build is NOT
    # from a committed SHA (release-stabilization §1). WARNING, not a hard fail —
    # surfaced so a dirty-tree deployment is visible, never silent.
    dirty = host.get("git_dirty")
    checks.append((
        "host_tree_committed", dirty is False,
        f"working tree at {host.get('git_sha')} is committed (reproducible)"
        if dirty is False else
        f"working tree is DIRTY at {host.get('git_sha')} — the running build is "
        f"not from a committed SHA; commit + rebuild for a reproducible release"))

    worker: dict | None = None
    if not token:
        checks.append(("worker_reachable", False,
                       "AGENT_WORKER_TOKEN not set — cannot query the worker"))
    else:
        try:
            worker = _worker_fingerprint(args.worker_url, token, args.timeout)
            checks.append(("worker_reachable", True,
                           f"worker at {args.worker_url} responded"))
        except Exception as exc:
            checks.append(("worker_reachable", False,
                           f"worker unreachable: {type(exc).__name__}: {exc}"))

    if worker is not None:
        # 2. the drift the incident was about: worker's own contract must
        #    validate its own config (False = the worker is stale -> restart)
        checks.append((
            "worker_autonomy_validates", worker.get("autonomy_validates", False),
            worker.get("autonomy_validation_error")
            or "worker contract validates its on-disk autonomy.yaml"))
        # 3. worker and host see the SAME config bytes (mount/version match)
        same = worker.get("config_sha256") == host["config_sha256"]
        checks.append((
            "worker_config_matches_host", same,
            "worker and host tracked-config SHA-256s match" if same
            else "worker config bytes differ from host — check the mount/version"))
        # 4. same source checkout (git SHA) — a mismatch means one is stale
        git_match = worker.get("git_sha") == host.get("git_sha")
        checks.append((
            "worker_git_matches_host",
            bool(worker.get("git_sha")) and git_match,
            f"worker git_sha={worker.get('git_sha')} host={host.get('git_sha')}"))

    # `host_tree_committed` is ADVISORY by default (a dirty tree is normal during
    # dev) and only GATES under --release (the production-acceptance rule §1/§12).
    _ADVISORY = {"host_tree_committed"}
    ok = all(passed for cid, passed, _ in checks
             if args.release or cid not in _ADVISORY)
    if args.json:
        print(json.dumps({
            "overall": "pass" if ok else "fail",
            "release_mode": args.release, "host": host, "worker": worker,
            "checks": [{"id": i, "status": "pass" if p else "fail",
                        "advisory": (i in _ADVISORY and not args.release),
                        "detail": d} for i, p, d in checks]}, indent=2))
    else:
        for cid, passed, detail in checks:
            advisory = cid in _ADVISORY and not args.release
            tag = "WARN" if (advisory and not passed) else ("PASS" if passed else "FAIL")
            print(f"[{tag:4}] {cid:28} {detail}")
        print(f"\nassistant-doctor: {'PASS' if ok else 'FAIL'}"
              f"{' (release mode)' if args.release else ''}")
        if not ok and worker and not worker.get("autonomy_validates", True):
            print("  -> worker contract does not match the active checkout; "
                  "restart it: scripts/start_agent_worker.ps1 restart")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())

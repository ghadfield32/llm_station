"""Sync life-center-infra catalog + verification into Command Center Kanban.

Runs the three Life Center syncs once end-to-end:

  catalog → life_center_services (admission cards) + life_center_operations
            (first-run setup tasks)
  verify  → life_center_overview (health projection, cards move lanes each run)

  python -m command_center.cli.life_center_sync                 # everything profile
  python -m command_center.cli.life_center_sync --profile core  # verify a subset

Prints one line per board (created/updated counts) and exits 0, or 1 on any hard
failure (a non-zero lc.py exit that isn't `verify`'s expected fail, invalid JSON,
or a board write error).

Invoked by a scheduler — Windows Task Scheduler during the desktop trial, a
systemd timer once the real host exists — deliberately NOT wired into Airflow:
life-center-infra is a self-contained seed destined for its own private repo and
must not hard-depend on this repo's Airflow instance (matching its own boundary).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from command_center.improvement.discovery.life_center import (
    command_center_operations_binder,
    command_center_overview_binder,
    command_center_services_binder,
    run_lc,
)


def _counts(results: list[dict]) -> tuple[int, int]:
    created = sum(1 for r in results if r.get("action") == "created")
    updated = sum(1 for r in results if r.get("action") == "updated")
    return created, updated


def run_sync(*, verify_profile: str = "everything") -> dict:
    """Run all three syncs against the live boards. `verify_profile` selects which
    APP tiers `lc verify` health-checks; the catalog (services/operations) is
    always the full, profile-independent service set.

    `lc verify --profile everything` deliberately excludes the `foundation`
    tier (lc.py's ALL_APP_TIERS = every tier except foundation — a compose
    bring-up distinction, not a health-check one), so Uptime Kuma and Restic
    would otherwise never get an Overview card and would sit at "unknown"
    forever even though they're running. Run verify twice and merge the
    checks so Overview covers everything that actually exists.
    """
    catalog = run_lc("catalog")  # `catalog` always emits JSON; it rejects --json
    services = catalog["services"]
    catalog_digest = catalog["catalog_digest"]

    services_result = command_center_services_binder()(services, catalog_digest)
    operations_result = command_center_operations_binder()(services)

    # verify exits 1 when overall == "fail" (a routine unhealthy-service case we
    # must sync, not a crash) yet still prints a valid report — tolerate exit 1.
    verify = run_lc("verify", "--profile", verify_profile, "--json",
                    allowed_returncodes=(0, 1))
    foundation_verify = run_lc("verify", "--profile", "foundation", "--json",
                               allowed_returncodes=(0, 1))
    all_checks = verify["checks"] + foundation_verify["checks"]
    generated_at = max(verify["generated_at"], foundation_verify["generated_at"])
    overview_result = command_center_overview_binder()(all_checks, generated_at)

    return {
        "life_center_services": services_result,
        "life_center_operations": operations_result,
        "life_center_overview": overview_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="life-center-sync")
    parser.add_argument(
        "--profile", default="everything",
        help="tier profile for `lc verify` health checks (default: everything)")
    args = parser.parse_args(argv)

    try:
        results = run_sync(verify_profile=args.profile)
    except subprocess.CalledProcessError as exc:
        print(f"life-center-sync: FAILED — lc.py exited {exc.returncode} "
              f"for {' '.join(exc.cmd[2:]) if len(exc.cmd) > 2 else exc.cmd}",
              file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return 1
    except (ValueError, KeyError, OSError) as exc:
        # invalid JSON (ValueError/json.JSONDecodeError), a missing expected key,
        # or a board/IO write error — fail hard rather than half-sync silently.
        print(f"life-center-sync: FAILED — {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    for board, rows in results.items():
        created, updated = _counts(rows)
        print(f"{board}: {created} created, {updated} updated ({len(rows)} cards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

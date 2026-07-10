#!/usr/bin/env python3
"""CLI for the frontier-router backup lane — read-only previews, no live egress.

Standalone (not wired into the main `cc` app) so the lane stays clearly separate from the
local control plane. Two subcommands:

  dry-run     preview the cost + policy verdict of a router call (makes NO request)
  price-audit flag provider prices older than price_freshness.max_age_days (never overwrites)

Invoke via `make frontier-router-dry-run` / `make frontier-router-price-audit`, or directly:
  python -m command_center.cli.frontier_router dry-run --model glm-5.2 --input-tokens 120000 ...
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from command_center.improvement.frontier_router_eval import dry_run_report, load_providers
from command_center.improvement.router_price_audit import audit_prices


def _dry_run(args: argparse.Namespace) -> int:
    report = dry_run_report(
        model_id=args.model, provider=args.provider, input_tokens=args.input_tokens,
        output_tokens=args.output_tokens, task_class=args.task_class,
        cached_input_tokens=args.cached_input_tokens)
    print(json.dumps(report, indent=2))
    return 0


def _price_audit(args: argparse.Namespace) -> int:
    today = args.today or datetime.now(timezone.utc).date().isoformat()
    report = audit_prices(load_providers(), today=today)
    print(json.dumps(report.to_dict(), indent=2))
    # A stale price under a `fail` policy is a hard non-zero exit; `warn_in_scan` stays 0.
    if report.verdict == "stale" and report.stale_action == "fail":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frontier-router")
    sub = parser.add_subparsers(dest="command", required=True)

    dr = sub.add_parser("dry-run", help="preview router cost + policy (no live call)")
    dr.add_argument("--model", required=True)
    dr.add_argument("--provider", default=None, help="omit to pick the cheapest eligible")
    dr.add_argument("--input-tokens", type=int, required=True)
    dr.add_argument("--output-tokens", type=int, required=True)
    dr.add_argument("--cached-input-tokens", type=int, default=0)
    dr.add_argument("--task-class", default="frontier_reference_eval")
    dr.set_defaults(func=_dry_run)

    pa = sub.add_parser("price-audit", help="flag stale provider prices")
    pa.add_argument("--today", default=None, help="ISO date override (default: today UTC)")
    pa.set_defaults(func=_price_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

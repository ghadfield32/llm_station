#!/usr/bin/env python3
"""
knowledge — generate and validate the observer-only OKF knowledge bundle.

  python -m command_center.cli.knowledge generate [--out knowledge] [--now ISO]
  python -m command_center.cli.knowledge validate [--bundle knowledge] [--root .]

`generate` reads authoritative sources (configs, the Ledger, docs, code, DAGs) and writes a
`knowledge/` bundle of `derived` OKF concepts — it never modifies a source. `validate` is the
blocking N/N PASS gate.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone


def cmd_generate(args) -> int:
    from command_center.knowledge.bundle import generate_bundle
    now = args.now or datetime.now(timezone.utc).isoformat()
    res = generate_bundle(".", now_iso=now, out_dir=args.out)
    print(f"knowledge generate: {res.n_concepts} concepts -> {res.out_dir}/ (at {now})")
    for section, n in res.by_section.items():
        if n:
            print(f"  {section:16s} {n}")
    return 0


def cmd_validate(args) -> int:
    from command_center.knowledge.validate import run_gate
    now = datetime.now(timezone.utc).isoformat()
    return 0 if run_gate(args.bundle, args.root, now_iso=now) else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="knowledge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.set_defaults(func=cmd_generate)
    g.add_argument("--out", default="knowledge")
    g.add_argument("--now", default="", help="ISO timestamp (default: now; injectable for reproducibility)")
    v = sub.add_parser("validate")
    v.set_defaults(func=cmd_validate)
    v.add_argument("--bundle", default="knowledge")
    v.add_argument("--root", default=".")
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

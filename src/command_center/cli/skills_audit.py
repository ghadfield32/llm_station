#!/usr/bin/env python3
"""`cc skills-audit` — surface dependency-shipped Agent Library Skills (read-only).

FastAPI, Typer, SQLModel and friends now ship a version-matched `.agents/skills/<name>/
SKILL.md` inside their installed package. This command inventories them so they are visible
and shows whether the repo already surfaces each one. It writes NOTHING — no install, no
symlink, no copy. Actually surfacing/installing a skill is a separate, gated step
(L3, security-scanned, project-scope-only) and is intentionally not done here.

    cc skills-audit            # human table
    cc skills-audit --json     # machine-readable inventory
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from command_center.skills import discover_skills, render_table

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    ap = argparse.ArgumentParser(prog="skills-audit")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--search-path", action="append", default=None,
                    help="extra directory to search (repeatable; default: the installed env)")
    args = ap.parse_args()

    search_paths = [Path(p) for p in args.search_path] if args.search_path else None
    records = discover_skills(search_paths=search_paths, repo_root=ROOT)

    if args.json:
        print(json.dumps([r.to_dict() for r in records], indent=2))
    else:
        print(render_table(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())

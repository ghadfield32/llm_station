#!/usr/bin/env python3
"""Render standards.yaml into the files executors actually read."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from command_center.schemas import StandardsConfig


def render(profile_name: str) -> str:
    cfg = StandardsConfig.model_validate(yaml.safe_load(open("configs/standards.yaml")))
    profile = next((p for p in cfg.profiles if p.name == profile_name), None)
    if profile is None:
        raise SystemExit(f"unknown profile '{profile_name}' — defined: {[p.name for p in cfg.profiles]}")
    lines = ["# Engineering standards (rendered from command-center configs/standards.yaml — edit THERE)", ""]
    lines += ["## Core principles", ""] + [f"- {p}" for p in cfg.core_principles]
    lines += ["", f"## Profile: {profile.name}", ""] + [f"- {p}" for p in profile.principles]
    if profile.blocked_patterns:
        lines += ["", "## Never (the defensive-coding judge blocks these)", ""] + [f"- {b}" for b in profile.blocked_patterns]
    if profile.allowed_patterns:
        lines += ["", "## Explicitly fine", ""] + [f"- {a}" for a in profile.allowed_patterns]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("outdir")
    args = parser.parse_args()

    text = render(args.profile)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for fname in ("CLAUDE.md", "AGENTS.md"):
        (outdir / fname).write_text(text, encoding="utf-8")
    print(f"wrote {outdir / 'CLAUDE.md'} and {outdir / 'AGENTS.md'} (profile: {args.profile})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

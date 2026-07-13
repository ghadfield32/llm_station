#!/usr/bin/env python3
"""
model_ops.py — operator surface over the model roster (configs/models.yaml).

Flat `cc` commands that wrap the existing registry/render flow so the whole
model lifecycle is reachable without remembering Makefile targets:

  cc model-status                  # show the roster: roles, candidates, active/scout, canary
  cc model-canary --role coder --model ollama_chat/qwen3-coder:30b [--weight 0.1] [--apply]
  cc model-promote --role coder --candidate <alias> --approver YOU [--apply]

`cc model-scout` (propose candidates) and `cc model-fit` (VRAM/context fit) keep
their existing modules — this module only adds the missing status/canary/promote
verbs. The human wall is preserved: promotion requires an explicit --approver and
--apply; nothing here auto-promotes. scout candidates are a watchlist (tracked but
not routed); promotion flips a scout candidate to active in models.yaml.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from command_center.schemas import ModelRegistry

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "configs" / "models.yaml"
CANARY_EVIDENCE_DIR = ROOT / "evaluation" / "model-canaries"


def _load_registry(path: Path = MODELS) -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# ── status ───────────────────────────────────────────────────────────

def run_status(*, path: Path = MODELS) -> dict[str, Any]:
    """Read-only roster: every role, its candidates, status, and canary weight."""
    reg = _load_registry(path)
    roles = []
    for role, cands in reg.roles.items():
        ordered = sorted(cands, key=lambda c: c.priority)
        roles.append({
            "role": role,
            "candidates": [
                {
                    "alias": c.alias,
                    "model": c.model,
                    "priority": c.priority,
                    "status": c.status,
                    "canary_weight": c.canary_weight,
                    "vram_gb": c.vram_gb,
                    "license": c.license,
                    "api_base_env": c.api_base_env,
                }
                for c in ordered
            ],
        })
    return {
        "status": "ok",
        "roles": roles,
        "active_total": sum(
            1 for cands in reg.roles.values() for c in cands if c.status == "active"
        ),
        "scout_total": sum(
            1 for cands in reg.roles.values() for c in cands if c.status == "scout"
        ),
    }


def _print_status(result: dict[str, Any]) -> None:
    for r in result["roles"]:
        print(f"\n{r['role']}:")
        for c in r["candidates"]:
            flags = [c["status"]]
            if c["canary_weight"]:
                flags.append(f"canary~{int(c['canary_weight'] * 100)}%")
            vram = f"{c['vram_gb']}GB" if c["vram_gb"] else "?GB"
            print(f"  [{','.join(flags):<14}] p{c['priority']} {c['alias']:<18} "
                  f"{c['model']:<20} {vram:<6} {c['license'] or ''}")
    print(f"\nactive={result['active_total']}  scout={result['scout_total']}")


# ── canary ───────────────────────────────────────────────────────────

def run_canary(
    *, role: str, model: str, weight: float = 0.1, apply: bool = False,
    path: Path = MODELS, root: Path = ROOT,
) -> dict[str, Any]:
    """Render a local canary for a role. Local-only: model must be ollama_chat/...

    Dry-run (default) validates and reports the render/restart steps. --apply runs
    render so generated/litellm-config.yaml carries the canary; serving it still
    requires restarting litellm (`cc up` / compose restart litellm) — left to the
    operator since it needs the running stack.
    """
    blockers: list[str] = []
    reg = _load_registry(path)
    if role not in reg.roles:
        blockers.append(f"unknown role '{role}' (roles: {', '.join(reg.roles)})")
    if not model.startswith("ollama_chat/"):
        blockers.append("canary model must be local-only and start with ollama_chat/")
    if not (0.0 < weight <= 1.0):
        blockers.append(f"weight {weight} out of range (0, 1]")
    render_cmd = [sys.executable, "-m", "command_center.registry.render",
                  "--canary", f"{role}={model}:{weight}"]
    if blockers:
        return {"status": "blocked", "role": role, "model": model, "weight": weight,
                "blockers": blockers, "applied": False, "render_cmd": render_cmd}
    applied = False
    if apply:
        proc = subprocess.run(render_cmd, cwd=root, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"status": "blocked", "role": role, "model": model, "weight": weight,
                    "blockers": [f"render failed: {(proc.stderr or proc.stdout).strip()}"],
                    "applied": False, "render_cmd": render_cmd}
        applied = True
    return {
        "status": "ok",
        "role": role, "model": model, "weight": weight,
        "applied": applied,
        "render_cmd": render_cmd,
        "next": "restart litellm to serve the canary: cc up  (or: docker compose restart litellm)",
        "blockers": [],
    }


# ── promote (human-gated) ─────────────────────────────────────────────

def _flip_status_to_active(text: str, alias: str) -> tuple[str, bool]:
    """Flip `status: scout` -> `status: active` on the candidate line for `alias`.

    Candidates are flow-style one-per-line dicts, so this is a targeted line edit
    that leaves every other line (and all comments) byte-identical.
    """
    out, changed = [], False
    alias_re = re.compile(rf"(^|[{{,\s])alias:\s*{re.escape(alias)}\s*(,|}}|$)")
    for line in text.splitlines(keepends=True):
        if not changed and alias_re.search(line) and "status: scout" in line:
            out.append(line.replace("status: scout", "status: active", 1))
            changed = True
        else:
            out.append(line)
    return "".join(out), changed


def run_promote(
    *, role: str, candidate: str, approver: str = "", apply: bool = False,
    path: Path = MODELS, root: Path = ROOT, now: datetime | None = None,
) -> dict[str, Any]:
    """Human-gated promotion: flip a scout candidate to active in models.yaml.

    Requires a non-empty --approver (the human wall) and --apply to write. Re-
    validates the registry after the edit and records evidence under
    evaluation/model-canaries/. Never auto-promotes.
    """
    blockers: list[str] = []
    if not approver.strip():
        blockers.append("promotion requires --approver NAME (human approval is mandatory)")
    reg = _load_registry(path)
    cands = reg.roles.get(role)
    target = None
    if cands is None:
        blockers.append(f"unknown role '{role}' (roles: {', '.join(reg.roles)})")
    else:
        target = next((c for c in cands if c.alias == candidate), None)
        if target is None:
            blockers.append(
                f"role '{role}' has no candidate '{candidate}' "
                f"(candidates: {', '.join(c.alias for c in cands)})"
            )
        elif target.status == "active":
            return {"status": "already_active", "role": role, "candidate": candidate,
                    "approver": approver, "applied": False, "blockers": []}
    if blockers:
        return {"status": "blocked", "role": role, "candidate": candidate,
                "approver": approver, "applied": False, "blockers": blockers}

    plan = {"role": role, "candidate": candidate, "from": "scout", "to": "active"}
    if not apply:
        return {"status": "dry_run", "applied": False, "approver": approver,
                "plan": plan, "blockers": [],
                "next": f"re-run with --apply to flip {candidate} to active"}

    text = path.read_text(encoding="utf-8")
    new_text, changed = _flip_status_to_active(text, candidate)
    if not changed:
        return {"status": "blocked", "role": role, "candidate": candidate,
                "approver": approver, "applied": False,
                "blockers": [f"could not find a 'status: scout' on the line for alias '{candidate}'"]}
    # Re-validate the edited registry before writing it back.
    ModelRegistry.model_validate(yaml.safe_load(new_text))
    path.write_text(new_text, encoding="utf-8")

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = root / "evaluation" / "model-canaries"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema_version": "command-center.model-promote.v1",
        "role": role, "candidate": candidate, "approver": approver,
        "from": "scout", "to": "active", "timestamp": stamp,
        "models_yaml": str(path.relative_to(root)),
    }
    ev_path = evidence_dir / f"{role}-{candidate}-promote-{stamp}.json"
    ev_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "promoted", "role": role, "candidate": candidate, "approver": approver,
        "applied": True, "evidence": str(ev_path.relative_to(root)), "blockers": [],
        "next": "render + restart litellm to route the promoted model: cc render && cc up",
    }


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="model", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show the model roster (read-only)")

    c = sub.add_parser("canary", help="render a local canary for a role")
    c.add_argument("--role", required=True)
    c.add_argument("--model", required=True, help="ollama_chat/<tag>")
    c.add_argument("--weight", type=float, default=0.1)
    c.add_argument("--apply", action="store_true", help="run render (writes generated config)")

    p = sub.add_parser("promote", help="human-gated: flip a scout candidate to active")
    p.add_argument("--role", required=True)
    p.add_argument("--candidate", required=True, help="candidate alias to promote")
    p.add_argument("--approver", default="", help="REQUIRED human approver name")
    p.add_argument("--apply", action="store_true", help="write the models.yaml flip")

    args = parser.parse_args()

    if args.cmd == "status":
        result = run_status()
        _print_status(result)
        return 0
    if args.cmd == "canary":
        result = run_canary(role=args.role, model=args.model,
                            weight=args.weight, apply=args.apply)
    else:  # promote
        result = run_promote(role=args.role, candidate=args.candidate,
                             approver=args.approver, apply=args.apply)

    print(f"model-{args.cmd}: {result['status'].upper()}")
    for b in result.get("blockers", []):
        print(f"  BLOCKED: {b}")
    if result.get("next"):
        print(f"  next: {result['next']}")
    if result.get("evidence"):
        print(f"  evidence: {result['evidence']}")
    return 0 if result["status"] in ("ok", "dry_run", "promoted", "already_active") else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Bridge GrowthOS/AppFlowy Kanban cards into Ledger missions.

Default mode is read-only dry-run. Use --apply to create Ledger missions.
The bridge intentionally does not execute code or update repos; it only opens
missions that then pass through the normal leases, risk gates, judges, and
executor flow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from command_center.schemas import KanbanConfig, RiskTier  # noqa: E402


RISK_SHORT = {
    RiskTier.L0: "L0",
    RiskTier.L1: "L1",
    RiskTier.L2: "L2",
    RiskTier.L3: "L3",
    RiskTier.L4: "L4",
}
SHORT_TO_RISK = {v: k for k, v in RISK_SHORT.items()}


@dataclass
class MissionDraft:
    card_key: str
    title: str
    section: str
    repo: str
    branch: str
    risk: str
    requires_approval: bool
    action: str
    card_pre_hash: str = ""   # CardKey cell; set for agent-created cards -> writeback


def read_yaml(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def merged_env(*env_files: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in env_files:
        values.update(read_dotenv(path))
    values.update(os.environ)
    return values


def slug(value: str, limit: int = 48) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return (text or "card")[:limit].strip("-")


def stable_card_key(cells: dict[str, Any]) -> str:
    basis = "|".join(
        str(cells.get(name, ""))
        for name in ("Name", "Title", "Section", "Target", "Action", "Acceptance")
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def cell(cells: dict[str, Any], *names: str) -> str:
    for name in names:
        value = cells.get(name)
        if value is not None and value != "":
            return str(value)
    return ""


def load_imported(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_imported(path: Path, imported: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(imported, indent=2, sort_keys=True), encoding="utf-8")


def risk_from_card(value: str, default: RiskTier) -> RiskTier:
    if not value:
        return default
    short = value.strip().upper()
    if short in SHORT_TO_RISK:
        return SHORT_TO_RISK[short]
    for risk in RiskTier:
        if value == risk.value:
            return risk
    raise ValueError(f"unsupported Risk value {value!r}; use L0, L1, L2, L3, or L4")


def approval_required(risk: RiskTier) -> bool:
    return risk in (RiskTier.L3, RiskTier.L4)


def build_drafts(rows: list[dict], cfg: KanbanConfig, imported: dict[str, str]) -> list[MissionDraft]:
    sections = {s.appflowy_section: s for s in cfg.sections}
    drafts: list[MissionDraft] = []
    for row in rows:
        cells = row.get("cells", row)
        title = cell(cells, "Title", "Name")
        section_name = cell(cells, "Section")
        status = cell(cells, "Status")
        if not title or section_name not in sections:
            continue
        section = sections[section_name]
        if status not in section.ready_statuses:
            continue
        card_key = stable_card_key(cells)
        if card_key in imported or cell(cells, "MissionID"):
            continue
        risk = risk_from_card(cell(cells, "Risk"), section.default_risk)
        repo = cell(cells, "Repo") or section.default_repo
        target = cell(cells, "Target") or section.target
        branch = cell(cells, "Branch") or f"{section.branch_prefix}/{slug(title)}"
        action_body = cell(cells, "Action") or title
        acceptance = cell(cells, "Acceptance")
        action = (
            f"{title}\n\n"
            f"Kanban section: {section.name} ({section.target_kind}:{target})\n"
            f"Requested action:\n{action_body}"
        )
        if acceptance:
            action += f"\n\nAcceptance criteria:\n{acceptance}"
        drafts.append(
            MissionDraft(
                card_key=card_key,
                title=title,
                section=section.name,
                repo=repo,
                branch=branch,
                risk=RISK_SHORT[risk],
                requires_approval=approval_required(risk),
                action=action,
                card_pre_hash=cell(cells, "CardKey"),
            )
        )
    return drafts


def open_ledger_mission(ledger_url: str, draft: MissionDraft) -> str:
    payload = {
        "action": draft.action,
        "repo": draft.repo,
        "branch": draft.branch,
        "risk": draft.risk,
        "requires_approval": draft.requires_approval,
    }
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{ledger_url.rstrip('/')}/mission", json=payload)
        r.raise_for_status()
        mission_id = r.json()["id"]
        client.post(
            f"{ledger_url.rstrip('/')}/mission/{mission_id}/event",
            json={
                "kind": "kanban_import",
                "payload": {
                    "card_key": draft.card_key,
                    "title": draft.title,
                    "section": draft.section,
                },
            },
        ).raise_for_status()
    return mission_id


def appflowy_ctx(source, env: dict[str, str]) -> dict:
    """Auth + database/field-id context for one AppFlowy source (used for both
    reading rows and stamping writeback cells, which go over the wire keyed
    by FIELD ID)."""
    root = Path(source.growthos_root)
    db_map = json.loads((root / source.database_map_path).read_text(encoding="utf-8"))
    entry = db_map[source.database]
    base = env[source.base_url_env].rstrip("/")
    with httpx.Client(timeout=30) as client:
        auth = client.post(
            f"{base}/gotrue/token?grant_type=password",
            json={"email": env[source.email_env], "password": env[source.password_env]},
        )
        auth.raise_for_status()
        token = auth.json()["access_token"]
    return {"base": base, "workspace": env[source.workspace_id_env],
            "token": token, "db_id": entry["database_id"],
            "fields": entry["fields"]}


def stamp_card(ctx: dict, card_pre_hash: str, mission_id: str) -> None:
    """Write MissionID + Status=In Progress back onto an agent-created card
    (identified by its CardKey pre_hash). UI-created cards have no CardKey;
    they are deduped by the imported-state file instead."""
    from datetime import date
    fields = ctx["fields"]
    cells = {fields["MissionID"]: mission_id,
             fields["Status"]: "In Progress",
             fields["LastSync"]: date.today().isoformat()}
    with httpx.Client(timeout=30) as client:
        r = client.put(
            f"{ctx['base']}/api/workspace/{ctx['workspace']}/database/{ctx['db_id']}/row",
            headers={"Authorization": f"Bearer {ctx['token']}"},
            json={"pre_hash": card_pre_hash, "cells": cells, "document": None},
        )
        r.raise_for_status()
        if r.json().get("code") != 0:
            raise RuntimeError(f"writeback failed: {r.text[:200]}")


def rows_from_appflowy(source, env: dict[str, str]) -> list[dict]:
    root = Path(source.growthos_root)
    base = env.get(source.base_url_env, "")
    workspace_id = env.get(source.workspace_id_env, "")
    email = env.get(source.email_env, "")
    password = env.get(source.password_env, "")
    missing = [
        name
        for name, value in (
            (source.base_url_env, base),
            (source.workspace_id_env, workspace_id),
            (source.email_env, email),
            (source.password_env, password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"missing AppFlowy env value(s): {', '.join(missing)}")
    db_map = root / source.database_map_path
    if not db_map.exists():
        raise RuntimeError(f"{db_map} not found; rerun growth-os/scripts/setup_workspace.py")
    dbs = json.loads(db_map.read_text(encoding="utf-8"))
    if source.database not in dbs:
        raise RuntimeError(f"database '{source.database}' missing from {db_map}")
    db_id = dbs[source.database]["database_id"]
    base = base.rstrip("/")
    with httpx.Client(timeout=30) as client:
        auth = client.post(
            f"{base}/gotrue/token?grant_type=password",
            json={"email": email, "password": password},
        )
        auth.raise_for_status()
        token = auth.json().get("access_token")
        if not token:
            raise RuntimeError("AppFlowy login returned no access_token")
        headers = {"Authorization": f"Bearer {token}"}
        rows = client.get(
            f"{base}/api/workspace/{workspace_id}/database/{db_id}/row",
            headers=headers,
        )
        rows.raise_for_status()
        row_ids = [x["id"] for x in rows.json()["data"]]
        if not row_ids:
            return []
        out: list[dict] = []
        for i in range(0, len(row_ids), 40):
            detail = client.get(
                f"{base}/api/workspace/{workspace_id}/database/{db_id}/row/detail",
                headers=headers,
                params={"ids": ",".join(row_ids[i:i + 40])},
            )
            detail.raise_for_status()
            out.extend(detail.json()["data"])
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/kanban.yaml")
    ap.add_argument("--source", default="")
    ap.add_argument("--apply", action="store_true", help="open Ledger missions")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    cfg = KanbanConfig.model_validate(read_yaml(args.config))
    imported_path = Path(cfg.imported_state_path)
    imported = load_imported(imported_path)

    ledger_env = merged_env(Path(".env"))
    ledger_url = ledger_env.get(cfg.ledger_base_url_env) or "http://localhost:8091"
    total = 0
    for source in cfg.sources:
        if args.source and source.name != args.source:
            continue
        if not source.enabled:
            continue
        env = merged_env(Path(".env"), Path(source.growthos_root) / ".env")
        try:
            rows = rows_from_appflowy(source, env)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            print(f"kanban-bridge: source '{source.name}' unreachable ({exc}); skipping this cycle")
            continue
        drafts = build_drafts(rows[: args.limit], cfg, imported)
        total += len(drafts)
        try:
            for draft in drafts:
                print(f"- [{draft.risk}] {draft.repo}:{draft.branch} :: {draft.title}")
                if not args.apply:
                    continue
                mission_id = open_ledger_mission(ledger_url, draft)
                imported[draft.card_key] = mission_id
                print(f"  opened {mission_id}")
                if draft.card_pre_hash:
                    ctx = appflowy_ctx(source, env)
                    stamp_card(ctx, draft.card_pre_hash, mission_id)
                    print(f"  stamped card {draft.card_pre_hash} -> In Progress")
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            print(f"kanban-bridge: Ledger unreachable ({exc}); skipping '{source.name}'")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"kanban-bridge: {mode} ({total} mission draft(s))")
    if args.apply:
        save_imported(imported_path, imported)
    elif total:
        print("dry-run only; rerun with --apply to open Ledger missions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

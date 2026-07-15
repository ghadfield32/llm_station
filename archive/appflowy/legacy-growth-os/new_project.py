"""Stamp a complete per-project kanban section in one command.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/new_project.py \
        --name nfl_models --repo nfl_models --risk L2 [--section "NFL Models"]

Does three things, idempotently (re-running with the same name is a no-op):
  1. creates `<name>_board` in AppFlowy from the `project_template` block in
     config/schema.yaml (Grid + Board view), recorded in config/databases.json
  2. appends a section to the command center's configs/kanban.yaml
     (validated against schemas.KanbanConfig before writing — fail-fast)
  3. registers the board as a bridge source database? No — the bridge reads
     mission_intake; per-project boards feed it via Section. The new section's
     `appflowy_section` value is what you put in a card's Section field.

Risk mapping: L0..L2 allowed for default_risk here; L3/L4 stay human-gated
at mission time (the contract enforces max_auto_risk <= L2).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import yaml

GROWTHOS_ROOT = Path(__file__).resolve().parent.parent
CC_ROOT = (GROWTHOS_ROOT / "../..").resolve()
sys.path.insert(0, str(GROWTHOS_ROOT))
sys.path.insert(0, str(CC_ROOT / "src"))  # command-center package now lives under src/

from growthos.config import load_settings  # noqa: E402
from setup_workspace import field_payload, find_parent_space, login  # noqa: E402

RISK_LONG = {"L0": "L0_read_only", "L1": "L1_plan_only", "L2": "L2_local_edits"}


def create_board(name: str) -> dict:
    schema = yaml.safe_load((GROWTHOS_ROOT / "config/schema.yaml")
                            .read_text(encoding="utf-8"))
    template = schema["project_template"]
    db_map_path = GROWTHOS_ROOT / "config/databases.json"
    db_map = json.loads(db_map_path.read_text())
    board = f"{name}_board"
    if board in db_map:
        print(f"{board}: already in databases.json, skipping create")
        return db_map[board]

    st = load_settings()
    base, ws = st.appflowy_base_url.rstrip("/"), st.appflowy_workspace_id
    with httpx.Client(timeout=30) as client:
        h = login(client, base, st.appflowy_email, st.appflowy_password)
        parent = find_parent_space(client, base, ws, h)
        r = client.post(f"{base}/api/workspace/{ws}/page-view", headers=h,
                        json={"parent_view_id": parent, "layout": 1, "name": board})
        r.raise_for_status()
        data = r.json()["data"]
        view_id, db_id = data["view_id"], data["database_id"]
        fields = list(template["fields"].items())
        for fname, fspec in fields[1:]:
            fr = client.post(f"{base}/api/workspace/{ws}/database/{db_id}/fields",
                             headers=h, json=field_payload(fname, fspec))
            fr.raise_for_status()
            if fr.json().get("code") != 0:
                raise RuntimeError(f"{board}.{fname}: {fr.text}")
        live = client.get(f"{base}/api/workspace/{ws}/database/{db_id}/fields",
                          headers=h).json()["data"]
        primary = next(f["id"] for f in live if f.get("is_primary"))
        fmap = {f["name"]: f["id"] for f in live}
        fmap[fields[0][0]] = primary
        vr = client.post(f"{base}/api/workspace/{ws}/page-view/{view_id}/database-view",
                         headers=h, json={"parent_view_id": view_id, "layout": 2,
                                          "name": "Board", "database_id": db_id,
                                          "embedded": False})
        vr.raise_for_status()
    entry = {"view_id": view_id, "database_id": db_id, "primary_field_id": primary,
             "title_column": fields[0][0], "fields": fmap}
    db_map[board] = entry
    db_map_path.write_text(json.dumps(db_map, indent=2))
    print(f"{board}: created view={view_id} db={db_id} (+Board view)")
    return entry


def register_section(name: str, section_label: str, repo: str, risk: str) -> None:
    kanban_path = CC_ROOT / "configs/kanban.yaml"
    cfg = yaml.safe_load(kanban_path.read_text(encoding="utf-8"))
    if any(s["name"] == name for s in cfg.get("sections", [])):
        print(f"section '{name}': already in kanban.yaml, skipping")
        return
    cfg["sections"].append({
        "name": name,
        "appflowy_section": section_label,
        "target_kind": "repo",
        "target": repo,
        "default_repo": repo,
        "default_risk": RISK_LONG[risk],
        "max_auto_risk": "L2_local_edits",
        "ready_statuses": ["Approved"],
        "done_statuses": ["Done", "Rejected"],
        "branch_prefix": f"kanban/{name.replace('_', '-')}",
    })
    from command_center.schemas import KanbanConfig  # noqa: E402  (fail-fast before writing)
    KanbanConfig.model_validate(cfg)
    kanban_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"section '{name}' -> configs/kanban.yaml (validated)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="snake_case project name")
    ap.add_argument("--repo", required=True, help="repo dir name under docker_projects")
    ap.add_argument("--risk", default="L2", choices=list(RISK_LONG))
    ap.add_argument("--section", default="", help="card Section label (default: name)")
    args = ap.parse_args()
    label = args.section or args.name.replace("_", " ").title()
    create_board(args.name)
    register_section(args.name, label, args.repo, args.risk)
    print("\nNOTE: mission_intake's Section select needs this option to exist "
          f"before cards can use it - add {label!r} to the Section options in "
          "config/schema.yaml AND on the live board (field edit in UI), or use "
          "the new board's own columns for project-local work.")


if __name__ == "__main__":
    main()

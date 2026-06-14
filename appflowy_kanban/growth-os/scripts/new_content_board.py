"""Create the LinkedIn content-calendar boards in AppFlowy from the
`content_template` block in config/schema.yaml.

One board per account (default: both):
  - geoffhadfield32_content       -> personal profile posts
  - world_model_sports_content    -> World Model Sports company-page posts

Each board is a Grid + a Board (kanban) view. The Board view groups by the
first single-select field, which is `Status` (In Queue / In Progress /
Completed) - the three columns the user asked for. Idempotent: a board already
present in config/databases.json is left untouched.

Unlike scripts/new_project.py these boards do NOT register a kanban.yaml
section - they are a content queue, not a mission-intake source. Publishing is
handled by command_center.cli.linkedin_publish, which reads these boards by the
same config/databases.json field map.

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/new_content_board.py
      (optionally  --board geoffhadfield32_content  to do just one)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import yaml

from growthos.config import load_settings
from setup_workspace import field_payload, find_parent_space, login, reconcile_fields

GROWTHOS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BOARDS = ["geoffhadfield32_content", "world_model_sports_content"]


def create_board(board: str) -> dict:
    schema = yaml.safe_load((GROWTHOS_ROOT / "config/schema.yaml")
                            .read_text(encoding="utf-8"))
    template = schema["content_template"]
    db_map_path = GROWTHOS_ROOT / "config/databases.json"
    db_map = json.loads(db_map_path.read_text())
    fields = list(template["fields"].items())

    st = load_settings()
    base, ws = st.appflowy_base_url.rstrip("/"), st.appflowy_workspace_id
    if not ws:
        raise SystemExit("APPFLOWY_WORKSPACE_ID is not set in .env")

    # Existing board: reconcile (add any missing fields, e.g. Key) in place,
    # same upgrade-safe behaviour as setup_workspace.py - never recreate.
    if board in db_map:
        db_id = db_map[board]["database_id"]
        with httpx.Client(timeout=30) as client:
            h = login(client, base, st.appflowy_email, st.appflowy_password)
            primary_id, fmap = reconcile_fields(client, base, ws, db_id, h, board, fields)
        db_map[board] = {"view_id": db_map[board]["view_id"], "database_id": db_id,
                         "primary_field_id": primary_id,
                         "title_column": fields[0][0], "fields": fmap}
        db_map_path.write_text(json.dumps(db_map, indent=2))
        print(f"{board}: exists ({db_id}), reconciled fields")
        return db_map[board]

    with httpx.Client(timeout=30) as client:
        h = login(client, base, st.appflowy_email, st.appflowy_password)
        parent = find_parent_space(client, base, ws, h)
        r = client.post(f"{base}/api/workspace/{ws}/page-view", headers=h,
                        json={"parent_view_id": parent, "layout": 1, "name": board})
        r.raise_for_status()
        data = r.json()["data"]
        view_id, db_id = data["view_id"], data["database_id"]
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
    print(f"{board}: created view={view_id} db={db_id} (+Board view, grouped by Status)")
    return entry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", action="append", choices=DEFAULT_BOARDS,
                    help="limit to one board (default: create both)")
    args = ap.parse_args()
    for board in (args.board or DEFAULT_BOARDS):
        create_board(board)
    print("\nNOTE: the Board view groups by the first single-select field (Status). "
          "If AppFlowy shows it grouped by another field, set Group by -> Status "
          "once in the UI (board grouping is not settable via REST).")


if __name__ == "__main__":
    main()

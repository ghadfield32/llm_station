"""Create or reconcile Growth OS databases in AppFlowy from config/schema.yaml.

Idempotent: the resulting name -> {view_id, database_id, fields} mapping is
persisted to config/databases.json; databases already present there are
verified and reconciled. Missing fields are added in place, so re-runs can
upgrade an existing board without recreating it.

Recipes verified against AppFlowy Cloud (self-hosted, 2026-06):
  create grid : POST /api/workspace/{ws}/page-view {parent_view_id, layout: 1, name}
                -> returns {view_id, database_id}
  add field   : POST /api/workspace/{ws}/database/{db}/fields
                {name, field_type, type_option_data}
                selects need type_option_data={"content": json.dumps({options, disable_color})}
  rows        : POST (insert) / PUT (upsert by pre_hash) .../database/{db}/row,
                cells keyed by FIELD ID; the schema's first column maps onto
                the grid's primary "Name" field (it cannot be renamed via REST).

Run:  python scripts/setup_workspace.py        (PYTHONPATH=. from repo root)
"""
from __future__ import annotations
import json
import secrets
from pathlib import Path

import httpx
import yaml

from growthos.config import load_settings

FIELD_TYPE_IDS = {
    "text": 0, "longtext": 0, "number": 1, "date": 2,
    "select": 3, "multiselect": 4, "checkbox": 5, "url": 6,
}
SELECT_COLORS = ["Purple", "Orange", "Yellow", "Green", "Blue", "Pink", "LightPink", "Aqua"]
DB_MAP_PATH = Path("config/databases.json")


def login(client: httpx.Client, base: str, email: str, password: str) -> dict:
    r = client.post(f"{base}/gotrue/token?grant_type=password",
                    json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def find_parent_space(client: httpx.Client, base: str, ws: str, h: dict) -> str:
    """First space under the workspace root (the default 'General'), else root."""
    r = client.get(f"{base}/api/workspace/{ws}/folder", params={"depth": 1}, headers=h)
    r.raise_for_status()
    root = r.json()["data"]
    for child in root.get("children", []):
        if child.get("is_space"):
            return child["view_id"]
    return root["view_id"]


def field_payload(name: str, spec) -> dict:
    if isinstance(spec, str):
        ftype, options = spec, None
    else:
        ftype, options = spec["type"], spec.get("options")
    payload = {"name": name, "field_type": FIELD_TYPE_IDS[ftype], "type_option_data": None}
    if options:
        content = {"disable_color": False, "options": [
            {"id": secrets.token_hex(3), "name": str(o),
             "color": SELECT_COLORS[i % len(SELECT_COLORS)]}
            for i, o in enumerate(options)]}
        payload["type_option_data"] = {"content": json.dumps(content)}
    return payload


def fetch_field_mapping(
    client: httpx.Client,
    base: str,
    ws: str,
    db_id: str,
    headers: dict,
    title_col: str,
) -> tuple[str, dict[str, str], list[dict]]:
    r = client.get(f"{base}/api/workspace/{ws}/database/{db_id}/fields", headers=headers)
    r.raise_for_status()
    live_fields = r.json()["data"]
    primary_id = next(f["id"] for f in live_fields if f.get("is_primary"))
    fields = {f["name"]: f["id"] for f in live_fields}
    fields[title_col] = primary_id
    return primary_id, fields, live_fields


def reconcile_fields(
    client: httpx.Client,
    base: str,
    ws: str,
    db_id: str,
    headers: dict,
    name: str,
    schema_fields: list[tuple[str, object]],
) -> tuple[str, dict[str, str]]:
    title_col = schema_fields[0][0]
    primary_id, fields, _ = fetch_field_mapping(client, base, ws, db_id, headers, title_col)
    missing = [(fname, fspec) for fname, fspec in schema_fields[1:] if fname not in fields]
    for fname, fspec in missing:
        fr = client.post(
            f"{base}/api/workspace/{ws}/database/{db_id}/fields",
            headers=headers,
            json=field_payload(fname, fspec),
        )
        fr.raise_for_status()
        if fr.json().get("code") != 0:
            raise RuntimeError(f"{name}.{fname}: {fr.text}")
        print(f"{name}.{fname}: added")
    if missing:
        primary_id, fields, _ = fetch_field_mapping(client, base, ws, db_id, headers, title_col)
    return primary_id, fields


def main() -> None:
    st = load_settings()
    base, ws = st.appflowy_base_url.rstrip("/"), st.appflowy_workspace_id
    if not ws:
        raise SystemExit("APPFLOWY_WORKSPACE_ID is not set in .env")
    schema = yaml.safe_load(Path("config/schema.yaml").read_text(encoding="utf-8"))["databases"]
    db_map = json.loads(DB_MAP_PATH.read_text()) if DB_MAP_PATH.exists() else {}

    with httpx.Client(timeout=30) as client:
        h = login(client, base, st.appflowy_email, st.appflowy_password)
        parent = find_parent_space(client, base, ws, h)

        for name, spec in schema.items():
            schema_fields = list(spec["fields"].items())
            if name in db_map:
                db_id = db_map[name]["database_id"]
                r = client.get(f"{base}/api/workspace/{ws}/database/{db_id}/fields", headers=h)
                if r.status_code == 200 and r.json().get("code") == 0:
                    primary_id, fields = reconcile_fields(client, base, ws, db_id, h, name, schema_fields)
                    db_map[name] = {
                        "view_id": db_map[name]["view_id"],
                        "database_id": db_id,
                        "primary_field_id": primary_id,
                        "title_column": schema_fields[0][0],
                        "fields": fields,
                    }
                    print(f"{name}: exists ({db_id}), reconciled")
                    continue
                print(f"{name}: stale mapping, recreating")

            r = client.post(f"{base}/api/workspace/{ws}/page-view", headers=h,
                            json={"parent_view_id": parent, "layout": 1, "name": name})
            r.raise_for_status()
            data = r.json()["data"]
            view_id, db_id = data["view_id"], data["database_id"]

            title_col = schema_fields[0][0]
            for fname, fspec in schema_fields[1:]:
                fr = client.post(f"{base}/api/workspace/{ws}/database/{db_id}/fields",
                                 headers=h, json=field_payload(fname, fspec))
                fr.raise_for_status()
                if fr.json().get("code") != 0:
                    raise RuntimeError(f"{name}.{fname}: {fr.text}")

            primary_id, fields, live_fields = fetch_field_mapping(
                client, base, ws, db_id, h, title_col
            )

            db_map[name] = {"view_id": view_id, "database_id": db_id,
                            "primary_field_id": primary_id, "title_column": title_col,
                            "fields": fields}
            print(f"{name}: created view={view_id} db={db_id} fields={len(live_fields)}")

        DB_MAP_PATH.write_text(json.dumps(db_map, indent=2))
        print(f"\nwrote {DB_MAP_PATH} with {len(db_map)} databases")


if __name__ == "__main__":
    main()

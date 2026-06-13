"""Read-only audit for AppFlowy board shape, starter rows, and content.

Reports:
- missing fields versus config/schema.yaml
- AppFlowy's default Type/Done columns
- rows with an empty primary Name cell, usually the three grid starter rows
- select fields with zero options, which render as unusable dropdowns
- child view names under each database page

Run from appflowy_kanban/growth-os:
  PYTHONPATH=. .venv/Scripts/python.exe scripts/audit_workspace.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import yaml

from growthos.config import load_settings


def login(client: httpx.Client, base: str, email: str, password: str) -> dict:
    r = client.post(
        f"{base}/gotrue/token?grant_type=password",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def row_details(
    client: httpx.Client,
    base: str,
    ws: str,
    db_id: str,
    headers: dict,
    row_ids: list[str],
) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(row_ids), 40):
        r = client.get(
            f"{base}/api/workspace/{ws}/database/{db_id}/row/detail",
            headers=headers,
            params={"ids": ",".join(row_ids[i:i + 40])},
        )
        r.raise_for_status()
        out.extend(r.json()["data"])
    return out


def field_details(
    client: httpx.Client,
    base: str,
    ws: str,
    db_id: str,
    headers: dict,
) -> list[dict]:
    r = client.get(f"{base}/api/workspace/{ws}/database/{db_id}/fields", headers=headers)
    r.raise_for_status()
    return r.json()["data"]


def view_children(folder: dict) -> dict[str, set[str]]:
    by_parent: dict[str, set[str]] = {}

    def walk(node: dict) -> None:
        parent = node.get("view_id", "")
        for child in node.get("children", []) or []:
            by_parent.setdefault(parent, set()).add(child.get("name", ""))
            walk(child)

    walk(folder)
    return by_parent


def option_count(field: dict) -> int | None:
    if field.get("field_type") != "SingleSelect":
        return None
    content = field.get("type_option", {}).get("content", {})
    return len(content.get("options", []))


def is_empty_cell(value) -> bool:
    if value in ("", None, False):
        return True
    if isinstance(value, (list, tuple, set)):
        return all(is_empty_cell(v) for v in value)
    if isinstance(value, dict):
        if "timezone" in value and "start" in value:
            return not any(
                value.get(key)
                for key in (
                    "start",
                    "end",
                    "pretty_start_date",
                    "pretty_start_datetime",
                    "pretty_start_time",
                    "pretty_end_date",
                    "pretty_end_datetime",
                    "pretty_end_time",
                    "reminder_id",
                )
            )
        return all(is_empty_cell(v) for v in value.values())
    return False


def is_blank_starter(cells: dict) -> bool:
    primary = str(cells.get("Name", "") or "").strip()
    if primary:
        return False
    meaningful = [
        value for key, value in cells.items()
        if key not in ("Type", "Done", "Name") and not is_empty_cell(value)
    ]
    return not meaningful


def cell_text(value) -> str:
    if value is None or value is False:
        return ""
    if isinstance(value, dict):
        for key in ("pretty_start_date", "pretty_start_datetime", "start"):
            if value.get(key):
                return str(value[key])
        return ""
    return str(value)


def sample_row(name: str, cells: dict) -> str:
    if name == "mission_intake":
        names = ("Name", "Status", "Section", "Priority", "Risk", "Repo", "Target")
    elif name == "todos":
        names = ("Name", "Status", "Area", "Priority", "Due")
    elif name in {"papers", "repos", "signals", "packages", "guidelines", "library", "lessons", "dags"}:
        names = ("Name", "Status", "Score", "Priority", "Severity", "DagID", "Updated", "Published")
    else:
        names = ("Name", "Status", "Kind", "Date")
    parts = []
    for field in names:
        value = cell_text(cells.get(field))
        if value:
            parts.append(f"{field}={value[:80]}")
    return "; ".join(parts) or f"Name={cell_text(cells.get('Name'))[:80]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", action="store_true", help="print sample real rows per database")
    args = ap.parse_args()

    st = load_settings()
    base = st.appflowy_base_url.rstrip("/")
    ws = st.appflowy_workspace_id
    schema = yaml.safe_load(Path("config/schema.yaml").read_text(encoding="utf-8"))["databases"]
    dbs = json.loads(Path("config/databases.json").read_text(encoding="utf-8"))

    with httpx.Client(timeout=30) as client:
        headers = login(client, base, st.appflowy_email, st.appflowy_password)
        folder = client.get(
            f"{base}/api/workspace/{ws}/folder",
            params={"depth": 10},
            headers=headers,
        )
        folder.raise_for_status()
        children = view_children(folder.json()["data"])

        print(
            f"{'database':18s} {'rows':>5s} {'real':>5s} {'blank':>5s} "
            f"{'missing':20s} {'junk':10s} {'empty-selects':14s} views"
        )
        print("-" * 118)
        for name, entry in dbs.items():
            expected = set((schema.get(name) or {}).get("fields", {}).keys())
            title_col = entry.get("title_column", "Name")
            if title_col in expected:
                expected.remove(title_col)
                expected.add("Name")

            live_fields = field_details(client, base, ws, entry["database_id"], headers)
            fields = {field["name"] for field in live_fields}
            missing = sorted(expected - fields)
            junk = sorted(x for x in ("Type", "Done") if x in fields and x not in expected)
            empty_selects = sorted(
                field["name"] for field in live_fields
                if option_count(field) == 0
            )

            r = client.get(
                f"{base}/api/workspace/{ws}/database/{entry['database_id']}/row",
                headers=headers,
            )
            r.raise_for_status()
            row_ids = [x["id"] for x in r.json()["data"]]
            details = row_details(client, base, ws, entry["database_id"], headers, row_ids)
            blank_count = sum(1 for row in details if is_blank_starter(row.get("cells", {})))
            real_rows = [
                row for row in details
                if not is_blank_starter(row.get("cells", {}))
                and str(row.get("cells", {}).get("Name", "") or "").strip()
            ]
            views = ", ".join(sorted(children.get(entry["view_id"], set()))) or "-"
            print(
                f"{name:18s} {len(row_ids):5d} {len(real_rows):5d} {blank_count:5d} "
                f"{', '.join(missing)[:20]:20s} {', '.join(junk)[:10]:10s} "
                f"{', '.join(empty_selects)[:14]:14s} {views}"
            )
            if args.details:
                for row in real_rows[:3]:
                    print(f"  - {sample_row(name, row.get('cells', {}))}")
                if not real_rows:
                    print("  - no real rows")


if __name__ == "__main__":
    main()

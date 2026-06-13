"""Add database views (Board/Calendar/Grid) to existing Growth OS databases.

Layouts (verified against AppFlowy Cloud REST): 1=Grid, 2=Board, 3=Calendar.
Boards group by the database's first single-select field (Status, by schema
convention); change grouping in the UI via view settings if needed.

Run:  PYTHONPATH=. .venv/Scripts/python.exe scripts/create_views.py
Idempotent-ish: re-running creates duplicate views with the same name, so it
checks the existing view names via the folder tree first and skips matches.
"""
from __future__ import annotations
import json
from pathlib import Path

import httpx

from growthos.config import load_settings

PLANS = [
    ("todos", 2, "Board"),
    ("todos", 3, "Deadlines"),
    ("mission_intake", 2, "Board"),
    ("mission_intake", 3, "Deadlines"),
    ("papers", 2, "Triage Board"),
    ("repos", 2, "Triage Board"),
    ("signals", 2, "Triage Board"),
    ("packages", 2, "Triage Board"),
    ("guidelines", 2, "Review Board"),
    ("library", 2, "Tier Board"),       # auto-groups by Tier (first select);
                                         # use this to work a tier at a time -
                                         # Essential is its own column
    ("library", 2, "Reading Board"),    # one-time UI: Group by -> Status
    ("lessons", 3, "Review Calendar"),  # calendar on NextReview (first date)
    ("lessons", 2, "Status Board"),     # one-time UI: Group by -> Status
]
# NOTE: AppFlowy view settings (group-by, filter, sort, column order) live in
# client-side collab state and have NO REST API (verified against the server
# source + docs.appflowy.io). A board auto-groups by the database's FIRST
# single-select field. So we create exactly one board per database here and
# the group/filter clicks are a documented one-time UI pass. Per-tier filtered
# boards were tried and removed - the Tier Board (grouped by Tier) is the
# correct, single-view way to read the curriculum one tier at a time.


def main() -> None:
    st = load_settings()
    base, ws = st.appflowy_base_url.rstrip("/"), st.appflowy_workspace_id
    r = httpx.post(f"{base}/gotrue/token?grant_type=password", timeout=30,
                   json={"email": st.appflowy_email, "password": st.appflowy_password})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    dbs = json.loads(Path("config/databases.json").read_text())

    folder = httpx.get(f"{base}/api/workspace/{ws}/folder", params={"depth": 10},
                       headers=h, timeout=30).json()["data"]
    existing: dict[str, set] = {}

    def walk(node):
        for ch in node.get("children", []) or []:
            existing.setdefault(node.get("view_id", ""), set()).add(ch.get("name", ""))
            walk(ch)
    walk(folder)

    for db, layout, name in PLANS:
        vid = dbs[db]["view_id"]
        if name in existing.get(vid, set()):
            print(f"{db} '{name}': already exists, skipping")
            continue
        r = httpx.post(f"{base}/api/workspace/{ws}/page-view/{vid}/database-view",
                       headers=h, timeout=30,
                       json={"parent_view_id": vid, "layout": layout, "name": name,
                             "database_id": dbs[db]["database_id"], "embedded": False})
        try:
            body = r.json()
            ok = "OK" if body.get("code") == 0 else body.get("message", "?")[:80]
        except Exception:
            ok = f"http {r.status_code}: {r.text[:120]!r}"
        print(f"{db} '{name}' (layout {layout}): {ok}")


if __name__ == "__main__":
    main()

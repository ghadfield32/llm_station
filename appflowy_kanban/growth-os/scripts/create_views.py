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
    ("library", 2, "Tier Board"),       # groups by Tier (first select field)
    ("library", 2, "Reading Board"),    # regroup in UI: Group by -> Status
    ("lessons", 3, "Review Calendar"),  # calendar on NextReview (first date)
    ("lessons", 2, "Status Board"),     # regroup in UI if it picks Domain
    # one working board per tier: in UI set Filter Tier=<name> + Group by
    # Status once per view (view settings are client-side; no REST for them)
    ("library", 2, "Tier: Essential"),
    ("library", 2, "Tier: Optional"),
    ("library", 2, "Tier: Companion"),
    ("library", 2, "Tier: Fun"),
    ("library", 2, "Tier: Reference"),
]


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

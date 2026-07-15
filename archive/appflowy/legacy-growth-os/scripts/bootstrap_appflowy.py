"""Helper to inspect your AppFlowy workspace and confirm IDs/fields.

Read-only and safe. Run AFTER you create the eight databases in the AppFlowy
UI (from config/schema.yaml). It prints workspace_id, each database_id, and the
field names — copy workspace_id into .env, and confirm field names match
schema.yaml so the Curator's FIELD_MAP lines up.

  python scripts/bootstrap_appflowy.py
"""
from __future__ import annotations
import json
from growthos.config import load_settings
from growthos.appflowy import AppFlowyClient


def main():
    st = load_settings()
    af = AppFlowyClient(st.appflowy_base_url, dry_run=False)
    af.login(st.appflowy_email, st.appflowy_password)
    import httpx
    base, h = af.base, af._headers
    ws = httpx.get(base + "/api/workspace", headers=h, timeout=30).json()
    print("WORKSPACES:\n", json.dumps(ws, indent=2)[:2000])
    print("\nCopy your workspace_id into .env, then re-run with it set to list databases.")
    if st.appflowy_workspace_id:
        dbs = httpx.get(base + f"/api/workspace/{st.appflowy_workspace_id}/database",
                        headers=h, timeout=30).json()
        print("\nDATABASES:\n", json.dumps(dbs, indent=2)[:3000])


if __name__ == "__main__":
    main()

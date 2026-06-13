#!/usr/bin/env python3
"""Scaffold the AppFlowy + Growth OS env files so the boards are one command away.

AppFlowy-Cloud's own deploy.env ships working localhost defaults (Postgres, GoTrue,
MinIO), so standing it up locally is really: copy deploy.env -> .env, copy the
curator's .env.example -> .env, then `make appflowy-up`. This does the copies (never
clobbering an existing .env) and prints the real next steps read from the files —
instead of asking a newcomer to hand-fill 80+ keys.

  python -m command_center.cli.appflowy_init      (or: make appflowy-init)

It does NOT invent secrets for the embedded Postgres/GoTrue URLs (those defaults are
internally consistent in deploy.env); it loudly flags that they are AppFlowy's public
dev defaults and must be rotated before any non-local exposure.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APPFLOWY = ROOT / "appflowy_kanban" / "AppFlowy-Cloud"
GROWTHOS = ROOT / "appflowy_kanban" / "growth-os"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def copy_if_absent(template: Path, dest: Path) -> bool:
    """Copy template->dest only if dest is missing. Returns True if it created it."""
    if dest.exists():
        print(f"  kept     {dest.relative_to(ROOT)} (already exists — not overwritten)")
        return False
    if not template.exists():
        raise SystemExit(f"appflowy-init: template missing: {template.relative_to(ROOT)}")
    shutil.copyfile(template, dest)
    print(f"  created  {dest.relative_to(ROOT)}  (from {template.name})")
    return True


def main() -> int:
    if not APPFLOWY.exists():
        raise SystemExit(
            "appflowy-init: appflowy_kanban/AppFlowy-Cloud is empty — fetch the submodule: "
            "git submodule update --init --recursive")

    print("AppFlowy + Growth OS env scaffold:")
    copy_if_absent(APPFLOWY / "deploy.env", APPFLOWY / ".env")
    copy_if_absent(GROWTHOS / ".env.example", GROWTHOS / ".env")

    env = read_env(APPFLOWY / ".env")
    scheme = env.get("SCHEME", "http")
    fqdn = env.get("FQDN", "localhost")
    base_url = f"{scheme}://{fqdn}"
    admin_email = env.get("GOTRUE_ADMIN_EMAIL", "(see AppFlowy-Cloud/.env)")

    print()
    print("Next:")
    print(f"  1. make appflowy-up                  # starts the board server at {base_url}")
    print(f"  2. open {base_url} and SIGN UP a real user (the GoTrue admin "
          f"{admin_email} is a system account and cannot own a workspace)")
    print("  3. put that user's email/password + the base URL into "
          "appflowy_kanban/growth-os/.env (APPFLOWY_* keys)")
    print("  4. cd appflowy_kanban/growth-os && python -m venv .venv && "
          ".venv/Scripts/pip install -r requirements.txt   # Linux: .venv/bin/pip")
    print("  5. .venv/Scripts/python scripts/setup_workspace.py   # creates the 8 databases")
    print()
    print("SECURITY: AppFlowy-Cloud/.env carries AppFlowy's PUBLIC dev defaults "
          "(Postgres/GoTrue/MinIO). Fine for localhost/tailnet; rotate every secret "
          "before any public exposure. Both .env files are gitignored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

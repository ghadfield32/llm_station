#!/usr/bin/env python3
"""
check_cross_refs.py — cross-file consistency the per-file contracts can't see.

Per-file Pydantic validation can't check that proactive.yaml's `target:` names
actually exist in targets.yaml (different files). This does. Exit 1 on a dangling
reference so the inventory and the watchers can't drift apart.
"""
import sys
import yaml

def main() -> int:
    targets = yaml.safe_load(open("configs/targets.yaml"))
    proactive = yaml.safe_load(open("configs/proactive.yaml"))
    kanban = yaml.safe_load(open("configs/kanban.yaml"))

    known = set()
    for kind in ("repos", "dags", "data_assets", "services"):
        for t in targets.get(kind, []):
            known.add(t["name"])
    # the proactive lane also uses category aliases for whole-class checks
    known |= {"airflow", "data_assets", "services"}

    ok = True
    checks = proactive.get("runtime_checks", []) + proactive.get("repo_stewardship", [])
    for c in checks:
        tgt = c.get("target")
        if tgt not in known:
            print(f"  DANGLING: proactive check '{c['name']}' watches '{tgt}' "
                  f"which is not in targets.yaml")
            ok = False
    standards = yaml.safe_load(open("configs/standards.yaml"))
    profiles = {p["name"] for p in standards.get("profiles", [])}
    for r in targets.get("repos", []):
        if r.get("standards_profile") not in profiles:
            print(f"  DANGLING: repo '{r['name']}' uses standards_profile "
                  f"'{r.get('standards_profile')}' not defined in standards.yaml")
            ok = False
    names_by_kind = {
        "repo": {r["name"] for r in targets.get("repos", [])},
        "dag": {d["name"] for d in targets.get("dags", [])},
        "data_asset": {a["name"] for a in targets.get("data_assets", [])},
        "service": {s["name"] for s in targets.get("services", [])},
    }
    for section in kanban.get("sections", []):
        kind = section.get("target_kind")
        target = section.get("target")
        if kind in names_by_kind and target not in names_by_kind[kind]:
            print(f"  DANGLING: kanban section '{section['name']}' points at "
                  f"{kind} target '{target}' not defined in targets.yaml")
            ok = False
        default_repo = section.get("default_repo")
        if default_repo and default_repo not in names_by_kind["repo"] and kind != "learning":
            print(f"  DANGLING: kanban section '{section['name']}' uses default_repo "
                  f"'{default_repo}' not defined in targets.yaml")
            ok = False

    # every channel's model must be a real models.yaml role (so the gateway can route it)
    models = yaml.safe_load(open("configs/models.yaml"))
    roles = set((models.get("roles") or {}).keys())
    channels = yaml.safe_load(open("configs/channels.yaml"))
    for ch in channels.get("channels", []):
        if ch.get("model") not in roles:
            print(f"  DANGLING: channel '{ch.get('name')}' uses model '{ch.get('model')}' "
                  f"which is not a role in models.yaml")
            ok = False
    print("cross-refs: PASS" if ok else "cross-refs: FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())

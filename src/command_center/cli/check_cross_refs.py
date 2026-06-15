#!/usr/bin/env python3
"""
check_cross_refs.py — cross-file consistency the per-file contracts can't see.

Per-file Pydantic validation can't check that proactive.yaml's `target:` names
actually exist in targets.yaml (different files). This does. Exit 1 on a dangling
reference so the inventory and the watchers can't drift apart.
"""
import sys
import yaml


def check_judge_routing(judges: dict, roles: set) -> list:
    """Every judge's role_alias and escalation_role must resolve to a real
    models.yaml role. A stage's cheap->strong escalation that points at a
    nonexistent route would silently never fire — so a typo here is a routing
    break, not a no-op. Returns a list of dangling-reference messages."""
    problems = []
    for stage in judges.get("stages", []):
        for j in stage.get("judges", []):
            for field in ("role_alias", "escalation_role"):
                ref = j.get(field)
                if ref and ref not in roles:
                    problems.append(
                        f"judge '{j.get('name')}' {field} '{ref}' "
                        f"is not a role in models.yaml")
    return problems


def check_gate_routes(gates: dict, roles: set) -> list:
    """Every risk tier's default Judge Gate classify route must resolve to a
    real models.yaml role. This keeps request routing in validated config rather
    than in a service-local fallback table."""
    problems = []
    for tier, policy in (gates.get("tiers") or {}).items():
        ref = policy.get("default_route_alias")
        if not ref:
            problems.append(f"gate tier '{tier}' missing default_route_alias")
        elif ref not in roles:
            problems.append(
                f"gate tier '{tier}' default_route_alias '{ref}' "
                f"is not a role in models.yaml")
    return problems


def check_tool_safe_roles(models: dict, channels: dict) -> list:
    """A TOOL-USING role must not be backed by a model whose Ollama tool parser
    drops a call the model prefixes with prose. Only the qwen3-coder family is
    known-broken: it ships a native RENDERER/PARSER (its Go template has no tool
    handling) and leaks such calls to the user as raw `<function=..>` XML
    (reproduced 7/8; MASTER.md §14, 2026-06-13). Tool users in this system: every
    chat channel's role, plus `planner` (Hermes tool-calls through it,
    HERMES_DEFAULT_MODEL). qwen3 / devstral parse tool calls robustly. Returns a
    list of tool-unsafe-routing messages (empty = all tool roles are safe)."""
    role_models = {role: [c.get("model", "") for c in cands]
                   for role, cands in (models.get("roles") or {}).items()}
    tool_using = {ch.get("model") for ch in channels.get("channels", [])}
    tool_using.add("planner")                 # Hermes' default tool-calling model
    problems = []
    for role in sorted(r for r in tool_using if r):
        bad = sorted({m for m in role_models.get(role, [])
                      if m.startswith("qwen3-coder")})
        if bad:
            problems.append(
                f"role '{role}' is used for tool-calling but is backed by {bad}, "
                f"whose Ollama parser drops prose-prefixed tool calls; route it to "
                f"a tool-robust model (qwen3/devstral — configs/models.yaml `chat:`)")
    return problems


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
    checks = (
        proactive.get("runtime_checks", [])
        + proactive.get("repo_stewardship", [])
        + proactive.get("self_improvement_scans", [])
    )
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

    # a tool-using role must not be backed by a model whose Ollama tool parser
    # drops prose-prefixed calls (see check_tool_safe_roles)
    for msg in check_tool_safe_roles(models, channels):
        print(f"  TOOL-UNSAFE: {msg}")
        ok = False

    # every judge's role_alias + escalation_role must route to a real role, so the
    # cheap->strong / stuck-escalation chain can never point at a nonexistent model
    judges = yaml.safe_load(open("configs/judges.yaml"))
    for msg in check_judge_routing(judges, roles):
        print(f"  DANGLING: {msg}")
        ok = False

    # every risk tier's default classify route must also resolve to a real role.
    gates = yaml.safe_load(open("configs/gates.yaml"))
    for msg in check_gate_routes(gates, roles):
        print(f"  DANGLING: {msg}")
        ok = False

    print("cross-refs: PASS" if ok else "cross-refs: FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())

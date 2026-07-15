#!/usr/bin/env python3
"""
Abilities & routing verification — drive the shared agent tools many ways through the LOGGED
dispatch (the same table the Discord, MCP, and local-assistant agents use), so you can confirm
every tool routes and works, every call lands in the agent-call log, and the approval wall is
STRUCTURAL (there is no 'approve' verb — staging to Approved is a human drag).

Read-only + structural only (no live writes): the write/lifecycle verbs are exercised by the
agent-kanban-surface unit tests (tests/test_actions_intent.py); the live write ability is proven
separately (book_note on 'Alan Turing: The Enigma'). Run from the growth-os root (AppFlowy up):

    PYTHONPATH=. .venv/Scripts/python.exe scripts/test_abilities.py
    PYTHONPATH=. .venv/Scripts/python.exe -m growthos.observability   # then watch the log
"""
from __future__ import annotations

import sys

from growthos.assistant import DISPATCH, TOOL_FNS

# (label, tool, kwargs) — each query ability exercised >=5 ways across databases/filters
READ_CASES = [
    ("liveness of all 5 hops", "network_health", {}),
    ("search library: Turing", "search", {"database": "library", "query": "Turing"}),
    ("search library: Enigma", "search", {"database": "library", "query": "Enigma"}),
    ("search papers: agent", "search", {"database": "papers", "query": "agent"}),
    ("search repos: airflow", "search", {"database": "repos", "query": "airflow"}),
    ("search todos: review", "search", {"database": "todos", "query": "review"}),
    ("inbox: papers", "list_inbox", {"database": "papers", "limit": 5}),
    ("inbox: repos", "list_inbox", {"database": "repos", "limit": 5}),
    ("inbox: signals", "list_inbox", {"database": "signals", "limit": 5}),
    ("todos: all open", "list_todos", {"status": "", "area": ""}),
    ("todos: In Progress", "list_todos", {"status": "In Progress", "area": ""}),
    ("todos: Blocked", "list_todos", {"status": "Blocked", "area": ""}),
    ("todos: Done", "list_todos", {"status": "Done", "area": ""}),
    ("cards: all", "list_cards", {"status": ""}),
    ("cards: Approved", "list_cards", {"status": "Approved"}),
    ("cards: Backlog", "list_cards", {"status": "Backlog"}),
    ("dags board", "list_dags", {"status": ""}),
    ("latest brief", "latest_brief", {}),
    ("project status: betts", "project_status", {"project": "betts_basketball"}),
]

# the queue -> in-progress -> complete flow is given by these intent verbs (not a flattened schema)
LIFECYCLE_VERBS = {"stage_card", "block_card", "reject_card", "start_todo", "finish_todo",
                   "block_todo"}
KANBAN_FIELD_VERBS = {"annotate_item", "set_item_field", "remove_item_field_value"}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70 + "\nABILITIES & ROUTING VERIFICATION (logged dispatch)\n" + "=" * 70)
    passed = failed = 0
    used: set[str] = set()

    print("\n-- query abilities (read-only, live) --")
    for label, tool, kw in READ_CASES:
        used.add(tool)
        try:
            DISPATCH[tool](**kw)               # routes to the tool; logged automatically
            print(f"  [PASS] {tool:16s} {label}")
            passed += 1
        except Exception as exc:               # a read tool must not raise
            print(f"  [FAIL] {tool:16s} {label} :: {type(exc).__name__}: {exc}")
            failed += 1

    print("\n-- the approval wall is STRUCTURAL --")
    names = {f.__name__ for f in TOOL_FNS}
    checks = [
        ("no 'approve' verb exists", not any("approve" in n for n in names)),
        ("set_status not exposed as a tool", "set_status" not in DISPATCH),
        ("lifecycle verbs present (queue->in-progress->complete)", LIFECYCLE_VERBS <= names),
        ("field-edit verbs present (notes + schema grouping)", KANBAN_FIELD_VERBS <= names),
    ]
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        passed += ok
        failed += not ok

    print("\n-- every tool on every surface is logged --")
    all_logged = all(hasattr(DISPATCH[f.__name__], "__wrapped__") for f in TOOL_FNS)
    print(f"  [{'PASS' if all_logged else 'FAIL'}] {len(TOOL_FNS)} tools wrapped by the agent-call log")
    passed += all_logged
    failed += not all_logged

    total = passed + failed
    print("\n" + "=" * 70)
    print(f"abilities-verification: {passed}/{total} PASS · {len(used)} query tools routed · "
          f"{len(TOOL_FNS)} tools total")
    print("every call above is in the agent-call log: `python -m growthos.observability`")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

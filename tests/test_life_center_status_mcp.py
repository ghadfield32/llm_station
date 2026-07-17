"""The life-center-status MCP is read-only by contract.

These tests pin the allowlist and the no-free-form-arg guarantee without needing
the ``mcp`` package installed (the server itself imports FastMCP lazily).
"""
from __future__ import annotations

import inspect

from command_center.mcp import life_center_status as lcs

EXPECTED_TOOLS = {
    "get_overview",
    "get_service_health",
    "get_backup_status",
    "get_storage_capacity",
    "get_model_inventory",
    "get_archive_freshness",
    "get_security_findings",
    "get_pending_maintenance",
}


def test_allowlist_is_exactly_the_eight_readonly_tools():
    names = {fn.__name__ for fn in lcs.READONLY_TOOLS}
    assert names == EXPECTED_TOOLS
    # no duplicates hiding in the list
    assert len(lcs.READONLY_TOOLS) == len(EXPECTED_TOOLS)


def test_no_tool_accepts_free_form_arguments():
    for fn in lcs.READONLY_TOOLS:
        sig = inspect.signature(fn)
        assert not sig.parameters, f"{fn.__name__} must take no arguments (read-only, no free-form input)"


def test_tools_return_json_serializable_typed_shapes():
    import json

    for fn in lcs.READONLY_TOOLS:
        result = fn()
        assert isinstance(result, (dict, list)), f"{fn.__name__} must return dict/list"
        json.dumps(result)  # redacted health facts must serialize cleanly


def test_no_mutation_or_action_surface_is_exported():
    exported = {n for n in dir(lcs) if not n.startswith("_")}
    banned = {"delete", "restart", "prune", "destroy", "exec", "run_command", "shell"}
    assert not (exported & banned)
    # There is no life-center-actions surface in this module.
    assert not any("action" in n.lower() for n in exported)

"""life-center-actions is default-deny: only the plan's "Read-only, no
approval" tier is registered. These tests pin that boundary so a future edit
can't silently widen it without a test failing first."""
from __future__ import annotations

from command_center.mcp import life_center_actions as lca

EXPECTED_ACTION_IDS = {
    "life_center.refresh_status",
    "life_center.verify_service",
    "life_center.verify_links",
    "life_center.refresh_catalog_projection",
}

# Substrings that must never appear in an admitted action_id — see the
# module's "NEVER add these here" list.
_FORBIDDEN_SUBSTRINGS = (
    "delete", "restart", "prune", "destroy", "shell", "exec", "run_command",
    "mutate", "approve", "merge", "deploy", "rotate", "forget",
)


def test_registry_is_exactly_the_four_read_only_actions():
    assert set(lca.ADMITTED_ACTION_IDS) == EXPECTED_ACTION_IDS
    assert len(lca.ADMITTED_ACTION_IDS) == len(EXPECTED_ACTION_IDS)


def test_no_admitted_action_id_matches_a_forbidden_verb():
    for action_id in lca.ADMITTED_ACTION_IDS:
        lowered = action_id.lower()
        for bad in _FORBIDDEN_SUBSTRINGS:
            assert bad not in lowered, f"{action_id!r} matches forbidden verb {bad!r}"


def test_dispatch_rejects_an_unregistered_action_id():
    result = lca.dispatch("life_center.delete_everything")
    assert result.status == "rejected"
    assert "unregistered" in result.error


def test_dispatch_never_raises_on_a_bad_action_id():
    # A malformed/unknown action_id must produce a typed rejection, never an
    # unhandled exception — this is the boundary a broker sits behind.
    result = lca.dispatch("../../etc/passwd")
    assert result.status == "rejected"


def test_action_request_accepts_forward_compatible_approval_fields():
    req = lca.ActionRequest(
        action_id="life_center.refresh_status", request_id="r1", idempotency_key="r1",
        approval_id="some-ledger-ref", catalog_digest="sha256:abc",
    )
    assert req.approval_id == "some-ledger-ref"
    assert req.catalog_digest == "sha256:abc"


def test_verify_service_requires_service_id():
    result = lca.dispatch("life_center.verify_service")
    assert result.status == "error"
    assert "service_id" in result.error


def test_no_forbidden_names_exported_at_module_level():
    exported = {n for n in dir(lca) if not n.startswith("_")}
    banned = {"delete", "restart", "prune", "destroy", "shell", "run_command"}
    assert not (exported & banned)

"""Structured board-format column transform (plan §8 board-format changes,
no browser-generated YAML). The browser sends a typed column list; the server
computes the `after` config, pruning stale column_actions so the result stays
contract-valid.
"""
from __future__ import annotations

import pytest

from command_center.kanban_sync.board_format import (
    BoardFormatChange,
    apply_columns_change,
    columns_diff,
    current_columns,
)


def _cfg():
    return {
        "schema_version": "command-center.domain-surfaces.v1",
        "domains": [{
            "domain_id": "improvements", "title": "Improvements",
            "card_component": "generic_task", "source": "board_store",
            "board_id": "improvements",
            "columns": ["Observed", "Ready", "In Progress", "Done"],
            "column_actions": {"Ready": "stage_card", "In Progress": "start_todo",
                               "Done": "finish_todo"},
            "empty_state": {"title": "No work yet", "hint": "add a card"},
        }],
    }


def test_current_columns():
    assert current_columns(_cfg(), "improvements") == [
        "Observed", "Ready", "In Progress", "Done"]


def test_apply_columns_is_a_deep_copy_no_mutation():
    cfg = _cfg()
    before_snapshot = current_columns(cfg, "improvements")
    change = BoardFormatChange(domain_id="improvements",
                               columns=["Observed", "Grounded", "Ready", "Done"])
    after = apply_columns_change(cfg, change)
    # original untouched (pure); after reflects the change
    assert current_columns(cfg, "improvements") == before_snapshot
    assert current_columns(after, "improvements") == [
        "Observed", "Grounded", "Ready", "Done"]


def test_apply_prunes_stale_column_actions():
    # dropping "In Progress" must drop its column_action, else the contract rejects
    change = BoardFormatChange(domain_id="improvements",
                               columns=["Observed", "Ready", "Done"])
    after = apply_columns_change(_cfg(), change)
    domain = after["domains"][0]
    assert "In Progress" not in domain["column_actions"]
    assert domain["column_actions"] == {"Ready": "stage_card", "Done": "finish_todo"}


def test_apply_result_validates_against_the_real_contract():
    from command_center.schemas.contracts import DomainSurfacesConfig
    change = BoardFormatChange(
        domain_id="improvements",
        columns=["Observed", "Grounded", "Ready", "In Progress", "Verifying", "Done"])
    after = apply_columns_change(_cfg(), change)
    DomainSurfacesConfig.model_validate(after)     # must not raise


def test_duplicate_columns_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        apply_columns_change(_cfg(), BoardFormatChange(
            domain_id="improvements", columns=["Observed", "Observed"]))


def test_empty_columns_rejected():
    with pytest.raises(ValueError, match="at least one column"):
        apply_columns_change(_cfg(), BoardFormatChange(
            domain_id="improvements", columns=[]))


def test_unknown_domain_raises():
    with pytest.raises(KeyError):
        apply_columns_change(_cfg(), BoardFormatChange(
            domain_id="nope", columns=["A"]))


def test_columns_diff_reports_added_removed_reordered():
    d = columns_diff(["Observed", "Ready", "In Progress", "Done"],
                     ["Observed", "Grounded", "Ready", "Done"])
    assert d["added"] == ["Grounded"]
    assert d["removed"] == ["In Progress"]

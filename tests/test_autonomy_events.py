"""Canonical event and completion-verifier tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from command_center.autonomy import CanonicalEvent, validate_event_record, verify_completion
from command_center.schemas import AutonomyConfig, RiskTier

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config() -> AutonomyConfig:
    raw = yaml.safe_load((REPO_ROOT / "configs/autonomy.yaml").read_text(encoding="utf-8"))
    return AutonomyConfig.model_validate(raw)


def _event(
    kind: str,
    detail: dict[str, Any],
    *,
    privacy_classification: str = "confidential",
    result: str = "verified",
) -> CanonicalEvent:
    return CanonicalEvent(
        kind=kind,
        event_id=f"evt-{kind.replace('.', '-')}",
        mission_id="mission-autonomy-test",
        timestamp="2026-06-16T12:00:00Z",
        actor="pytest",
        source_authority="tests/test_autonomy_events.py",
        risk_tier=RiskTier.L1,
        privacy_classification=privacy_classification,
        result=result,
        input_artifact_hashes=[],
        output_artifact_hashes=[],
        trace_id="trace-autonomy-test",
        detail=detail,
    )


def _forecast(expected_state_after: dict[str, str]) -> CanonicalEvent:
    return _event(
        "mission.forecast",
        {
            "expected_state_before": {"card": "Backlog"},
            "expected_state_after": expected_state_after,
            "expected_events": ["mission.verification"],
            "expected_no_change": ["provider_keys", "raw_transcripts", "screenshots"],
            "privacy_boundary": "hashes_and_refs_only",
            "rollback_or_revert_plan": "delete local test evidence package",
        },
        result="planned",
    )


def _verification(observed_state_after: dict[str, str], evidence_refs: list[str]) -> CanonicalEvent:
    return _event(
        "mission.verification",
        {
            "observed_state_after": observed_state_after,
            "evidence_refs": evidence_refs,
            "verifier_result": "matched_forecast",
        },
    )


def _mission_action(command: str = "noop-scan") -> CanonicalEvent:
    return _event(
        "mission.action",
        {
            "command_or_tool": command,
            "target_ref": "repo:llm_station",
            "observed_state_before": {"repo": "unchanged"},
            "action": "read_only_scan",
        },
        result="started",
    )


def test_valid_forecast_and_verification_pass_completion():
    cfg = _config()
    expected = {"card": "In Progress", "repo": "unchanged"}

    verdict = verify_completion(
        _forecast(expected),
        _verification(expected, ["evaluation/system-validation/test-run/BASELINE.md"]),
        [_mission_action()],
        cfg,
    )

    assert verdict.passed
    assert verdict.reasons == []


def test_event_validation_rejects_missing_family_detail():
    cfg = _config()
    event = _event("mission.verification", {"observed_state_after": {"card": "Done"}})

    with pytest.raises(ValueError, match="evidence_refs"):
        validate_event_record(event, cfg)


def test_event_validation_rejects_raw_detail_payloads():
    cfg = _config()
    event = _verification(
        {"card": "Done"},
        ["evaluation/system-validation/test-run/BASELINE.md"],
    )
    event.detail["raw_screen_text"] = "not retained"

    with pytest.raises(ValueError, match="raw payload"):
        validate_event_record(event, cfg)


def test_secret_reference_events_must_name_secret_refs_only():
    cfg = _config()
    event = _verification(
        {"card": "Done"},
        ["evaluation/system-validation/test-run/BASELINE.md"],
    )
    event.privacy_classification = "secret_reference"

    with pytest.raises(ValueError, match="secret_refs"):
        validate_event_record(event, cfg)

    event.detail["secret_refs"] = ["env:DISCORD_BOT_TOKEN"]
    assert validate_event_record(event, cfg) == event


def test_completion_blocks_when_observed_state_does_not_match_forecast():
    cfg = _config()

    verdict = verify_completion(
        _forecast({"card": "Done"}),
        _verification({"card": "In Progress"}, ["evaluation/system-validation/test-run/GAPS.md"]),
        [_mission_action()],
        cfg,
    )

    assert not verdict.passed
    assert any("observed_state_after does not match" in reason for reason in verdict.reasons)


def test_completion_blocks_without_evidence_refs():
    cfg = _config()
    expected = {"card": "Done"}

    verdict = verify_completion(
        _forecast(expected),
        _verification(expected, []),
        [_mission_action()],
        cfg,
    )

    assert not verdict.passed
    assert any("evidence_refs" in reason for reason in verdict.reasons)


def test_completion_blocks_repeated_action_signature():
    cfg = _config()
    expected = {"repo": "unchanged"}

    verdict = verify_completion(
        _forecast(expected),
        _verification(expected, ["evaluation/system-validation/test-run/COMMANDS.md"]),
        [_mission_action(), _mission_action()],
        cfg,
    )

    assert not verdict.passed
    assert any("repeated action signature" in reason for reason in verdict.reasons)

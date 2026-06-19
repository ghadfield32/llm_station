"""Forecast/evidence completion verifier and conservative loop breaker."""
from __future__ import annotations

from pydantic import Field

from command_center.autonomy.events import CanonicalEvent, validate_event_record
from command_center.schemas import AutonomyConfig, Strict


class CompletionVerdict(Strict):
    status: str
    reasons: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _action_signature(event: CanonicalEvent) -> tuple[str, str, str]:
    detail = event.detail
    return (
        str(detail.get("command_or_tool", "")),
        str(detail.get("target_ref", "")),
        str(detail.get("action", detail.get("command", ""))),
    )


def verify_completion(
    forecast: CanonicalEvent,
    verification: CanonicalEvent,
    recent_actions: list[CanonicalEvent],
    config: AutonomyConfig,
) -> CompletionVerdict:
    """Compare forecast to observed verification evidence.

    This function is deterministic and deliberately conservative. It requires
    matching event families, configured event validation, evidence references,
    and observed state matching the forecast when the forecast names an expected
    state. Exact repeated action signatures require a strategy change rather
    than a fabricated DONE.
    """
    reasons: list[str] = []

    if forecast.kind != "mission.forecast":
        reasons.append("forecast event must be mission.forecast")
    if verification.kind != "mission.verification":
        reasons.append("verification event must be mission.verification")

    for event in [forecast, verification, *recent_actions]:
        try:
            validate_event_record(event, config)
        except ValueError as exc:
            reasons.append(str(exc))

    expected = forecast.detail.get("expected_state_after")
    observed = verification.detail.get("observed_state_after")
    if expected is not None and observed != expected:
        reasons.append(
            f"observed_state_after does not match expected_state_after: {observed!r} != {expected!r}"
        )

    evidence_refs = verification.detail.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        reasons.append("verification must include non-empty evidence_refs")

    signatures = [_action_signature(event) for event in recent_actions if event.kind == "mission.action"]
    signatures = [sig for sig in signatures if any(sig)]
    if len(signatures) != len(set(signatures)):
        reasons.append("repeated action signature detected; strategy change required")

    return CompletionVerdict(status="BLOCKED" if reasons else "PASS", reasons=reasons)

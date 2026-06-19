"""Canonical autonomy event records.

The event contract is config-backed (`configs/autonomy.yaml`). The Pydantic
record below provides the common wire shape; `validate_event_record` applies the
configured event-family requirements without retaining raw payloads.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from command_center.schemas import AutonomyConfig, RiskTier, Strict


class CanonicalEvent(Strict):
    schema_version: Literal["command-center.event.v1"] = "command-center.event.v1"
    kind: str
    event_id: str
    mission_id: str
    timestamp: str
    actor: str
    source_authority: str
    risk_tier: RiskTier
    privacy_classification: str
    result: str
    input_artifact_hashes: list[str] = Field(default_factory=list)
    output_artifact_hashes: list[str] = Field(default_factory=list)
    trace_id: str
    approval_id: str | None = None
    rollback_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _checks(self):
        required = {
            "kind": self.kind,
            "event_id": self.event_id,
            "mission_id": self.mission_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "source_authority": self.source_authority,
            "privacy_classification": self.privacy_classification,
            "result": self.result,
            "trace_id": self.trace_id,
        }
        blank = [name for name, value in required.items() if not value]
        if blank:
            raise ValueError(f"canonical event has blank required field(s): {blank}")
        return self


def validate_event_record(event: CanonicalEvent, config: AutonomyConfig) -> CanonicalEvent:
    families = {family.kind: family for family in config.event_contract.families}
    family = families.get(event.kind)
    if family is None:
        raise ValueError(f"unknown event family {event.kind!r}")
    if event.privacy_classification not in set(config.event_contract.privacy_classes):
        raise ValueError(
            f"unknown privacy_classification {event.privacy_classification!r}"
        )
    if event.result not in set(config.event_contract.result_values):
        raise ValueError(f"unknown event result {event.result!r}")
    missing = [field for field in family.required_fields if field not in event.detail]
    if missing:
        raise ValueError(f"event {event.kind!r} missing detail field(s): {missing}")
    if any(key.startswith("raw_") for key in event.detail):
        raise ValueError("canonical events may not retain raw payload fields")
    if event.privacy_classification == "secret_reference":
        refs = event.detail.get("secret_refs", [])
        if not isinstance(refs, list) or not refs:
            raise ValueError("secret_reference events must name secret_refs, not secret values")
    return event

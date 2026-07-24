"""Runtime-agnostic agent-session configuration."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from .base import Strict


class AgentHarnessId(StrEnum):
    FAKE = "fake"
    CODEX_AGENT = "codex_agent"
    CLAUDE_CODE_LOCAL = "claude_code_local"
    CLAUDE_AGENT = "claude_agent"
    OPENROUTER_AGENT = "openrouter_agent"


class CapabilityProfile(StrEnum):
    STRATEGIC_STEWARD = "strategic_steward"
    GENERALIST = "generalist"
    DEEP_CODE = "deep_code"
    THROUGHPUT = "throughput"


class AgentEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class AgentSessionSpec(Strict):
    """A portable session request.

    ``capability_profile`` is resolved live at session start; this contract
    deliberately contains no remembered model slug or authentication data.
    """

    name: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    instructions: str | None = Field(default=None, min_length=1)
    instructions_file: str | None = Field(default=None, min_length=1)
    harness: AgentHarnessId
    capability_profile: CapabilityProfile
    effort: AgentEffort | None = None
    mode: str = Field(min_length=1)
    policy_refs: list[str] = Field(default_factory=list)

    @field_validator("instructions_file")
    @classmethod
    def instructions_file_must_be_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute() or path.drive or ".." in path.parts:
            raise ValueError("instructions_file must be relative to the spec file")
        return value

    @field_validator("policy_refs")
    @classmethod
    def policy_refs_must_not_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("policy_refs entries must not be blank")
        return values

    @model_validator(mode="after")
    def exactly_one_instructions_source(self) -> AgentSessionSpec:
        if (self.instructions is None) == (self.instructions_file is None):
            raise ValueError(
                "exactly one of instructions or instructions_file must be provided")
        return self

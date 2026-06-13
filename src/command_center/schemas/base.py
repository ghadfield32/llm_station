"""
Base contracts. Everything editable in configs/ validates against these.

Design rule (matches your standards): strict where it prevents real breakage,
nothing where it would just be a typed restatement of trivial config. extra="forbid"
is the workhorse — a typo'd key fails loudly at `make validate` instead of silently
doing nothing at 2am.
"""
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    # forbid unknown keys (catch typos), strip whitespace, validate on assignment
    model_config = ConfigDict(extra="forbid", validate_assignment=True,
                              str_strip_whitespace=True)


class RiskTier(StrEnum):
    L0 = "L0_read_only"
    L1 = "L1_plan_only"
    L2 = "L2_local_edits"
    L3 = "L3_external_write"
    L4 = "L4_dangerous"


class Decision(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    ESCALATE = "escalate"


class Provider(StrEnum):
    OLLAMA = "ollama"
    VLLM = "vllm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


class EnvKind(StrEnum):
    CONTROL_PLANE = "control_plane"
    WORKER = "worker"
    REPO_TASK = "repo_task"
    JUDGE = "judge"
    CI = "ci"
    RELAY = "relay"

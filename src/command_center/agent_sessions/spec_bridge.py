"""Load agent-session specs and bridge them to the existing harness registry."""
from __future__ import annotations

from pathlib import Path
import re

import yaml

from command_center.schemas.agent_session_spec import AgentSessionSpec

from .registry import HarnessDescriptor, HarnessRegistry


AGENT_SESSION_SPECS_DIR = Path("configs/agent_sessions")


def resolve_spec(
    spec: AgentSessionSpec, registry: HarnessRegistry,
) -> HarnessDescriptor:
    """Return the registered descriptor after validating its supported mode."""
    harness_id = spec.harness.value
    try:
        descriptor = registry.get(harness_id)
    except KeyError as exc:
        raise KeyError(f"agent-session spec references unknown harness {harness_id!r}") from exc
    if spec.mode not in descriptor.supported_modes:
        raise ValueError(
            f"agent-session spec mode {spec.mode!r} is unsupported by harness "
            f"{harness_id!r} (supports: {list(descriptor.supported_modes)})")
    return descriptor


def load_spec(
    spec_name: str, *, directory: Path | None = None,
) -> tuple[AgentSessionSpec, str]:
    """Load one named spec and its inline-or-file-backed instructions.

    Lookup is deliberately per call. There is no import-time directory scan or
    cache, so config changes and test monkeypatches are observed immediately.
    """
    if re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", spec_name) is None:
        raise ValueError(f"invalid agent-session spec name: {spec_name!r}")
    root = directory if directory is not None else AGENT_SESSION_SPECS_DIR
    path = root / f"{spec_name}.yaml"
    with path.open(encoding="utf-8") as handle:
        spec = AgentSessionSpec.model_validate(yaml.safe_load(handle))
    if spec.name != spec_name:
        raise ValueError(
            f"agent-session spec name {spec.name!r} does not match filename "
            f"{path.name!r}")
    if spec.instructions is not None:
        return spec, spec.instructions
    assert spec.instructions_file is not None  # enforced by AgentSessionSpec's XOR
    instructions_path = path.parent / spec.instructions_file
    try:
        instructions = instructions_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(
            f"cannot read instructions_file {spec.instructions_file!r} for "
            f"agent-session spec {spec.name!r}: {exc}") from exc
    if not instructions.strip():
        raise ValueError(
            f"instructions_file {spec.instructions_file!r} for agent-session "
            f"spec {spec.name!r} is empty")
    return spec, instructions

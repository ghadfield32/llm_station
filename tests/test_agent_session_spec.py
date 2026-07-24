from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from command_center.agent_sessions.fake_harness import FakeHarness
from command_center.agent_sessions.protocol import SessionStart
from command_center.agent_sessions.registry import (
    HarnessDescriptor, HarnessRegistry, default_registry,
)
from command_center.agent_sessions.service import AgentSessionService
from command_center.agent_sessions.spec_bridge import load_spec, resolve_spec
from command_center.agent_sessions.store import SessionStore
from command_center.schemas.agent_session_spec import AgentHarnessId, AgentSessionSpec


def _spec(**overrides) -> AgentSessionSpec:
    data = {
        "name": "test-agent",
        "instructions": "Analyze the repository.",
        "harness": "fake",
        "capability_profile": "generalist",
        "mode": "analysis",
    }
    data.update(overrides)
    return AgentSessionSpec.model_validate(data)


def _start(**overrides) -> SessionStart:
    data = {
        "conversation_id": "conversation-1",
        "repo_id": "repo-1",
        "mode": "analysis",
    }
    data.update(overrides)
    return SessionStart(**data)


def test_yaml_model_round_trip_and_unknown_key_rejection():
    original = _spec(effort="high", policy_refs=["read-only"])
    dumped = yaml.safe_dump(original.model_dump(mode="json"))
    assert AgentSessionSpec.model_validate(yaml.safe_load(dumped)) == original

    data = original.model_dump(mode="json")
    data["model"] = "remembered-model-slug"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentSessionSpec.model_validate(data)


@pytest.mark.parametrize(
    ("instructions", "instructions_file"),
    [(None, None), ("inline", "instructions.md")],
)
def test_instructions_xor_is_enforced(instructions, instructions_file):
    with pytest.raises(ValidationError, match="exactly one"):
        _spec(instructions=instructions, instructions_file=instructions_file)


def test_instructions_file_is_resolved_relative_to_spec(tmp_path):
    (tmp_path / "prompt.md").write_text("Instructions from a file.\n", encoding="utf-8")
    (tmp_path / "file-backed.yaml").write_text(
        yaml.safe_dump({
            "name": "file-backed",
            "instructions_file": "prompt.md",
            "harness": "fake",
            "capability_profile": "throughput",
            "mode": "analysis",
        }),
        encoding="utf-8",
    )
    spec, instructions = load_spec("file-backed", directory=tmp_path)
    assert spec.instructions_file == "prompt.md"
    assert instructions == "Instructions from a file.\n"


def test_harness_enum_and_default_registry_cannot_drift():
    registry_ids = {
        descriptor.harness_id
        for descriptor in default_registry(SessionStore()).descriptors()
    }
    enum_ids = {harness.value for harness in AgentHarnessId}
    assert enum_ids == registry_ids


def test_bridge_resolves_every_registered_harness():
    registry = default_registry(SessionStore())
    for descriptor in registry.descriptors():
        spec = _spec(
            harness=descriptor.harness_id,
            mode=descriptor.supported_modes[0],
        )
        assert resolve_spec(spec, registry) is descriptor


def test_bridge_reports_unknown_harness_value():
    with pytest.raises(KeyError, match="fake"):
        resolve_spec(_spec(harness="fake"), HarnessRegistry([]))


def test_bridge_reports_unsupported_mode_value():
    registry = default_registry(SessionStore())
    with pytest.raises(ValueError, match="unsupported-mode"):
        resolve_spec(_spec(mode="unsupported-mode"), registry)


def test_all_example_agent_session_configs_validate():
    paths = sorted(Path("configs/agent_sessions").glob("*.yaml"))
    assert len(paths) >= 2
    for path in paths:
        spec, instructions = load_spec(path.stem, directory=path.parent)
        assert spec.name == path.stem
        assert instructions.strip()


def test_consumer_flag_off_ignores_spec_name(monkeypatch):
    monkeypatch.delenv("AGENT_SESSION_SPEC_ENABLED", raising=False)
    store = SessionStore()
    service = AgentSessionService(store=store, registry=default_registry(store))
    record = asyncio.run(service.start_session(_start(spec_name="missing-spec")))

    assert record.harness == "fake"
    assert record.provider_profile == "default"
    assert store.events_since(record.session_id)[0].payload == {"mode": "analysis"}


def test_consumer_flag_on_boots_from_spec_and_records_metadata(
    monkeypatch, tmp_path,
):
    from command_center.agent_sessions import spec_bridge

    (tmp_path / "fake-throughput.yaml").write_text(
        yaml.safe_dump({
            "name": "fake-throughput",
            "instructions": "Use the packet as the sole source of truth.",
            "harness": "fake",
            "capability_profile": "throughput",
            "effort": "xhigh",
            "mode": "workspace",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_SESSION_SPEC_ENABLED", "1")
    monkeypatch.setattr(spec_bridge, "AGENT_SESSION_SPECS_DIR", tmp_path)
    store = SessionStore()

    class CapturingFakeHarness(FakeHarness):
        request: SessionStart | None = None

        async def start_session(self, request: SessionStart) -> str:
            self.request = request
            return await super().start_session(request)

    harness = CapturingFakeHarness(store)
    registry = HarnessRegistry([HarnessDescriptor(
        harness_id="fake", label="Fake", production=False,
        supported_modes=("analysis", "workspace"), factory=lambda: harness,
    )])
    service = AgentSessionService(store=store, registry=registry)
    record = asyncio.run(service.start_session(_start(
        harness_id="does-not-exist", mode="invalid", model="stale-model",
        spec_name="fake-throughput",
    )))

    assert record.harness == "fake"
    assert record.provider_profile == "throughput"
    assert record.model is None
    assert harness.request is not None
    assert harness.request.instructions == "Use the packet as the sole source of truth."
    assert harness.request.effort == "xhigh"
    assert store.events_since(record.session_id)[0].payload == {
        "mode": "workspace",
        "spec_name": "fake-throughput",
    }

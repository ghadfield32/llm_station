"""AGT-15 offline adapter bench.

The existing `.github/workflows/contracts.yml` `pytest` step invokes this file;
CI therefore runs only FakeHarness observations and keeps DRIFT report-only.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from command_center.agent_sessions.adapters.codex_agent import CodexAgentHarness
from command_center.agent_sessions.adapters.openrouter_agent import OpenRouterAgentHarness
from command_center.agent_sessions.bench.models import (
    CORE_DIMENSIONS,
    BenchProfile,
    Dimension,
    ProbeResult,
    Verdict,
)
from command_center.agent_sessions.bench.probes import PROBES
from command_center.agent_sessions.bench.profiles import (
    assert_profile_registry_coverage,
    discover_bench_profiles,
)
from command_center.agent_sessions.bench.reconcile import (
    reconcile,
    registry_declaration_drifts,
)
from command_center.agent_sessions.bench.render import build_report, write_report
from command_center.agent_sessions.bench.runner import run_bench
from command_center.agent_sessions.fake_harness import FakeHarness
from command_center.agent_sessions.registry import HarnessDescriptor, default_registry
from command_center.agent_sessions.store import SessionStore


def _fake_results() -> list[ProbeResult]:
    async def run() -> list[ProbeResult]:
        store = SessionStore()
        harness = FakeHarness(store)
        return [await probe(harness, store, repo_id="unused") for probe in PROBES]

    return asyncio.run(run())


def test_each_fake_probe_earns_expected_observed_verdict():
    results = {result.dimension: result for result in _fake_results()}
    assert {dimension: result.observed_verdict for dimension, result in results.items()} == {
        Dimension.STREAMING: Verdict.PARTIAL,
        Dimension.RESUME: Verdict.PARTIAL,
        Dimension.WRITE_MODE_WALL: Verdict.PASS,
        Dimension.ATTACHMENTS: Verdict.SKIPPED,
        Dimension.MODEL_SWITCH: Verdict.SKIPPED,
    }
    assert all(result.detail for result in results.values())


def test_declared_not_observed_capability_becomes_drift():
    wrong = FakeHarness.bench_profile.model_copy(
        update={"streaming": Verdict.PASS})
    cells = reconcile(wrong, _fake_results())
    streaming = next(cell for cell in cells if cell.dimension is Dimension.STREAMING)
    assert streaming.declared is Verdict.PASS
    assert streaming.observed is Verdict.PARTIAL
    assert streaming.verdict is Verdict.DRIFT


def test_real_adapters_are_skipped_offline_never_unobserved_passes():
    cells = asyncio.run(run_bench())
    real_cells = [cell for cell in cells if cell.adapter != "fake"]
    assert len(real_cells) == 4 * len(CORE_DIMENSIONS)
    assert all(cell.observed is Verdict.SKIPPED for cell in real_cells)
    assert not any(cell.verdict is Verdict.PASS for cell in real_cells)
    assert all("not probed offline" in cell.detail for cell in real_cells)


def test_matrix_json_schema_is_stable_and_written_under_generated():
    cells = asyncio.run(run_bench())
    report = build_report(live=False, cells=cells)
    output = write_report(
        report, Path("generated/adapter-capability-matrix.json"))
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert output.parent.name == "generated"
    assert list(payload) == [
        "schema_version", "mode", "dimensions", "cells", "summary"]
    assert payload["schema_version"] == 1
    assert payload["mode"] == "offline"
    assert payload["dimensions"] == [dimension.value for dimension in CORE_DIMENSIONS]
    assert len(payload["cells"]) == 5 * len(CORE_DIMENSIONS)
    assert list(payload["cells"][0]) == [
        "adapter", "dimension", "declared", "observed", "verdict", "detail"]
    assert Verdict.FAIL.value not in [cell["verdict"] for cell in payload["cells"]]


def test_seeded_registry_declaration_mismatch_becomes_drift():
    store = SessionStore()
    harness = CodexAgentHarness(store)
    descriptor = HarnessDescriptor(
        harness_id="codex_agent",
        label="seeded mismatch",
        production=True,
        supported_modes=("analysis",),
        factory=lambda: harness,
    )
    wrong = harness.bench_profile.model_copy(
        update={"write_mode_wall": Verdict.FAIL})
    static_drifts = registry_declaration_drifts(wrong, descriptor, harness)
    skipped = [
        ProbeResult(
            dimension=dimension,
            observed_verdict=Verdict.SKIPPED,
            detail="runtime not probed in seeded declaration test",
        )
        for dimension in CORE_DIMENSIONS
    ]
    cells = reconcile(wrong, skipped, static_drifts)
    wall = next(cell for cell in cells if cell.dimension is Dimension.WRITE_MODE_WALL)
    assert wall.observed is Verdict.SKIPPED
    assert wall.verdict is Verdict.DRIFT
    assert "registry supports analysis mode only" in wall.detail


def test_external_egress_contradicts_unqualified_attachment_pass():
    store = SessionStore()
    harness = OpenRouterAgentHarness(store)
    descriptor = HarnessDescriptor(
        harness_id="openrouter_agent",
        label="seeded attachment mismatch",
        production=True,
        supported_modes=("analysis",),
        factory=lambda: harness,
    )
    wrong = harness.bench_profile.model_copy(
        update={"attachments": Verdict.PASS})
    drifts = registry_declaration_drifts(wrong, descriptor, harness)
    assert "external_egress=True" in drifts[Dimension.ATTACHMENTS]


def test_every_registry_harness_has_exactly_one_profile_and_vice_versa():
    store = SessionStore()
    registry = default_registry(store)
    profiles = discover_bench_profiles()
    assert_profile_registry_coverage(registry, profiles)
    assert set(profiles) == {
        "fake",
        "codex_agent",
        "claude_code_local",
        "claude_agent",
        "openrouter_agent",
    }

    orphan = BenchProfile(
        adapter="orphan",
        streaming=Verdict.FAIL,
        resume=Verdict.FAIL,
        write_mode_wall=Verdict.FAIL,
        attachments=Verdict.FAIL,
        model_switch=Verdict.FAIL,
    )
    with pytest.raises(ValueError, match="orphaned=.*orphan"):
        assert_profile_registry_coverage(registry, {**profiles, "orphan": orphan})

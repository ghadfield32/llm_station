"""Offline/live bench orchestration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..protocol import AgentHarness
from ..registry import default_registry
from ..store import SessionStore, SessionStoreProtocol
from .models import Cell, Dimension, ProbeResult, Verdict
from .probes import PROBES
from .profiles import assert_profile_registry_coverage, discover_bench_profiles
from .reconcile import reconcile, registry_declaration_drifts

Probe = Callable[..., Awaitable[ProbeResult]]

_OFFLINE_SKIP_REASONS = {
    "codex_agent": "codex SDK runtime not probed offline",
    "claude_code_local": "Claude Code subprocess runtime not probed offline",
    "claude_agent": "Claude Agent SDK/network runtime not probed offline",
    "openrouter_agent": "OpenRouter network runtime not probed offline",
}


def _skipped_results(reason: str) -> list[ProbeResult]:
    return [
        ProbeResult(
            dimension=dimension,
            observed_verdict=Verdict.SKIPPED,
            detail=reason,
        )
        for dimension in Dimension
    ]


async def _run_probes(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for probe in PROBES:
        dimension = Dimension(probe.__name__.removeprefix("probe_"))
        try:
            results.append(await probe(harness, store, repo_id=repo_id))
        except Exception as exc:
            results.append(ProbeResult(
                dimension=dimension,
                observed_verdict=Verdict.FAIL,
                detail=(
                    f"{dimension.value} observation raised "
                    f"{type(exc).__name__}: {exc}"
                ),
            ))
    return results


async def run_bench(*, live: bool = False, repo_id: str = "llm_station") -> list[Cell]:
    """Run all adapters; the default observes only FakeHarness."""
    store = SessionStore()
    registry = default_registry(store)
    profiles = discover_bench_profiles()
    assert_profile_registry_coverage(registry, profiles)

    cells: list[Cell] = []
    for descriptor in registry.descriptors():
        harness = descriptor.factory()
        profile = profiles[descriptor.harness_id]
        if not live and descriptor.production:
            results = _skipped_results(_OFFLINE_SKIP_REASONS[descriptor.harness_id])
        elif live:
            availability = await harness.probe()
            if not availability.available:
                results = _skipped_results(
                    f"{descriptor.harness_id} runtime unavailable: {availability.detail}")
            else:
                results = await _run_probes(harness, store, repo_id=repo_id)
        else:
            results = await _run_probes(harness, store, repo_id=repo_id)

        static_drifts = registry_declaration_drifts(profile, descriptor, harness)
        cells.extend(reconcile(profile, results, static_drifts))

        shutdown = getattr(harness, "shutdown", None)
        if live and callable(shutdown):
            await shutdown()
    return cells

"""Declared-vs-observed reconciliation and static declaration cross-checks."""
from __future__ import annotations

from collections.abc import Mapping

from ..registry import HarnessDescriptor
from .models import BenchProfile, Cell, Dimension, ProbeResult, Verdict

_CAPABILITY_RANK = {
    Verdict.FAIL: 0,
    Verdict.PARTIAL: 1,
    Verdict.PASS: 2,
}


def reconcile(
    profile: BenchProfile,
    probe_results: list[ProbeResult],
    declaration_drifts: Mapping[Dimension, str] | None = None,
) -> list[Cell]:
    """Reconcile claims with event evidence and explicit static contradictions."""
    by_dimension = {result.dimension: result for result in probe_results}
    if len(by_dimension) != len(probe_results):
        raise ValueError("duplicate probe result for a core dimension")
    missing = [d.value for d in Dimension if d not in by_dimension]
    if missing:
        raise ValueError(f"missing probe results: {', '.join(missing)}")

    static_drifts = declaration_drifts or {}
    cells: list[Cell] = []
    for dimension in Dimension:
        result = by_dimension[dimension]
        declared = profile.verdict_for(dimension)
        observed = result.observed_verdict
        static_detail = static_drifts.get(dimension)
        if static_detail:
            verdict = Verdict.DRIFT
            detail = f"{result.detail}; declaration cross-check: {static_detail}"
        elif observed is Verdict.SKIPPED:
            verdict = Verdict.SKIPPED
            detail = result.detail
        elif (
            declared in (Verdict.PASS, Verdict.PARTIAL)
            and _CAPABILITY_RANK[observed] < _CAPABILITY_RANK[declared]
        ):
            verdict = Verdict.DRIFT
            detail = (
                f"declared {declared.value} but observed {observed.value}: "
                f"{result.detail}")
        else:
            verdict = observed
            detail = result.detail
        cells.append(Cell(
            adapter=profile.adapter,
            dimension=dimension,
            declared=declared,
            observed=observed,
            verdict=verdict,
            detail=detail,
        ))
    return cells


def registry_declaration_drifts(
    profile: BenchProfile,
    descriptor: HarnessDescriptor,
    harness: object,
) -> dict[Dimension, str]:
    """Return contradictions between the harness profile and registry facts."""
    drifts: dict[Dimension, str] = {}
    modes = set(descriptor.supported_modes)
    interactive = bool(getattr(harness, "interactive_approvals", True))
    external_egress = bool(getattr(harness, "external_egress", False))

    if profile.write_mode_wall is Verdict.FAIL and modes == {"analysis"}:
        drifts[Dimension.WRITE_MODE_WALL] = (
            "profile claims FAIL but registry supports analysis mode only")
    elif profile.write_mode_wall is Verdict.FAIL and interactive:
        drifts[Dimension.WRITE_MODE_WALL] = (
            "profile claims FAIL but harness declares interactive_approvals=True")

    if profile.attachments is Verdict.PASS and external_egress:
        drifts[Dimension.ATTACHMENTS] = (
            "profile claims unqualified PASS but harness declares external_egress=True")

    return drifts

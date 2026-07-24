"""Model-switch probe: requested selections must appear in session events."""
from __future__ import annotations

import inspect
from typing import Any

from ...protocol import AgentHarness
from ...store import SessionStoreProtocol
from ..models import Dimension, ProbeResult, Verdict
from .common import start_analysis_session


async def probe_model_switch(
    harness: AgentHarness,
    store: SessionStoreProtocol,
    *,
    repo_id: str,
) -> ProbeResult:
    list_models = getattr(harness, "list_models", None)
    if list_models is None:
        return ProbeResult(
            dimension=Dimension.MODEL_SWITCH,
            observed_verdict=Verdict.SKIPPED,
            detail=f"{getattr(harness, 'name', 'harness')} exposes no model catalog to probe",
        )
    catalog_result = list_models()
    catalog: list[dict[str, Any]] = (
        await catalog_result if inspect.isawaitable(catalog_result) else catalog_result)
    model_ids = [
        str(item["id"]) for item in catalog
        if item.get("available", True) and item.get("id")
    ]
    if len(model_ids) < 2:
        return ProbeResult(
            dimension=Dimension.MODEL_SWITCH,
            observed_verdict=Verdict.SKIPPED,
            detail=f"runtime exposed fewer than two available models: {model_ids}",
        )

    requested = model_ids[:2]
    observed: list[object] = []
    for model in requested:
        session_id = await start_analysis_session(
            harness, repo_id=repo_id, model=model)
        started = next(
            event for event in store.events_since(session_id)
            if event.type == "session_started"
        )
        observed.append(started.payload.get("model"))
    if observed == requested:
        verdict = Verdict.PASS
        detail = f"observed distinct requested models in session events: {observed}"
    else:
        verdict = Verdict.FAIL
        detail = f"requested models {requested}, observed session models {observed}"
    return ProbeResult(
        dimension=Dimension.MODEL_SWITCH,
        observed_verdict=verdict,
        detail=detail,
    )

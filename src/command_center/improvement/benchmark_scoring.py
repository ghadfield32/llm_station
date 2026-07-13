"""Shared rule-based case scoring for the frontier-router and local-frontier continual KPI
harnesses (frontier_benchmark.py / local_frontier_benchmark.py). Extracted so both apply the
EXACT SAME rubric — the same checks the case author wrote for local incumbents — rather than
maintaining two copies that could silently drift."""
from __future__ import annotations

import json
from typing import Any


def score_case(case, content: str) -> dict[str, Any]:
    """Rule-based scoring against the case's OWN declared expectations. No judge model, no
    fabricated quality number; a case either matches its declared contract or it doesn't."""
    ok = True
    reasons: list[str] = []
    parsed: dict | None = None
    if case.response_format == "json":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            ok = False
            reasons.append("response is not valid JSON")
        if parsed is not None:
            for key in case.required_json_keys:
                if key not in parsed:
                    ok = False
                    reasons.append(f"missing required key {key!r}")
            for key, expected in case.expected_json_values.items():
                if parsed.get(key) != expected:
                    ok = False
                    reasons.append(f"{key}={parsed.get(key)!r} != expected {expected!r}")
    for needle in case.expected_contains:
        if needle not in content:
            ok = False
            reasons.append(f"missing expected substring {needle!r}")
    for needle in case.forbidden_contains:
        if needle in content:
            ok = False
            reasons.append(f"contains forbidden substring {needle!r}")
    return {"case_id": case.id, "ok": ok, "reasons": reasons, "safety": case.safety,
            "metric_tags": case.metric_tags}

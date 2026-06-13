"""
The discovery scan's tunable knobs — externalized so no ranking/triage decision is an inline
literal (PIPELINE_STANDARDS "data-derived decisions, no hardcoded thresholds"; an explicit,
documented config knob is the sanctioned form, "a config knob, not in-line magic").

`configs/discovery.yaml` is the editable source of truth, validated by `DiscoveryConfig`. The
CONTRACT classes live in `..schema` (beside the other improvement contracts, importable by
`make validate` without pulling the heavy discovery package); this module is just the yaml
LOADER and re-exports the contract for convenience.

Genuine data-derivation (learning the ranking from outcomes rather than asserting it) lives in
`acceptance.py`; these knobs are the documented operating point and the formula baseline.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..schema import (
    AcceptanceKnobs, CodeHealthKnobs, DiscoveryConfig, RankingKnobs, TriageKnobs,
)

__all__ = [
    "AcceptanceKnobs", "CodeHealthKnobs", "DiscoveryConfig", "RankingKnobs", "TriageKnobs",
    "load_discovery_config",
]

_DEFAULT_PATH = "configs/discovery.yaml"
_CACHE: dict[str, DiscoveryConfig] = {}


def load_discovery_config(path: str | Path = _DEFAULT_PATH) -> DiscoveryConfig:
    """Load + validate the discovery config. The file is the source of truth; if it is absent
    the contract defaults apply (so a fresh checkout still runs). Cached per path."""
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    p = Path(path)
    if p.exists():
        cfg = DiscoveryConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
    else:
        cfg = DiscoveryConfig(schema_version="1.0")
    _CACHE[key] = cfg
    return cfg

"""UsageMonitoringConfig contract invariants — including the structural
refusal of allow_silent_fallback=true (KPI: silent fallbacks = 0) and the
real configs/usage-monitoring.yaml validating.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from command_center.schemas import UsageMonitoringConfig

REPO_ROOT = Path(__file__).resolve().parents[1]

_BASE = {
    "schema_version": "command-center.usage-monitoring.v1",
    "enabled": True,
    "thresholds": {"warning_percent": 75, "critical_percent": 90},
    "polling": {"active_session_seconds": 30, "idle_seconds": 300},
    "routing": {"block_when_exhausted": True, "allow_silent_fallback": False,
                "reserve_capacity_for_high_risk_missions": True},
    "alerts": {"cockpit": True, "chat_notification": True, "ledger": True,
               "email_digest": True},
}


def test_real_config_file_validates():
    cfg = UsageMonitoringConfig.model_validate(
        yaml.safe_load((REPO_ROOT / "configs/usage-monitoring.yaml").read_text()))
    assert cfg.schema_version == "command-center.usage-monitoring.v1"
    assert cfg.routing.allow_silent_fallback is False


def test_wrong_schema_version_rejected():
    bad = {**_BASE, "schema_version": "nope"}
    with pytest.raises(ValueError, match="schema_version"):
        UsageMonitoringConfig.model_validate(bad)


def test_critical_below_warning_rejected():
    bad = {**_BASE, "thresholds": {"warning_percent": 90, "critical_percent": 75}}
    with pytest.raises(ValueError, match="critical_percent must be >= warning_percent"):
        UsageMonitoringConfig.model_validate(bad)


def test_allow_silent_fallback_true_is_structurally_refused():
    bad = {**_BASE, "routing": {**_BASE["routing"], "allow_silent_fallback": True}}
    with pytest.raises(ValueError, match="allow_silent_fallback must be false"):
        UsageMonitoringConfig.model_validate(bad)


def test_extra_keys_are_forbidden():
    bad = {**_BASE, "surprise": 1}
    with pytest.raises(ValueError):
        UsageMonitoringConfig.model_validate(bad)

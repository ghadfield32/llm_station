"""Contract regression tests.

Deterministic, no network, no model calls. They prove the shipped configs still
satisfy their contracts and that the channel registry is internally consistent —
the same guarantees `make validate` gives, pinned in CI via `pytest`.

Run from the repo root (pytest's default working dir): the contracts reference
configs/ by repo-relative path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from command_center.schemas import CONFIG_CONTRACTS
from command_center.schemas.contracts import ProactiveConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str) -> dict:
    return yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_every_config_validates_against_its_contract():
    for rel, contract in CONFIG_CONTRACTS.items():
        contract.model_validate(_load(rel))


def test_channels_yaml_is_registered():
    assert "configs/channels.yaml" in CONFIG_CONTRACTS


def test_each_channel_model_is_a_real_role():
    roles = set((_load("configs/models.yaml").get("roles") or {}).keys())
    for ch in _load("configs/channels.yaml").get("channels", []):
        assert ch["model"] in roles, (
            f"channel {ch['name']!r} routes to model {ch['model']!r} "
            "which is not a role in models.yaml"
        )


def test_gateway_core_imports_without_transport_sdks():
    # core must import on a base install (no discord/slack/fastapi needed)
    from command_center.channels.core import GatewayConfig, GatewayCore, build_system

    assert "Growth OS gateway on Slack" in build_system("Slack")
    # the two deterministic guards selftest.py asserts on must stay present
    src = (REPO_ROOT / "src/command_center/channels/core.py").read_text(encoding="utf-8")
    assert "already called this with identical" in src
    assert "Tool budget exhausted" in src
    assert GatewayConfig and GatewayCore


def test_daily_self_improvement_scan_is_observer_only():
    cfg = ProactiveConfig.model_validate(_load("configs/proactive.yaml"))
    scans = {s.name: s for s in cfg.self_improvement_scans}
    scan = scans["daily-self-improvement-brief"]
    assert scan.observer_only
    assert scan.uses_existing_approval_wall
    assert scan.independent_verifier_required
    assert set(scan.write_scopes) == {"backlog_cards", "report_artifact"}
    assert set(scan.output_artifacts) == {"backlog_cards", "decision_report"}
    assert scan.max_generated_experiment_risk.value == "L2_local_edits"


def test_daily_self_improvement_scan_cannot_generate_external_write_work():
    raw = _load("configs/proactive.yaml")
    raw["self_improvement_scans"][0]["max_generated_experiment_risk"] = "L3_external_write"
    with pytest.raises(ValueError, match="cannot generate L3/L4"):
        ProactiveConfig.model_validate(raw)


def test_daily_self_improvement_scan_cannot_add_extra_artifacts():
    raw = _load("configs/proactive.yaml")
    raw["self_improvement_scans"][0]["output_artifacts"] = ["decision_report"]
    with pytest.raises(ValueError, match="may write only"):
        ProactiveConfig.model_validate(raw)

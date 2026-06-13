"""
The discovery config (configs/discovery.yaml → DiscoveryConfig): every scan decision is a
validated, documented config knob — not an inline literal. Verifies the contract, the loader,
and that the pipeline/scanners actually source their operating point from it.
"""
from __future__ import annotations

import pytest
import yaml

from command_center.improvement.discovery import (
    CodeHealthScanner, ObserverCharter, ScanPipeline,
)
from command_center.improvement.discovery.config import load_discovery_config
from command_center.improvement.discovery.sources import CodeHealthThresholds
from command_center.improvement.schema import DiscoveryConfig
from command_center.improvement.registry import ExperimentRegistry


def test_repo_discovery_yaml_validates():
    # the checked-in configs/discovery.yaml must validate (and is wired into make validate)
    cfg = load_discovery_config("configs/discovery.yaml")
    assert isinstance(cfg, DiscoveryConfig)
    assert cfg.ranking.default_method in ("ice", "rice", "wsjf", "voi")


def test_contract_is_registered_in_config_contracts():
    from command_center.schemas import CONFIG_CONTRACTS
    assert CONFIG_CONTRACTS["configs/discovery.yaml"] is DiscoveryConfig


def test_defaults_apply_when_file_absent(tmp_path):
    cfg = load_discovery_config(tmp_path / "nope.yaml")   # absent → contract defaults
    assert cfg.ranking.default_method == "wsjf"
    assert cfg.triage.min_confidence == 0.4
    assert cfg.triage.max_cards == 20
    assert cfg.code_health.max_function_statements == 60


def _write_cfg(tmp_path, **triage) -> str:
    body = {"schema_version": "1.0", "ranking": {"default_method": "ice"},
            "triage": {"min_confidence": 0.6, "cooldown_hours": 12.0, "max_cards": 3}}
    body["triage"].update(triage)
    p = tmp_path / "discovery.yaml"
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    return str(p)


def test_pipeline_sources_operating_point_from_config(tmp_path):
    cfg = load_discovery_config(_write_cfg(tmp_path))
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    pipe = ScanPipeline(ObserverCharter(reg, report_path=tmp_path / "r.md"), config=cfg)
    assert pipe.method == "ice"                 # from config, not a literal default
    assert pipe.max_cards == 3
    assert pipe.triage.min_confidence == 0.6
    assert pipe.triage.cooldown_hours == 12.0
    assert pipe.confidence_half_width == 0.15   # ranking default


def test_explicit_args_still_override_config(tmp_path):
    cfg = load_discovery_config(_write_cfg(tmp_path))
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    pipe = ScanPipeline(ObserverCharter(reg, report_path=tmp_path / "r.md"),
                        config=cfg, method="wsjf", max_cards=7)
    assert pipe.method == "wsjf" and pipe.max_cards == 7


def test_invalid_config_fails_validation():
    with pytest.raises(ValueError):
        DiscoveryConfig.model_validate(
            {"schema_version": "1.0", "triage": {"min_confidence": 1.4}})   # > 1
    with pytest.raises(ValueError):
        DiscoveryConfig.model_validate(
            {"schema_version": "1.0", "ranking": {"default_method": "bogus"}})
    with pytest.raises(ValueError):
        DiscoveryConfig.model_validate(
            {"schema_version": "1.0", "extra_field": True})                 # Strict: extra forbidden


def test_code_health_thresholds_from_config_round_trip():
    knobs = DiscoveryConfig(schema_version="1.0").code_health
    t = CodeHealthThresholds.from_config(knobs)
    assert t.max_function_statements == knobs.max_function_statements
    assert t.min_swallowed_excepts == knobs.min_swallowed_excepts
    # and the offline scanner accepts it
    assert CodeHealthScanner("src", thresholds=t).t.max_module_lines == knobs.max_module_lines


def test_confidence_band_width_flows_into_report(tmp_path):
    # a wider band knob produces a visibly wider band in the rendered report
    from command_center.improvement.discovery import Finding, Pillar
    from command_center.improvement.discovery.report import render_report
    f = Finding(pillar=Pillar.CODE_QUALITY, source="t", title="x", claim="c",
                evidence="e", confidence=0.6)
    narrow = render_report(date="d", method="wsjf", ranked_drafts=[(f, 1.0)],
                           triage_results=[], outcomes=[], drafted_ids={f.experiment_id},
                           confidence_half_width=0.05)
    wide = render_report(date="d", method="wsjf", ranked_drafts=[(f, 1.0)],
                         triage_results=[], outcomes=[], drafted_ids={f.experiment_id},
                         confidence_half_width=0.30)
    assert "0.55–0.65" in narrow      # 0.6 ± 0.05
    assert "0.30–0.90" in wide        # 0.6 ± 0.30

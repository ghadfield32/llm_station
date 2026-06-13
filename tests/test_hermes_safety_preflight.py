"""Offline tests for the Hermes spike isolation preflight (WS4).

Schema verified against the installed Hermes v0.16.0 (provider + base_url +
api_key + model + custom_providers; there is NO data_collection key). The
preflight is the gate that must pass before the pre-1.0 agent launches; these
tests prove it accepts a correctly-isolated config and flags every violation.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "evaluation" / "capability-assessment" / "hermes"))

from safety_preflight import check_hermes_isolation  # noqa: E402


def _good() -> dict:
    return {
        "provider": "custom",
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
        "model": "qwen3-coder:30b",
        "custom_providers": [
            {"name": "local-ollama", "base_url": "http://localhost:11434/v1", "api_key": ""},
        ],
    }


def test_isolated_config_passes():
    assert check_hermes_isolation(_good()) == []


def test_auto_provider_is_flagged():
    # auto-resolution never selects a local provider -> falls through to cloud
    cfg = _good()
    cfg["provider"] = "auto"
    assert any("provider" in p for p in check_hermes_isolation(cfg))


def test_cloud_provider_is_flagged():
    cfg = _good()
    cfg["provider"] = "openrouter"
    assert any("provider" in p for p in check_hermes_isolation(cfg))


def test_litellm_proxy_endpoint_is_flagged_for_hang_bug():
    cfg = _good()
    cfg["base_url"] = "http://localhost:4000/v1"   # LiteLLM proxy
    problems = check_hermes_isolation(cfg)
    assert any("#26489" in p for p in problems)
    assert any(":11434" in p for p in problems)


def test_remote_endpoint_is_flagged():
    cfg = _good()
    cfg["base_url"] = "http://192.168.1.50:11434/v1"
    assert any("local host" in p for p in check_hermes_isolation(cfg))


def test_provider_api_key_is_flagged():
    cfg = _good()
    cfg["api_key"] = "sk-real-secret-key"
    assert any("api_key" in p for p in check_hermes_isolation(cfg))


def test_empty_model_is_flagged():
    cfg = _good()
    cfg["model"] = ""
    assert any("model" in p for p in check_hermes_isolation(cfg))


def test_custom_provider_remote_base_url_is_flagged():
    cfg = _good()
    cfg["custom_providers"][0]["base_url"] = "https://api.openai.com/v1"
    problems = check_hermes_isolation(cfg)
    assert any("custom_providers[0]" in p for p in problems)


def test_empty_config_flags_multiple_axes_not_just_one():
    # an unset config must fail loudly on multiple axes, never silently pass
    problems = check_hermes_isolation({})
    assert len(problems) >= 3

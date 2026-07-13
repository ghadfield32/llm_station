"""
The model roster lifecycle surface: the `status` field on ModelCandidate, render
routing only `active` candidates (scout = watchlist, not routed), and the
operator verbs (status / canary / human-gated promote) in cli.model_ops.
"""
from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError

from command_center.cli import model_ops
from command_center.registry.render import build
from command_center.schemas import ModelRegistry


def _cand(alias, model, priority, **kw):
    base = {"alias": alias, "provider": "ollama", "model": model,
            "priority": priority, "local": True}
    base.update(kw)
    return base


def _registry(roles):
    return ModelRegistry.model_validate(
        {"schema_version": "command-center.models.v1", "roles": roles}
    )


# ── schema: status field ─────────────────────────────────────────────

def test_status_defaults_to_active():
    reg = _registry({"coder": [_cand("a", "m:1", 1)]})
    assert reg.roles["coder"][0].status == "active"


def test_scout_candidate_is_valid_alongside_active():
    reg = _registry({"coder": [
        _cand("a", "m:1", 1, status="active"),
        _cand("b", "m:2", 2, status="scout"),
    ]})
    assert [c.status for c in reg.roles["coder"]] == ["active", "scout"]


def test_all_scout_role_is_rejected():
    with pytest.raises(ValidationError, match="no active candidate"):
        _registry({"coder": [_cand("a", "m:1", 1, status="scout")]})


def test_scout_candidate_cannot_be_canary():
    with pytest.raises(ValidationError, match="scout but has canary_weight"):
        _registry({"coder": [
            _cand("a", "m:1", 1, status="active"),
            _cand("b", "m:2", 2, status="scout", canary_weight=0.1),
        ]})


# ── render: only active candidates are routed ─────────────────────────

def test_render_skips_scout_candidates():
    reg = _registry({"coder": [
        _cand("act", "active-model:1", 1, status="active"),
        _cand("sct", "scout-model:2", 2, status="scout"),
    ]})
    out = build(reg, canary={}, promote=set())
    assert "ollama_chat/active-model:1" in out
    assert "scout-model:2" not in out


# ── status (read-only) ────────────────────────────────────────────────

def test_run_status_reports_roles_and_counts(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({
        "schema_version": "command-center.models.v1",
        "roles": {"coder": [
            _cand("act", "m:1", 1, status="active"),
            _cand("sct", "m:2", 2, status="scout"),
        ]},
    }), encoding="utf-8")
    result = model_ops.run_status(path=p)
    assert result["status"] == "ok"
    assert result["active_total"] == 1
    assert result["scout_total"] == 1
    aliases = [c["alias"] for c in result["roles"][0]["candidates"]]
    assert aliases == ["act", "sct"]


# ── canary ────────────────────────────────────────────────────────────

def test_canary_rejects_non_local_model(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({
        "schema_version": "command-center.models.v1",
        "roles": {"coder": [_cand("a", "m:1", 1)]},
    }), encoding="utf-8")
    result = model_ops.run_canary(role="coder", model="openai/gpt", path=p)
    assert result["status"] == "blocked"
    assert any("ollama_chat/" in b for b in result["blockers"])


def test_canary_rejects_unknown_role(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({
        "schema_version": "command-center.models.v1",
        "roles": {"coder": [_cand("a", "m:1", 1)]},
    }), encoding="utf-8")
    result = model_ops.run_canary(role="nope", model="ollama_chat/m:1", path=p)
    assert result["status"] == "blocked"
    assert any("unknown role" in b for b in result["blockers"])


def test_canary_dry_run_ok_without_applying(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump({
        "schema_version": "command-center.models.v1",
        "roles": {"coder": [_cand("a", "m:1", 1)]},
    }), encoding="utf-8")
    result = model_ops.run_canary(role="coder", model="ollama_chat/qwen3-coder:30b",
                                  weight=0.1, apply=False, path=p)
    assert result["status"] == "ok"
    assert result["applied"] is False
    assert "--canary" in result["render_cmd"]


# ── promote (human-gated) ─────────────────────────────────────────────

SCOUT_YAML = """\
schema_version: command-center.models.v1
# keep this comment
roles:
  coder:
    - {alias: coder-local, provider: ollama, model: "qwen3-coder:30b", priority: 1, local: true, status: active}
    - {alias: coder-cand, provider: ollama, model: "devstral:24b", priority: 2, local: true, status: scout}
"""


def _scout_models(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(SCOUT_YAML, encoding="utf-8")
    return p


def test_promote_blocks_without_approver(tmp_path):
    p = _scout_models(tmp_path)
    result = model_ops.run_promote(role="coder", candidate="coder-cand", approver="", path=p)
    assert result["status"] == "blocked"
    assert any("approver" in b for b in result["blockers"])
    assert "status: scout" in p.read_text(encoding="utf-8")  # unchanged


def test_promote_dry_run_does_not_write(tmp_path):
    p = _scout_models(tmp_path)
    result = model_ops.run_promote(role="coder", candidate="coder-cand",
                                   approver="geoff", apply=False, path=p)
    assert result["status"] == "dry_run"
    assert result["applied"] is False
    assert "status: scout" in p.read_text(encoding="utf-8")  # still not flipped


def test_promote_apply_flips_scout_to_active_and_preserves_rest(tmp_path):
    p = _scout_models(tmp_path)
    result = model_ops.run_promote(role="coder", candidate="coder-cand",
                                   approver="geoff", apply=True, path=p, root=tmp_path)
    assert result["status"] == "promoted"
    text = p.read_text(encoding="utf-8")
    assert "# keep this comment" in text                      # comment preserved
    assert "status: scout" not in text                        # flipped
    assert text.count("status: active") == 2                  # both now active
    # re-validates clean + writes evidence
    ModelRegistry.model_validate(yaml.safe_load(text))
    ev = tmp_path / result["evidence"]
    assert json.loads(ev.read_text(encoding="utf-8"))["approver"] == "geoff"


def test_promote_already_active_is_noop(tmp_path):
    p = _scout_models(tmp_path)
    result = model_ops.run_promote(role="coder", candidate="coder-local", approver="geoff", path=p)
    assert result["status"] == "already_active"


def test_flip_status_only_touches_target_line():
    text = (
        "    - {alias: a, model: x, status: scout}\n"
        "    - {alias: b, model: y, status: scout}\n"
    )
    out, changed = model_ops._flip_status_to_active(text, "b")
    assert changed
    assert out.splitlines()[0] == "    - {alias: a, model: x, status: scout}"  # untouched
    assert "alias: b, model: y, status: active" in out

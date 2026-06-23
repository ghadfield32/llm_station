"""Verified-provenance tests for the capability catalog.

Two halves, mirroring the implementation: the schema *requires* a digest on
local provenance for tamper-relevant capabilities, and the verifier *recomputes*
that digest and fails on drift. The checked-in configs/capabilities.yaml must
satisfy both — pinned here so it can't regress in CI.
"""
import pytest
import yaml
from pydantic import ValidationError

from command_center.cli.capability_digest import (
    ROOT,
    compute_artifact_digest,
    verify_capability_digests,
)
from command_center.schemas import CapabilityCatalogConfig
from command_center.schemas.contracts import digest_required_for, source_ref_kind


def _catalog_data():
    return yaml.safe_load(open("configs/capabilities.yaml", encoding="utf-8"))


def _entry(data, type_):
    return next(e for e in data["entries"] if e["type"] == type_)


# ---- the checked-in catalog satisfies both halves --------------------------

def test_real_catalog_validates_and_verifies():
    cfg = CapabilityCatalogConfig.model_validate(_catalog_data())
    assert verify_capability_digests(cfg, ROOT) == []


def test_skill_entry_actually_pins_a_digest():
    # guards against the rule being vacuous: at least one in-scope entry exercises it
    skill = _entry(_catalog_data(), "skill")
    assert digest_required_for(skill["type"], skill["risk_tier"])
    assert any(p.get("digest") for p in skill["provenance"])


# ---- schema: require digest on local provenance ----------------------------

def test_missing_digest_on_inscope_local_ref_fails():
    data = _catalog_data()
    skill = _entry(data, "skill")
    for prov in skill["provenance"]:
        prov.pop("digest", None)
    with pytest.raises(ValidationError, match="must pin a digest"):
        CapabilityCatalogConfig.model_validate(data)


def test_bad_digest_format_fails():
    data = _catalog_data()
    _entry(data, "skill")["provenance"][0]["digest"] = "sha256:notreallyahash"
    with pytest.raises(ValidationError, match="sha256:<64 lowercase hex>"):
        CapabilityCatalogConfig.model_validate(data)


def test_out_of_scope_type_does_not_require_digest():
    # a `tool` entry with a local provenance ref and no digest stays valid:
    # the requirement is scoped to skill/mcp_server/model_candidate.
    data = _catalog_data()
    tool = _entry(data, "tool")
    assert any(source_ref_kind(p["source_ref"]) == "local" for p in tool["provenance"])
    assert not any(p.get("digest") for p in tool["provenance"])
    CapabilityCatalogConfig.model_validate(data)  # does not raise


def test_remote_provenance_is_exempt_from_requirement():
    # model_candidate is in scope, but its remote (URL) refs need no digest.
    data = _catalog_data()
    mc = _entry(data, "model_candidate")
    remote = [p for p in mc["provenance"] if source_ref_kind(p["source_ref"]) == "remote"]
    assert remote and not any(p.get("digest") for p in remote)
    CapabilityCatalogConfig.model_validate(data)  # does not raise


# ---- verifier: recompute and detect drift ----------------------------------

def test_verifier_detects_digest_drift():
    cfg = CapabilityCatalogConfig.model_validate(_catalog_data())
    # flip the recorded digest to a valid-format but wrong value
    skill = next(e for e in cfg.entries if e.type == "skill")
    prov = next(p for p in skill.provenance if p.digest)
    prov.digest = "sha256:" + "0" * 64
    problems = verify_capability_digests(cfg, ROOT)
    assert any("digest drift" in m for m in problems)


def test_verifier_flags_digest_on_unverifiable_remote_ref():
    data = _catalog_data()
    mc = _entry(data, "model_candidate")
    remote = next(p for p in mc["provenance"] if source_ref_kind(p["source_ref"]) == "remote")
    remote["digest"] = "sha256:" + "a" * 64
    cfg = CapabilityCatalogConfig.model_validate(data)
    problems = verify_capability_digests(cfg, ROOT)
    assert any("cannot be verified locally" in m for m in problems)


def test_verifier_flags_missing_artifact(tmp_path):
    cfg = CapabilityCatalogConfig.model_validate(_catalog_data())
    # an empty root => every local artifact is "missing"
    problems = verify_capability_digests(cfg, tmp_path)
    assert any("missing file" in m for m in problems)


# ---- the hashing helper itself ---------------------------------------------

def test_compute_whole_file_digest_is_raw_bytes(tmp_path):
    import hashlib
    f = tmp_path / "note.md"
    f.write_bytes(b"hello world\n")
    expected = "sha256:" + hashlib.sha256(b"hello world\n").hexdigest()
    assert compute_artifact_digest("note.md", tmp_path) == expected


def test_compute_fragment_digest_is_stable_against_unrelated_edits(tmp_path):
    base = {"tools": {"github": {"mode": "write"}, "shell": {"mode": "read"}}}
    f = tmp_path / "tools.yaml"
    f.write_text(yaml.safe_dump(base), encoding="utf-8")
    before = compute_artifact_digest("tools.yaml#tools.github", tmp_path)
    # edit an unrelated sibling; the github fragment digest must not move
    base["tools"]["shell"]["mode"] = "write"
    f.write_text(yaml.safe_dump(base), encoding="utf-8")
    after = compute_artifact_digest("tools.yaml#tools.github", tmp_path)
    assert before == after
    # but editing the targeted fragment does move it
    base["tools"]["github"]["mode"] = "read"
    f.write_text(yaml.safe_dump(base), encoding="utf-8")
    assert compute_artifact_digest("tools.yaml#tools.github", tmp_path) != before


def test_compute_rejects_non_local_ref(tmp_path):
    with pytest.raises(ValueError, match="not a local artifact"):
        compute_artifact_digest("https://example.com/x", tmp_path)

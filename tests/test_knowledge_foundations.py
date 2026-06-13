"""
OKF foundations: the strict growth-os-0.1 profile contract and the clobber-safe concept document
(generated block replaced on regenerate; human notes preserved; idempotent).
"""
from __future__ import annotations

import pytest

from command_center.knowledge import (
    Authority, OkfConcept, Sensitivity, SourceSystem, parse_concept, read_concept, write_concept,
)
from command_center.knowledge.document import ConceptParseError


def _concept(**kw) -> OkfConcept:
    base = dict(type="System", title="Risk tiers", description="L0–L4 permission model",
                resource="config://configs/gates.yaml", timestamp="2026-06-13T00:00:00Z",
                last_verified_at="2026-06-13T00:00:00Z", source_system=SourceSystem.CONFIG,
                source_path="configs/gates.yaml", owner="command-center")
    base.update(kw)
    return OkfConcept(**base)


# --------------------------------------------------------------------- profile

def test_concept_defaults_are_derived_and_profiled():
    c = _concept()
    assert c.profile == "growth-os-0.1" and c.okf_version == "0.1"
    assert c.authority is Authority.DERIVED      # the default: a projection, not the source
    assert c.generated_by == "growthos-okf-producer"


def test_profile_rejects_secret_and_bad_hash_and_unknown_fields():
    with pytest.raises(ValueError, match="SECRET"):
        _concept(sensitivity=Sensitivity.SECRET)
    with pytest.raises(ValueError, match="sha256"):
        _concept(source_hash="deadbeef")
    with pytest.raises(ValueError):
        _concept(resource="")                    # resource is required
    with pytest.raises(ValueError):
        OkfConcept(type="x", title="t", description="d", resource="r",
                   timestamp="t", last_verified_at="t", source_system=SourceSystem.CONFIG,
                   source_path="p", owner="o", bogus_field=True)   # Strict: unknown field


def test_source_hash_accepts_a_proper_digest():
    c = _concept(source_hash="sha256:" + "a" * 64)
    assert c.source_hash.startswith("sha256:")


# --------------------------------------------------------------------- document

def test_render_has_frontmatter_generated_markers_and_human():
    from command_center.knowledge.document import ConceptDocument, GEN_END, GEN_START
    doc = ConceptDocument(frontmatter=_concept(), generated="- fact one\n- fact two")
    text = doc.render()
    assert text.startswith("---\n") and "growth-os-0.1" in text
    assert GEN_START in text and GEN_END in text
    assert "Human notes" in text                 # default human stub


def test_round_trip_parse():
    from command_center.knowledge.document import ConceptDocument
    doc = ConceptDocument(frontmatter=_concept(title="Round trip"),
                          generated="- a\n- b", human="## Human notes\n\nkeep me")
    parsed = parse_concept(doc.render())
    assert parsed.frontmatter.title == "Round trip"
    assert parsed.generated == "- a\n- b"
    assert "keep me" in parsed.human


def test_write_preserves_human_and_replaces_generated(tmp_path):
    path = tmp_path / "concept.md"
    write_concept(path, _concept(), generated="- v1 facts")
    # a human edits the notes section
    text = path.read_text(encoding="utf-8").replace(
        "_Add curated notes here; they are preserved across regenerations._",
        "operator: watch the canary closely")
    path.write_text(text, encoding="utf-8")
    # regenerate with new facts → generated replaced, human note kept
    write_concept(path, _concept(), generated="- v2 facts")
    after = read_concept(path)
    assert after.generated == "- v2 facts"
    assert "watch the canary closely" in after.human


def test_write_is_idempotent(tmp_path):
    path = tmp_path / "c.md"
    write_concept(path, _concept(), generated="- stable")
    first = path.read_text(encoding="utf-8")
    write_concept(path, _concept(), generated="- stable")
    assert path.read_text(encoding="utf-8") == first      # same source → same bytes


def test_no_timestamp_churn_when_source_unchanged(tmp_path):
    # a later regeneration with a NEW clock but the SAME source content must not churn the file
    path = tmp_path / "c.md"
    h = "sha256:" + "b" * 64
    write_concept(path, _concept(source_hash=h, timestamp="2026-01-01T00:00:00Z",
                                 last_verified_at="2026-01-01T00:00:00Z"), generated="- same")
    first = path.read_text(encoding="utf-8")
    write_concept(path, _concept(source_hash=h, timestamp="2026-09-09T00:00:00Z",
                                 last_verified_at="2026-09-09T00:00:00Z"), generated="- same")
    assert path.read_text(encoding="utf-8") == first       # unchanged source → byte-identical
    # but a changed source DOES update (new generated content + timestamp)
    write_concept(path, _concept(source_hash="sha256:" + "c" * 64,
                                 timestamp="2026-09-09T00:00:00Z",
                                 last_verified_at="2026-09-09T00:00:00Z"), generated="- changed")
    after = read_concept(path)
    assert after.generated == "- changed"
    assert after.frontmatter.timestamp == "2026-09-09T00:00:00Z"


def test_parse_errors_are_loud():
    with pytest.raises(ConceptParseError, match="frontmatter"):
        parse_concept("no frontmatter here")
    with pytest.raises(ConceptParseError, match="markers"):
        parse_concept("---\ntype: System\ntitle: t\ndescription: d\nresource: r\n"
                      "timestamp: t\nlast_verified_at: t\nsource_system: config\n"
                      "source_path: p\nowner: o\n---\n\nno generated markers")

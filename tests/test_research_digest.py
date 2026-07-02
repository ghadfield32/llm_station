"""
Research intake: the typed catalog, its feed emission, and the observer-only scan bridge
(ResearchSourceScanner). A catalog row marked `evaluate` becomes exactly one read-only (L1)
evaluation Finding through the same propose-only wall model-scout uses.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from command_center.improvement.discovery import Pillar, ResearchSourceScanner
from command_center.improvement.discovery.dag_support import SOURCE_REGISTRY, build_scanner
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.schema import TargetType
from command_center.research import (
    RESEARCH_FEED_SOURCE, ResearchSource, ResearchSourceCatalog, Verdict,
    catalog_to_feed, load_catalog, render_digest_markdown, source_to_feed_record,
)
from command_center.schemas.base import RiskTier


def _source(**kw):
    base = dict(id="x-1", title="Thing", source_type="github", source="o/r",
                concept_cluster="memory", claim="does a thing")
    base.update(kw)
    return ResearchSource(**base)


# --------------------------------------------------------------------- catalog model

def test_catalog_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        ResearchSourceCatalog(sources=[_source(id="dup"), _source(id="dup")])


def test_bad_id_rejected():
    with pytest.raises(ValidationError):
        _source(id="not a slug")


def test_evidence_completeness_scales_with_evidence():
    bare = _source()
    full = _source(measured_gap="a real gap", related_modules=["m"], url="u", notes=["n"])
    assert bare.evidence_completeness() == 0.0
    assert full.evidence_completeness() == 1.0


def test_evaluatable_only_returns_evaluate_verdict():
    cat = ResearchSourceCatalog(sources=[
        _source(id="a", verdict=Verdict.EVALUATE),
        _source(id="b", verdict=Verdict.WATCH),
        _source(id="c", verdict=Verdict.REJECT),
    ])
    assert [s.id for s in cat.evaluatable()] == ["a"]


# --------------------------------------------------------------------- feed emission

def test_feed_only_includes_evaluate_sources():
    cat = ResearchSourceCatalog(sources=[
        _source(id="keep", verdict=Verdict.EVALUATE, measured_gap="gap"),
        _source(id="drop", verdict=Verdict.WATCH),
    ])
    feed = catalog_to_feed(cat)
    assert set(feed) == {RESEARCH_FEED_SOURCE}
    ids = [r["id"] for r in feed[RESEARCH_FEED_SOURCE]]
    assert ids == ["keep"]
    rec = feed[RESEARCH_FEED_SOURCE][0]
    assert rec["record_type"] == "research_source"
    assert 0.0 <= rec["evidence_completeness"] <= 1.0


# --------------------------------------------------------------------- scan bridge

def test_research_scanner_drafts_readonly_evaluation_finding():
    rec = source_to_feed_record(_source(verdict=Verdict.EVALUATE, measured_gap="a gap",
                                        related_modules=["services/x"], url="u", priority="high"))
    findings = ResearchSourceScanner(lambda: [rec]).scan()
    assert len(findings) == 1
    f = findings[0]
    assert f.pillar is Pillar.FULL_IDEA
    assert f.suggested_target_type is TargetType.SKILL
    assert f.suggested_risk is RiskTier.L1          # read-only evaluation, never adoption
    assert "gap" in f.claim.lower()


def test_research_scanner_low_confidence_without_measured_gap():
    with_gap = source_to_feed_record(_source(measured_gap="real", related_modules=["m"],
                                             url="u", notes=["n"]))
    without = source_to_feed_record(_source())
    f_gap = ResearchSourceScanner(lambda: [with_gap]).scan()[0]
    f_bare = ResearchSourceScanner(lambda: [without]).scan()[0]
    # §13 as a number: a bare link is strictly less confident than one with a measured gap.
    assert f_bare.confidence < f_gap.confidence
    assert "NO measured gap" in f_bare.claim


def test_research_scanner_ignores_foreign_records():
    assert ResearchSourceScanner(lambda: [{"record_type": "model_scout_candidate"}]).scan() == []


def test_research_source_registered_and_buildable():
    spec = next(s for s in SOURCE_REGISTRY if s["name"] == RESEARCH_FEED_SOURCE)
    assert spec["kind"] == "research"
    scanner = build_scanner(spec, ExperimentRegistry(":memory:"), fetch=lambda _s: [])
    assert isinstance(scanner, ResearchSourceScanner)


# --------------------------------------------------------------------- report + load

def test_render_digest_groups_by_verdict():
    cat = ResearchSourceCatalog(sources=[
        _source(id="b1", verdict=Verdict.BUILD),
        _source(id="w1", verdict=Verdict.WATCH, trigger="when X"),
    ])
    md = render_digest_markdown(cat)
    assert "## build (1)" in md
    assert "## watch (1)" in md
    assert "revisit when: when X" in md


def test_seed_catalog_loads_and_validates():
    # the committed batch record must always be valid + round-trip to a feed
    cat = load_catalog("knowledge/research/source_catalog.yaml")
    assert len(cat.sources) >= 10
    feed = catalog_to_feed(cat)
    assert RESEARCH_FEED_SOURCE in feed

"""
The research source catalog — a durable, typed record of external ideas/repos/links
evaluated against this stack, and the bridge that turns them into observer-only
improvement findings.

This productizes the MASTER.md §5.2 intake ("broad prompt first, then no adoption
without a measured gap, control-plane overlap matrix, threat model, and pre-registered
experiment plan"). A link dump becomes a `knowledge/research/source_catalog.yaml`
entry, and any entry marked `verdict: evaluate` is emitted as a feed record the daily
self-improvement scan classifies into a *Proposed* evaluation card — the exact same
propose-only wall model-scout uses. Nothing here adopts, installs, or promotes anything;
the catalog is a curated read-only artifact and the feed only drafts evaluation work.

The catalog is hand-authored (unlike the generated OKF bundle under knowledge/), so it
is validated by these Pydantic models on load — a typo'd key or bad verdict fails loudly
at `cc research-digest validate`, never silently at scan time.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import Field, field_validator

from ..schemas.base import Strict

# The record_type the scan's ResearchSourceScanner recognises. One string, one owner.
RESEARCH_RECORD_TYPE = "research_source"
# The feed source name the scan maps these records under (must match SOURCE_REGISTRY).
RESEARCH_FEED_SOURCE = "research_digest"


class Verdict(StrEnum):
    """What we decided to do with a source. Only `evaluate` becomes an actionable card;
    the rest are durable memory so the same link is never re-litigated from scratch."""
    EVALUATE = "evaluate"          # measured gap plausible → draft a read-only evaluation card
    BUILD = "build"                # already decided to build the extracted idea (tracked elsewhere)
    ALREADY_HAVE = "already_have"  # the capability exists in-stack; record why, do nothing
    WATCH = "watch"                # interesting but no measured gap yet → watch-list only
    REJECT = "reject"              # conflicts with a contract/principle; record why, do nothing


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResearchSource(Strict):
    """One evaluated external source (repo, post, paper, site). The schema is the map's
    Phase-1 `source_catalog.yaml` shape, adopted nearly verbatim, plus the §5.2 fields that
    gate adoption (`measured_gap`, `verdict`, `trigger`)."""
    id: str = Field(..., min_length=1, description="stable kebab-case slug, unique in the catalog")
    title: str = Field(..., min_length=1)
    source_type: str = Field(..., description="github | linkedin | web | paper | other")
    source: str = Field(..., description="repo slug, author, or short handle")
    url: str = ""
    concept_cluster: str = Field(..., description="e.g. agent_control_plane, memory, serving")
    claim: str = Field(..., description="one-line: what it does / what idea it teaches")
    related_modules: list[str] = Field(default_factory=list,
                                       description="llm_station modules this would attach to")
    # §5.2 gate: adoption needs a MEASURED gap. Null/empty = no gap yet = low-confidence card.
    measured_gap: str | None = None
    verdict: Verdict = Verdict.WATCH
    priority: Priority = Priority.MEDIUM
    risk_level: RiskLevel = RiskLevel.MEDIUM
    trigger: str = Field("", description="the condition that would move this off the watch-list")
    notes: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"id {v!r} must be kebab/snake-case (alnum, '-', '_')")
        return v

    def evidence_completeness(self) -> float:
        """0..1 — how ready this source is for an evaluation decision. A source with a
        measured gap, named modules, and a URL is decision-grade; a bare link is not.
        This is what makes a card with no measured gap correctly low-confidence — §13's
        'no candidate zoo without a measured gap' expressed as a number, not a slogan."""
        present = 0
        checks = (
            bool(self.measured_gap),
            bool(self.related_modules),
            bool(self.url),
            bool(self.notes),
        )
        present = sum(1 for c in checks if c)
        return present / len(checks)


class ResearchSourceCatalog(Strict):
    schema_version: str = "command-center.research-catalog.v1"
    sources: list[ResearchSource] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def _unique_ids(cls, v: list[ResearchSource]) -> list[ResearchSource]:
        seen: set[str] = set()
        for s in v:
            if s.id in seen:
                raise ValueError(f"duplicate source id {s.id!r} in catalog")
            seen.add(s.id)
        return v

    def evaluatable(self) -> list[ResearchSource]:
        return [s for s in self.sources if s.verdict == Verdict.EVALUATE]


DEFAULT_CATALOG_PATH = "knowledge/research/source_catalog.yaml"
DEFAULT_FEED_PATH = "generated/research-digest-feed.json"


def load_catalog(path: str | Path = DEFAULT_CATALOG_PATH) -> ResearchSourceCatalog:
    """Load + validate the catalog. Raises pydantic.ValidationError on a bad file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ResearchSourceCatalog.model_validate(raw)


def source_to_feed_record(s: ResearchSource) -> dict:
    """One catalog source -> one scan feed record. Only meaningful for `evaluate` sources;
    the scanner drafts a read-only (L1) evaluation card, never an adoption."""
    return {
        "record_type": RESEARCH_RECORD_TYPE,
        "id": s.id,
        "title": s.title,
        "source_type": s.source_type,
        "source": s.source,
        "url": s.url,
        "concept_cluster": s.concept_cluster,
        "claim": s.claim,
        "related_modules": list(s.related_modules),
        "measured_gap": s.measured_gap,
        "priority": s.priority.value,
        "risk_level": s.risk_level.value,
        "evidence_completeness": round(s.evidence_completeness(), 4),
        "notes": list(s.notes),
    }


def catalog_to_feed(catalog: ResearchSourceCatalog) -> dict:
    """The `{source_name: [records...]}` map the scan's `--feeds` file expects. Only
    `evaluate` sources are emitted — watch/reject/already_have stay durable-only."""
    return {RESEARCH_FEED_SOURCE: [source_to_feed_record(s) for s in catalog.evaluatable()]}


def render_digest_markdown(catalog: ResearchSourceCatalog) -> str:
    """A human-readable digest grouped by verdict then concept cluster — the STORM-style
    'here is what the batch says' artifact, read straight off the typed catalog."""
    lines = ["# Research digest", "",
             f"{len(catalog.sources)} source(s) in `{DEFAULT_CATALOG_PATH}`.", ""]
    order = [Verdict.BUILD, Verdict.EVALUATE, Verdict.WATCH, Verdict.ALREADY_HAVE, Verdict.REJECT]
    for verdict in order:
        rows = [s for s in catalog.sources if s.verdict == verdict]
        if not rows:
            continue
        lines.append(f"## {verdict.value} ({len(rows)})")
        lines.append("")
        for s in sorted(rows, key=lambda x: (x.concept_cluster, x.id)):
            gap = s.measured_gap or "_no measured gap yet_"
            lines.append(f"- **{s.title}** (`{s.source}`, {s.concept_cluster}) — {s.claim}")
            lines.append(f"  - gap: {gap}")
            if s.trigger:
                lines.append(f"  - revisit when: {s.trigger}")
            if s.related_modules:
                lines.append(f"  - modules: {', '.join(s.related_modules)}")
        lines.append("")
    return "\n".join(lines)

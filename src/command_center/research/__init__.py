"""Research intake — the durable, typed catalog of external ideas/repos evaluated
against this stack, and the observer-only bridge into the daily self-improvement scan.
See catalog.py; the CLI is command_center.cli.research_digest."""
from __future__ import annotations

from .catalog import (
    DEFAULT_CATALOG_PATH, DEFAULT_FEED_PATH, RESEARCH_FEED_SOURCE, RESEARCH_RECORD_TYPE,
    Priority, ResearchSource, ResearchSourceCatalog, RiskLevel, Verdict,
    catalog_to_feed, load_catalog, render_digest_markdown, source_to_feed_record,
)

__all__ = [
    "DEFAULT_CATALOG_PATH", "DEFAULT_FEED_PATH", "RESEARCH_FEED_SOURCE", "RESEARCH_RECORD_TYPE",
    "Priority", "ResearchSource", "ResearchSourceCatalog", "RiskLevel", "Verdict",
    "catalog_to_feed", "load_catalog", "render_digest_markdown", "source_to_feed_record",
]

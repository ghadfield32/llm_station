"""Fetch recent arXiv papers for the configured categories + queries."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import urllib.parse
import feedparser
import httpx
from ..config import ArxivCfg
from ..models import CuratedItem

API = "https://export.arxiv.org/api/query"


def _build_query(cfg: ArxivCfg) -> str:
    cats = " OR ".join(f"cat:{c}" for c in cfg.categories)
    parts = [f"({cats})"] if cats else []
    parts += [f"({q})" for q in cfg.queries]
    return " OR ".join(parts) if parts else "cat:cs.LG"


def fetch(cfg: ArxivCfg, max_results: int = 80) -> list[CuratedItem]:
    if not cfg.enabled:
        return []
    params = {
        "search_query": _build_query(cfg),
        "sortBy": "submittedDate", "sortOrder": "descending",
        "start": 0, "max_results": max_results,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    raw = httpx.get(url, timeout=40, follow_redirects=True).text
    feed = feedparser.parse(raw)
    cutoff = date.today() - timedelta(days=cfg.lookback_days)
    items: list[CuratedItem] = []
    for e in feed.entries:
        try:
            pub = datetime(*e.published_parsed[:6]).date()
        except Exception:
            pub = None
        if pub and pub < cutoff:
            continue
        aid = e.id.split("/abs/")[-1]
        items.append(CuratedItem(
            kind="paper", external_id=aid, title=e.title.strip().replace("\n", " "),
            url=e.id, summary=e.summary.strip().replace("\n", " ")[:1200],
            authors=", ".join(a.name for a in getattr(e, "authors", [])[:6]),
            topics=[t.term for t in getattr(e, "tags", [])][:6],
            source="arxiv", published=pub,
        ))
    return items

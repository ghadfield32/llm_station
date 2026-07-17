"""Fetch recent arXiv papers for the configured categories + queries."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import re
import time
import urllib.parse
import feedparser
import httpx
from command_center.research_topics import (
    arxiv_query_for_topic,
    matching_research_topics,
)
from ..config import ArxivCfg
from ..models import CuratedItem

API = "https://export.arxiv.org/api/query"
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.I)


def _source_links(entry, primary: str) -> tuple[list[str], list[str]]:
    candidates = [
        str(getattr(link, "href", "") or "")
        for link in getattr(entry, "links", [])
    ]
    candidates.extend(_URL_RE.findall(str(getattr(entry, "arxiv_comment", "") or "")))
    doi = str(getattr(entry, "arxiv_doi", "") or "").strip()
    if doi:
        candidates.append(f"https://doi.org/{doi}")
    related: list[str] = []
    for value in candidates:
        url = value.rstrip(".,;:")
        if url and url != primary and url not in related:
            related.append(url)
    code = [
        url for url in related
        if any(host in url.lower() for host in ("github.com/", "gitlab.com/", "codeberg.org/"))
    ]
    return code[:8], related[:12]


def _build_query(cfg: ArxivCfg) -> str:
    cats = " OR ".join(f"cat:{c}" for c in cfg.categories)
    parts = [f"({cats})"] if cats else []
    parts += [f"({arxiv_query_for_topic(topic)})" for topic in cfg.review_topics]
    return " OR ".join(parts) if parts else "cat:cs.LG"


def fetch(cfg: ArxivCfg, max_results: int = 80) -> list[CuratedItem]:
    if not cfg.enabled:
        return []
    cutoff = date.today() - timedelta(days=cfg.lookback_days)
    plans: list[tuple[str, str | None]] = []
    cats = " OR ".join(f"cat:{category}" for category in cfg.categories)
    if cats:
        plans.append((f"({cats})", None))
    plans.extend(
        (arxiv_query_for_topic(topic), topic) for topic in cfg.review_topics)
    if not plans:
        plans.append(("cat:cs.LG", None))
    by_id: dict[str, CuratedItem] = {}
    for index, (query, requested_topic) in enumerate(plans):
        # arXiv asks clients to leave a three-second gap between repeated API
        # calls. Topic-isolated queries prevent broad categories from hiding a
        # newly added topic in one global newest-N response.
        if index:
            time.sleep(3)
        params = {
            "search_query": query,
            "sortBy": "submittedDate", "sortOrder": "descending",
            "start": 0, "max_results": max_results,
        }
        url = f"{API}?{urllib.parse.urlencode(params)}"
        response = httpx.get(url, timeout=40, follow_redirects=True)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
            raise RuntimeError("arXiv returned an invalid Atom feed")
        for entry in feed.entries:
            try:
                published = datetime(*entry.published_parsed[:6]).date()
            except Exception:
                published = None
            if published and published < cutoff:
                continue
            arxiv_id = entry.id.split("/abs/")[-1]
            existing = by_id.get(arxiv_id)
            if existing is not None:
                if (
                    requested_topic
                    and requested_topic not in existing.extra["review_topics"]
                ):
                    existing.extra["review_topics"].append(requested_topic)
                continue
            code_links, related_links = _source_links(entry, entry.id)
            title = entry.title.strip().replace("\n", " ")
            summary = entry.summary.strip().replace("\n", " ")[:1200]
            review_topics = (
                [requested_topic]
                if requested_topic
                else matching_research_topics(
                    f"{title}\n{summary}", cfg.review_topics)
            )
            by_id[arxiv_id] = CuratedItem(
                kind="paper", external_id=arxiv_id, title=title,
                url=entry.id, summary=summary,
                authors=", ".join(
                    author.name for author in getattr(entry, "authors", [])[:6]),
                topics=[tag.term for tag in getattr(entry, "tags", [])][:6],
                source=f"arxiv:{requested_topic or 'categories'}", published=published,
                extra={
                    "code_links": code_links,
                    "related_links": related_links,
                    "review_topics": review_topics,
                    "primary_category": str(getattr(
                        getattr(entry, "arxiv_primary_category", None), "term", "")
                        or ""),
                    "comment": str(
                        getattr(entry, "arxiv_comment", "") or "").strip(),
                    "journal_ref": str(
                        getattr(entry, "arxiv_journal_ref", "") or "").strip(),
                    "doi": str(getattr(entry, "arxiv_doi", "") or "").strip(),
                },
            )
    return list(by_id.values())

"""Pull 'advances' signals from RSS/Atom feeds (HN, lab blogs, newsletters)."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import feedparser
from ..config import SignalsCfg
from ..models import CuratedItem

CATS = {"llm": "LLM", "language model": "LLM", "gpt": "LLM", "agent": "LLM",
        "code": "Coding", "coding": "Coding", "developer": "Coding",
        "data": "DataScience", "ml": "DataScience", "mlops": "MLOps", "pipeline": "MLOps"}


def _categorize(text: str) -> str:
    t = text.lower()
    for k, v in CATS.items():
        if k in t:
            return v
    return "Other"


def fetch(cfg: SignalsCfg, per_feed: int = 12) -> list[CuratedItem]:
    if not cfg.enabled:
        return []
    cutoff = date.today() - timedelta(days=cfg.lookback_days)
    out: list[CuratedItem] = []
    for feed_url in cfg.feeds:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue
        src = feed.feed.get("title", feed_url)
        for e in feed.entries[:per_feed]:
            pub = None
            for attr in ("published_parsed", "updated_parsed"):
                if getattr(e, attr, None):
                    pub = datetime(*getattr(e, attr)[:6]).date()
                    break
            if pub and pub < cutoff:
                continue
            title = e.get("title", "").strip()
            out.append(CuratedItem(
                kind="signal", external_id=e.get("link", title), title=title,
                url=e.get("link", ""), summary=(e.get("summary", "") or "")[:600],
                source=src, published=pub, extra={"category": _categorize(title)},
            ))
    return out

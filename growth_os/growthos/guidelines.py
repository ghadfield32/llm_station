"""guidelines — keeps the `guidelines` database a living mirror of (a) the
command center's enforced standards and (b) upstream release/guideline feeds.

Stages:
  stage 1  sync_standards()  configs/standards.yaml -> one Current row per
                             profile + one for core principles. The knowledge
                             base mirrors what the judges actually enforce.
  stage 2  fetch_feeds()     sources.yaml `guidelines.feeds` (release-note
                             atom/rss, e.g. GitHub releases) -> rows landing
                             as Status=Review for human reading; Status set
                             only on NEW rows so triage decisions stick.

Run:  python -m growthos.guidelines        (also wired into the daily loop)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import feedparser
import yaml

from .actions import client
from .config import load_settings

log = logging.getLogger("growthos.guidelines")

PROFILE_AREAS = {"python_ml_pipeline": "ML", "python_service": "Infra"}


# stage 1 ------------------------------------------------------------------

def sync_standards(standards_path: Path) -> int:
    data = yaml.safe_load(standards_path.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    rows = [{
        "pre_hash": "std-core-principles",
        "cells": {"Name": "Core engineering principles",
                  "Area": "Coding", "Status": "Current",
                  "Source": "command-center standards.yaml",
                  "Notes": "\n".join(f"- {p}" for p in data.get("core_principles", [])),
                  "UpdatedAt": today}}]
    for profile in data.get("profiles", []):
        name = profile["name"]
        notes = ["principles:"] + [f"- {p}" for p in profile.get("principles", [])]
        notes += ["blocked:"] + [f"- {p}" for p in profile.get("blocked_patterns", [])]
        notes += ["allowed:"] + [f"- {p}" for p in profile.get("allowed_patterns", [])]
        rows.append({
            "pre_hash": f"std-profile-{name}",
            "cells": {"Name": f"Standards profile: {name}",
                      "Area": PROFILE_AREAS.get(name, "Project"),
                      "Status": "Current",
                      "Source": "command-center standards.yaml",
                      "Notes": "\n".join(notes), "UpdatedAt": today}})
    return len(client().upsert("guidelines", rows))


# stage 2 ------------------------------------------------------------------

def fetch_feeds(feeds: list[str], lookback_days: int) -> int:
    af = client()
    existing = set()
    for d in af.row_details("guidelines", af.list_row_ids("guidelines")):
        c = d["cells"]
        if c.get("URL"):
            existing.add(c["URL"])
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = []
    for url in feeds:
        feed = feedparser.parse(url)
        src = feed.feed.get("title", url)
        for e in feed.entries[:10]:
            pub = None
            for attr in ("published_parsed", "updated_parsed"):
                if getattr(e, attr, None):
                    pub = datetime(*getattr(e, attr)[:6]).date()
                    break
            if pub and pub < cutoff:
                continue
            link = e.get("link", "")
            cells = {"Name": f"{src}: {e.get('title', '').strip()}"[:120],
                     "Area": "Infra", "Source": src, "URL": link,
                     "UpdatedAt": (pub or date.today()).isoformat(),
                     "Notes": (e.get("summary", "") or "")[:400]}
            if link not in existing:           # new -> needs review
                cells["Status"] = "Review"
            rows.append({"pre_hash": link or cells["Name"], "cells": cells})
    return len(client().upsert("guidelines", rows))


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    here = Path(__file__).resolve().parent.parent
    standards = Path(load_settings().growthos_standards_path).resolve()
    if not standards.exists():
        log.warning("standards file not found at %s; feeds only", standards)
        n_std = 0
    else:
        n_std = sync_standards(standards)
    cfg = yaml.safe_load((here / "config/sources.yaml").read_text(encoding="utf-8"))
    gcfg = cfg.get("guidelines", {})
    n_feeds = fetch_feeds(gcfg.get("feeds", []), gcfg.get("lookback_days", 30))
    log.info("guidelines: %d standards rows, %d feed rows upserted", n_std, n_feeds)


if __name__ == "__main__":
    main()

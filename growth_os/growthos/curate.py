"""Entry point: fetch -> score -> dedupe -> upsert. Idempotent and rerun-safe.

Usage:
  python -m growthos.curate                 # all enabled sources
  python -m growthos.curate --source arxiv  # one source
  python -m growthos.curate --dry-run       # CSVs only (also honours GROWTHOS_DRY_RUN)
"""
from __future__ import annotations
import argparse
import logging

from .config import load_config, load_settings
from .state import SeenStore
from .score import make_scorer, rank_and_trim
from .internal_board import InternalBoardClient, items_to_cells
from .sources import arxiv, github, rss


def run(only: str | None = None, force_dry: bool = False) -> dict[str, int]:
    cfg = load_config()
    st = load_settings()
    logging.basicConfig(level=getattr(logging, st.growthos_log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("growthos.curate")

    dry = st.growthos_dry_run or force_dry
    seen = SeenStore(st.growthos_state_dir)
    boards = InternalBoardClient(
        store_dir=st.growthos_board_store,
        event_log=st.growthos_kanban_event_log,
        dry_run=dry,
        out_dir="./_export",
    )

    # 1) fetch
    raw = []
    if (not only or only == "arxiv"):
        raw += arxiv.fetch(cfg.sources.arxiv)
    if (not only or only == "github"):
        raw += github.fetch(cfg.sources.github, token=st.github_token)
    if (not only or only == "signals"):
        raw += rss.fetch(cfg.sources.signals)
    log.info("fetched %d raw items", len(raw))

    # 2) dedupe against history, per kind
    by_kind: dict[str, list] = {}
    for it in raw:
        by_kind.setdefault(it.kind, []).append(it)
    fresh = []
    top_n = {"paper": cfg.sources.arxiv.top_n, "repo": cfg.sources.github.top_n,
             "signal": cfg.sources.signals.top_n}
    scorer = make_scorer(cfg, st.ollama_base_url)
    for kind, items in by_kind.items():
        new = seen.filter_new(kind, items)
        # 3) score + trim to top-N per kind
        kept = rank_and_trim(new, scorer, top_n.get(kind, 10),
                             include_zero=(kind == "signal"))
        fresh += kept
        log.info("%s: %d new -> %d kept", kind, len(new), len(kept))

    # 3.5) annotate the keepers: one-line "why this helps / use it for" notes
    if fresh:
        from .enrich import suggest
        n = suggest(fresh, st.ollama_base_url, st.growthos_brief_model)
        log.info("enriched %d/%d kept items", n, len(fresh))

    # 4) write
    written = {}
    ok_keys: set[str] = set()
    for db, cells in items_to_cells(fresh).items():
        wrote = boards.upsert(db, cells)
        written[db] = len(wrote)
        ok_keys.update(wrote)
    # 5) remember ONLY what actually wrote, so failed rows retry next run
    for kind in by_kind:
        ids = [i.external_id for i in fresh
               if i.kind == kind and i.external_id in ok_keys]
        if ids:
            seen.add(kind, ids)

    log.info("done. wrote=%s dry_run=%s", written, dry)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["arxiv", "github", "signals"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(only=a.source, force_dry=a.dry_run)


if __name__ == "__main__":
    main()

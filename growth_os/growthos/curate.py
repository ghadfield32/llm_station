"""Entry point: fetch -> score -> dedupe -> upsert. Idempotent and rerun-safe.

Usage:
  python -m growthos.curate                 # all enabled sources
  python -m growthos.curate --source arxiv  # one source
  python -m growthos.curate --dry-run       # CSVs only (also honours GROWTHOS_DRY_RUN)
  python -m growthos.curate --reanalyze papers --limit 25
"""
from __future__ import annotations
import argparse
import logging

from .config import load_config, load_settings
from .state import SeenStore
from .score import make_scorer, rank_and_trim
from .internal_board import InternalBoardClient, analysis_cells, items_to_cells
from .models import CuratedItem
from .sources import arxiv, github, rss


def _values(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _project_fits(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [
        dict(item) for item in value
        if isinstance(item, dict) and str(item.get("project") or "").strip()
    ]


def _analysis_item(db_name: str, card: dict) -> CuratedItem:
    kind = "paper" if db_name == "papers" else "repo"
    source_cells = card.get("appflowy_source_cells")
    source_cells = source_cells if isinstance(source_cells, dict) else {}
    summary = (
        card.get("abstract") or source_cells.get("Abstract")
        if kind == "paper"
        else card.get("why") or source_cells.get("Why")
    )
    source_topics = source_cells.get("Topics")
    return CuratedItem(
        kind=kind,
        external_id=str(card["card_id"]),
        title=str(card["title"]),
        url=str(card.get("url") or source_cells.get("URL") or ""),
        summary=str(summary or ""),
        authors=str(card.get("authors") or source_cells.get("Authors") or ""),
        topics=_values(
            card.get("review_topics") or card.get("useful_for")
            or card.get("topics") or source_topics),
        source="board_analysis_backfill",
        extra={
            "suggested": str(card.get("suggested") or ""),
            "useful_for_us": str(card.get("useful_for_us") or ""),
            "pros": _values(card.get("pros")),
            "cons": _values(card.get("cons")),
            "key_details": _values(card.get("key_details")),
            "implementation_notes": _values(card.get("implementation_notes")),
            "work_areas": _values(card.get("work_areas")),
            "use_cases": _values(card.get("use_cases")),
            "research_priority": str(card.get("research_priority") or ""),
            "relevance_score": card.get("relevance_score", ""),
            "potential_impact_score": card.get("potential_impact_score", ""),
            "implementation_readiness_score": card.get(
                "implementation_readiness_score", ""),
            "evidence_confidence_score": card.get(
                "evidence_confidence_score", ""),
            "estimated_effort": str(card.get("estimated_effort") or ""),
            "project_fits": _project_fits(card.get("project_fits")),
            "applicable_projects": _values(card.get("applicable_projects")),
            "best_project": str(card.get("best_project") or ""),
            "best_project_fit_score": card.get("best_project_fit_score", ""),
            "project_fit_summary": str(card.get("project_fit_summary") or ""),
            "analysis_schema_version": str(
                card.get("analysis_schema_version") or ""),
            "code_links": _values(card.get("code_links")),
            "related_links": _values(card.get("related_links")),
            "review_topics": _values(card.get("review_topics")),
            "analysis_status": str(card.get("analysis_status") or "not_analyzed"),
            "analysis_model": str(card.get("analysis_model") or ""),
            "analysis_generated_at": str(card.get("analysis_generated_at") or ""),
            "analysis_input_sha256": str(card.get("analysis_input_sha256") or ""),
            "analysis_origin": str(card.get("analysis_origin") or ""),
            "analysis_error_code": str(card.get("analysis_error_code") or ""),
        },
    )


def _reanalyze(
    boards: InternalBoardClient, db_name: str, limit: int, *, base_url: str, model: str,
) -> dict[str, int]:
    from .enrich import suggest

    cards = boards.analysis_candidates(db_name, limit)
    items = [_analysis_item(db_name, card) for card in cards]
    attempt_fields = (
        "analysis_status", "analysis_model", "analysis_generated_at",
        "analysis_input_sha256", "analysis_origin", "analysis_error_code",
    )
    before_attempt = {
        item.external_id: tuple(item.extra.get(field) for field in attempt_fields)
        for item in items
    }
    completed = suggest(items, base_url, model)
    rows = [
        {"pre_hash": item.external_id, "cells": analysis_cells(item)}
        for item in items
        # suggest() stamps every attempted outcome (complete, failed, or
        # unavailable). An early transport failure leaves later items carrying
        # their prior timestamps; compare the whole attempt fingerprint so
        # those untouched cards are never rewritten.
        if tuple(item.extra.get(field) for field in attempt_fields)
        != before_attempt[item.external_id]
    ]
    wrote = boards.upsert(db_name, rows) if rows else []
    return {
        f"{db_name}_analysis_candidates": len(cards),
        f"{db_name}_analysis_complete": completed,
        f"{db_name}_analysis_written": len(wrote),
    }


def run(
    only: str | None = None,
    force_dry: bool = False,
    *,
    reanalyze: str | None = None,
    analysis_limit: int = 25,
) -> dict[str, int]:
    st = load_settings()
    cfg = load_config(domain_surfaces_path=st.growthos_domain_surfaces)
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
    if reanalyze:
        return _reanalyze(
            boards, reanalyze, analysis_limit,
            base_url=st.ollama_base_url,
            model=st.growthos_brief_model,
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
    ap.add_argument("--reanalyze", choices=["papers", "repos"])
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    if a.source and a.reanalyze:
        ap.error("--source and --reanalyze are mutually exclusive")
    run(
        only=a.source,
        force_dry=a.dry_run,
        reanalyze=a.reanalyze,
        analysis_limit=a.limit,
    )


if __name__ == "__main__":
    main()

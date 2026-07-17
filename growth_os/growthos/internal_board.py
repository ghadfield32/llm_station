"""First-party board-store client used by Growth OS actions.

The interface preserves the old idempotent row API while storing cards in the
Command Center's governed event log and per-board JSON stores. It has no network
authentication and no external board dependency.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync.events import EventLog, emit_event, is_human_owned_status
from command_center.write_locking import BoardWriteLocked

from .config import load_research_projects
from .enrich import validate_persisted_analysis
from .models import CuratedItem

BOARD_IDS = {
    "mission_intake": "llm_station_command_center",
    "todos": "personal_tasks",
    "papers": "research_papers",
    "repos": "research_repos",
    "signals": "research_signals",
    "library": "reading_library",
    "lessons": "learning_lessons",
    "notes": "knowledge_notes",
    "dags": "dag_operations",
}


def analysis_cells(item: CuratedItem) -> dict[str, Any]:
    """Canonical analysis fields shared by fresh writes and bounded backfills."""
    extra = item.extra
    error_code = extra.get("analysis_error_code", "")
    return {
        "Suggested": extra.get("suggested", ""),
        "UsefulForUs": extra.get("useful_for_us", ""),
        "Pros": extra.get("pros", []),
        "Cons": extra.get("cons", []),
        "KeyDetails": extra.get("key_details", []),
        "ImplementationNotes": extra.get("implementation_notes", []),
        "WorkAreas": extra.get("work_areas", []),
        "UseCases": extra.get("use_cases", []),
        "ResearchPriority": extra.get("research_priority", ""),
        "RelevanceScore": extra.get("relevance_score", ""),
        "PotentialImpactScore": extra.get("potential_impact_score", ""),
        "ImplementationReadinessScore": extra.get(
            "implementation_readiness_score", ""),
        "EvidenceConfidenceScore": extra.get("evidence_confidence_score", ""),
        "EstimatedEffort": extra.get("estimated_effort", ""),
        "ProjectFits": extra.get("project_fits", []),
        "ApplicableProjects": extra.get("applicable_projects", []),
        "BestProject": extra.get("best_project", ""),
        "BestProjectFitScore": extra.get("best_project_fit_score", ""),
        "ProjectFitSummary": extra.get("project_fit_summary", ""),
        "AnalysisSchemaVersion": extra.get("analysis_schema_version", ""),
        "CodeLinks": extra.get("code_links", []),
        "RelatedLinks": extra.get("related_links", []),
        "ReviewTopics": extra.get("review_topics", []),
        "AnalysisStatus": extra.get("analysis_status", "not_analyzed"),
        "AnalysisModel": extra.get("analysis_model", ""),
        "AnalysisGeneratedAt": extra.get("analysis_generated_at", ""),
        "AnalysisInputSHA256": extra.get("analysis_input_sha256", ""),
        "AnalysisOrigin": extra.get("analysis_origin", ""),
        "AnalysisErrorCode": error_code,
        # Successful retries must explicitly clear a canonical error retained
        # from an earlier failed attempt. Other blank legacy cells remain
        # merge-preserving through _canonicalize.
        "analysis_error_code": error_code,
    }


FIELD_MAP = {
    "papers": lambda i: {
        "Title": i.title, "Authors": i.authors, "ArxivID": i.external_id,
        "Abstract": i.summary,
        "URL": i.url, "Topics": i.topics, "Score": i.score, "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
        "PrimaryCategory": i.extra.get("primary_category", ""),
        "Comment": i.extra.get("comment", ""),
        "JournalRef": i.extra.get("journal_ref", ""),
        "DOI": i.extra.get("doi", ""),
        **analysis_cells(i),
    },
    "repos": lambda i: {
        "Name": i.title, "Owner": i.extra.get("owner", ""), "URL": i.url,
        "Stars": i.extra.get("stars", 0), "Language": i.extra.get("language", ""),
        "Why": i.summary,
        "Topics": i.topics, "Score": i.score, "Status": "Inbox",
        "Updated": i.published.isoformat() if i.published else "",
        "PushedAt": i.extra.get("pushed_at", ""),
        "Forks": i.extra.get("forks", 0),
        "OpenIssues": i.extra.get("open_issues", 0),
        "License": i.extra.get("license", ""),
        "DefaultBranch": i.extra.get("default_branch", ""),
        "Archived": i.extra.get("archived", False),
        **analysis_cells(i),
    },
    "signals": lambda i: {
        "Headline": i.title, "Source": i.source, "URL": i.url,
        "Suggested": i.extra.get("suggested", ""),
        "Category": i.extra.get("category", "Other"), "Score": i.score,
        "Status": "Inbox",
        "Published": i.published.isoformat() if i.published else "",
    },
}
KIND_TO_DB = {"paper": "papers", "repo": "repos", "signal": "signals"}

_CANONICAL_FIELDS = {
    "Name": "title", "Title": "title", "Task": "title", "Headline": "title",
    "Authors": "authors", "Abstract": "abstract", "URL": "url",
    "Topics": "useful_for", "Score": "score", "ArxivID": "arxiv_id",
    "Owner": "owner", "Stars": "stars", "Language": "language", "Why": "why",
    "Suggested": "suggested", "UsefulForUs": "useful_for_us",
    "Pros": "pros", "Cons": "cons", "KeyDetails": "key_details",
    "ImplementationNotes": "implementation_notes", "CodeLinks": "code_links",
    "WorkAreas": "work_areas", "UseCases": "use_cases",
    "ResearchPriority": "research_priority",
    "RelevanceScore": "relevance_score",
    "PotentialImpactScore": "potential_impact_score",
    "ImplementationReadinessScore": "implementation_readiness_score",
    "EvidenceConfidenceScore": "evidence_confidence_score",
    "EstimatedEffort": "estimated_effort", "ProjectFits": "project_fits",
    "ApplicableProjects": "applicable_projects", "BestProject": "best_project",
    "BestProjectFitScore": "best_project_fit_score",
    "ProjectFitSummary": "project_fit_summary",
    "AnalysisSchemaVersion": "analysis_schema_version",
    "RelatedLinks": "related_links", "AnalysisStatus": "analysis_status",
    "ReviewTopics": "review_topics",
    "AnalysisModel": "analysis_model", "AnalysisGeneratedAt": "analysis_generated_at",
    "AnalysisInputSHA256": "analysis_input_sha256", "AnalysisOrigin": "analysis_origin",
    "AnalysisErrorCode": "analysis_error_code",
    "Published": "published", "Updated": "updated", "PushedAt": "pushed_at",
    "PrimaryCategory": "primary_category", "Comment": "comment",
    "JournalRef": "journal_ref", "DOI": "doi", "Forks": "forks",
    "OpenIssues": "open_issues", "License": "license",
    "DefaultBranch": "default_branch", "Archived": "archived",
    "DagID": "dag_id", "LastRun": "last_run", "NextRun": "next_run",
    "Schedule": "schedule", "Notes": "notes", "Author": "author",
    "Tier": "tier", "Type": "type", "Section": "section", "Module": "module",
    "Hours": "hours", "Area": "area", "Priority": "priority", "Due": "due",
}


def _action_for_status(status: str) -> str:
    lowered = status.casefold()
    if lowered in {"blocked", "needs geoff", "broken"}:
        return "block_card"
    if lowered in {"rejected", "rejected / skip"}:
        return "reject_card"
    if lowered in {"in progress", "scheduled", "reading", "trying", "using"}:
        return "start_todo"
    if lowered in {"done", "completed", "published", "read", "archived", "retired", "internalized"}:
        return "finish_todo"
    if lowered in {"ready", "in queue", "saved", "review"}:
        return "stage_card"
    return "add_mission_card"


class InternalBoardClient:
    """Idempotent row facade over first-party board stores."""

    def __init__(self, *, store_dir: str | Path | None = None,
                 event_log: str | Path | None = None, dry_run: bool = False,
                 out_dir: str | Path = "./_export"):
        self.store_dir = Path(store_dir or os.environ.get(
            "GROWTHOS_BOARD_STORE", "../generated/boards"))
        self.event_log = Path(event_log or os.environ.get(
            "GROWTHOS_KANBAN_EVENT_LOG", "../generated/kanban-events.jsonl"))
        self.dry_run = dry_run
        self.out = Path(out_dir)

    def _provider(self, db_name: str) -> CommandCenterBoardProvider:
        board_id = BOARD_IDS.get(db_name, db_name)
        return CommandCenterBoardProvider(
            board_id=board_id,
            event_log=EventLog(self.event_log),
            store_dir=self.store_dir,
        )

    @staticmethod
    def _canonicalize(cells: dict[str, Any]) -> dict[str, Any]:
        out = dict(cells)
        title = out.get("Name") or out.get("Title") or out.get("Task") or out.get("Headline")
        if title:
            out.setdefault("Name", title)
        for legacy, canonical in _CANONICAL_FIELDS.items():
            value = out.get(legacy)
            if value not in (None, ""):
                out.setdefault(canonical, value)
        return out

    def list_row_ids(self, db_name: str) -> list[str]:
        return [str(row["card_id"]) for row in self._provider(db_name).list_cards()]

    def analysis_candidates(self, db_name: str, limit: int) -> list[dict[str, Any]]:
        """Return a bounded, stable batch that still needs complete analysis."""
        if db_name not in {"papers", "repos"}:
            raise ValueError("analysis backfill supports papers or repos")
        if limit < 1 or limit > 200:
            raise ValueError("analysis backfill limit must be between 1 and 200")
        registered_projects = load_research_projects()
        candidates = []
        for stored in self._provider(db_name).list_cards():
            row = dict(stored)
            source_cells = row.get("appflowy_source_cells")
            source_cells = source_cells if isinstance(source_cells, dict) else {}
            title = str(
                row.get("title") or row.get("Title") or row.get("Name")
                or source_cells.get("Title") or source_cells.get("Name") or ""
            ).strip()
            if title:
                row["title"] = title
            if (
                title
                and not validate_persisted_analysis(row, registered_projects)
            ):
                candidates.append(row)
        # Work through never-attempted cards before retrying failures. A single
        # unavailable model response therefore cannot pin the same card at the
        # front of every bounded batch and starve the rest of the board.
        candidates.sort(key=lambda row: (
            bool(row.get("analysis_generated_at")),
            str(row.get("analysis_generated_at") or ""),
            str(row.get("card_id") or ""),
        ))
        return candidates[:limit]

    def analysis_progress(self, db_name: str) -> dict[str, int]:
        """Return exact strict-completion counts for one research board."""
        if db_name not in {"papers", "repos"}:
            raise ValueError("analysis progress supports papers or repos")
        registered_projects = load_research_projects()
        rows = self._provider(db_name).list_cards()
        titled = 0
        complete = 0
        for stored in rows:
            row = dict(stored)
            source_cells = row.get("appflowy_source_cells")
            source_cells = source_cells if isinstance(source_cells, dict) else {}
            title = str(
                row.get("title") or row.get("Title") or row.get("Name")
                or source_cells.get("Title") or source_cells.get("Name") or ""
            ).strip()
            if not title:
                continue
            titled += 1
            row["title"] = title
            if validate_persisted_analysis(row, registered_projects):
                complete += 1
        return {
            "stored_total": len(rows),
            "total": titled,
            "titled": titled,
            "complete": complete,
            "pending": titled - complete,
            "missing_title": len(rows) - titled,
        }

    def row_details(self, db_name: str, row_ids: list[str], chunk: int = 40) -> list[dict]:
        wanted = set(row_ids)
        out: list[dict] = []
        for row in self._provider(db_name).list_cards():
            card_id = str(row.get("card_id", ""))
            if card_id not in wanted:
                continue
            cells = {
                key: value for key, value in row.items()
                if key not in {"card_id", "board_id", "status", "last_event_id"}
            }
            if row.get("status") is not None:
                cells["Status"] = row["status"]
            out.append({"id": card_id, "cells": cells})
        return out

    def rows_updated_since(self, db_name: str, after_iso: str) -> list[str]:
        after = datetime.fromisoformat(after_iso.replace("Z", "+00:00")).timestamp()
        provider = self._provider(db_name)
        if not provider.store_dir.is_dir():
            return []
        updated: set[str] = set()
        for path in provider.store_dir.glob("*.json"):
            if path.stat().st_mtime < after:
                continue
            fields = json.loads(path.read_text(encoding="utf-8"))
            card_id = fields.get("card_id")
            if isinstance(card_id, str):
                updated.add(card_id)
        return sorted(updated)

    def upsert(self, db_name: str, rows: list[dict]) -> list[str]:
        if self.dry_run:
            return self._write_csv(db_name, rows)
        provider = self._provider(db_name)
        written: list[str] = []
        for row in rows:
            card_id = str(row["pre_hash"])
            cells = self._canonicalize(dict(row.get("cells") or {}))
            status = cells.pop("Status", None)
            if is_human_owned_status(status):
                continue
            # Retry the idempotent row transaction, not the whole source scan.
            # This avoids an hourly Airflow read repeatedly aligning with the
            # cockpit's periodic event-log reads.
            for attempt in range(20):
                try:
                    provider.upsert_card(card_id, cells)
                    current = (
                        (provider.snapshot() or {}).get(card_id, {}).get("status")
                    )
                    # Curator status is creation-time initialization only. Once
                    # a card has any lane, preserve the human/operator choice.
                    if status not in (None, "") and current is None:
                        emit_event(
                            provider.log,
                            action=_action_for_status(str(status)),
                            board_id=provider.board_id,
                            card_id=card_id,
                            source_surface="reconciler",
                            actor_type="agent",
                            status_before=current,
                            status_after=str(status),
                            evidence_ref=f"growth_os:{db_name}:{card_id}",
                        )
                except BoardWriteLocked:
                    if attempt == 19:
                        raise
                    time.sleep(0.05)
                else:
                    break
            written.append(card_id)
        return written

    def _write_csv(self, db_name: str, rows: list[dict]) -> list[str]:
        """Export a preview and report zero successful board writes.

        Callers use the returned IDs to advance durable seen-state. Returning
        previewed IDs here incorrectly made a CSV-only dry run consume inputs
        that had never reached the first-party board.
        """
        if not rows:
            return []
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{db_name}.csv"
        fields = list(rows[0]["cells"].keys())
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if new:
                writer.writeheader()
            for row in rows:
                writer.writerow(row["cells"])
        return []


def items_to_cells(items: list[CuratedItem]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for item in items:
        db_name = KIND_TO_DB[item.kind]
        out.setdefault(db_name, []).append({
            "pre_hash": item.external_id,
            "cells": FIELD_MAP[db_name](item),
        })
    return out

"""Audited, idempotent AppFlowy -> first-party board migration.

AppFlowy is a historical source only. Every row is retained with exact cells and
provenance; reruns merge imported fields without deleting cards or overwriting
fields that have diverged through first-party edits. Dry-run is the default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.kanban_sync.events import EventLog, emit_event
from command_center.write_locking import board_write_lock

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_MAP = ROOT / "archive/appflowy/legacy-growth-os/config/databases.json"
IMPORTER_ID = "appflowy-first-party-migration.v1"


class AppFlowyMigrationError(RuntimeError):
    pass


def _value(cells: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = cells.get(name)
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _book_id(cells: dict[str, Any], row_id: str, _account: str | None) -> str:
    title = _text(_value(cells, "Title", "Name"))
    return f"book-{title.lower()[:80]}" if title else f"appflowy-row-{row_id}"


def _paper_id(cells: dict[str, Any], row_id: str, _account: str | None) -> str:
    return _text(_value(cells, "ArxivID", "URL")) or f"appflowy-row-{row_id}"


def _repo_id(cells: dict[str, Any], row_id: str, _account: str | None) -> str:
    return _text(_value(cells, "URL")) or f"appflowy-row-{row_id}"


def _dag_id(cells: dict[str, Any], row_id: str, _account: str | None) -> str:
    return _text(_value(cells, "DagID", "Name")) or f"appflowy-row-{row_id}"


def _post_id(cells: dict[str, Any], row_id: str, account: str | None) -> str:
    key = _text(_value(cells, "Key"))
    return key or f"appflowy-post-{account}-{row_id}"


@dataclass(frozen=True)
class MigrationSpec:
    source_db: str
    target_board: str
    identity: Callable[[dict[str, Any], str, str | None], str]
    fields: dict[str, str]
    statuses: frozenset[str]
    account: str | None = None
    field_aliases: dict[str, tuple[str, ...]] | None = None


SPECS = (
    MigrationSpec(
        "papers", "research_papers", _paper_id,
        {
            "Title": "title", "Authors": "authors", "ArxivID": "arxiv_id",
            "Abstract": "abstract", "Suggested": "suggested", "URL": "url",
            "Topics": "useful_for", "Score": "score", "Published": "published",
        },
        frozenset({"Inbox", "Reading", "Read", "Archived"}),
        field_aliases={"title": ("Title", "Name")},
    ),
    MigrationSpec(
        "repos", "research_repos", _repo_id,
        {
            "Name": "title", "Owner": "owner", "URL": "url",
            "Stars": "stars", "Language": "language", "Why": "why",
            "Suggested": "suggested", "Topics": "topics", "Score": "score",
            "Updated": "updated",
        },
        frozenset({"Inbox", "Trying", "Using", "Archived"}),
    ),
    MigrationSpec(
        "dags", "dag_operations", _dag_id,
        {
            "Name": "title", "DagID": "dag_id", "Schedule": "schedule",
            "Description": "description", "Owners": "owner", "Tags": "tags",
            "Notes": "failure_summary", "LastSeen": "last_run",
            "NextRun": "next_run", "Path": "related_repo",
        },
        frozenset({"Active", "Paused", "Manual", "Broken", "Retired"}),
    ),
    MigrationSpec(
        "library", "reading_library", _book_id,
        {
            "Author": "author", "Tier": "tier",
            "Type": "type", "Module": "module", "Section": "section",
            "Hours": "hours", "Notes": "notes",
        },
        frozenset({"To read", "Reading", "Done"}),
        field_aliases={"title": ("Title", "Name")},
    ),
    MigrationSpec(
        "geoffhadfield32_content", "linkedin_content_pipeline_internal", _post_id,
        {
            "Hook": "hook", "Body": "body", "Key": "legacy_key",
            "Media": "media", "ScheduledFor": "scheduled_for",
            "Format": "format", "Pillar": "pillar", "Notes": "notes",
            "Source": "source_ref", "PostURN": "post_urn",
            "PublishedAt": "published_at", "Created": "created_at",
        },
        frozenset({"Draft", "In Queue", "Scheduled", "Published", "Needs Geoff"}),
        account="geoffhadfield32_content",
    ),
    MigrationSpec(
        "world_model_sports_content", "linkedin_content_pipeline_internal", _post_id,
        {
            "Hook": "hook", "Body": "body", "Key": "legacy_key",
            "Media": "media", "ScheduledFor": "scheduled_for",
            "Format": "format", "Pillar": "pillar", "Notes": "notes",
            "Source": "source_ref", "PostURN": "post_urn",
            "PublishedAt": "published_at", "Created": "created_at",
        },
        frozenset({"Draft", "In Queue", "Scheduled", "Published", "Needs Geoff"}),
        account="world_model_sports_content",
    ),
)


class AppFlowyReadClient:
    def __init__(
        self, *, base_url: str, workspace_id: str, db_map_path: Path,
        auth_url: str | None = None,
    ):
        self.base = base_url.rstrip("/")
        self.auth = (
            auth_url.rstrip("/") if auth_url
            else self.base + "/gotrue"
        )
        self.workspace_id = workspace_id
        self.db_map = json.loads(db_map_path.read_text(encoding="utf-8"))
        self.client = httpx.Client(timeout=60)
        self.token = ""

    def login(self, *, email: str, password: str) -> None:
        response = self.client.post(
            self.auth + "/token?grant_type=password",
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        self.token = _text(response.json().get("access_token"))
        if not self.token:
            raise AppFlowyMigrationError("AppFlowy login returned no access token")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def rows(self, db_name: str) -> list[dict[str, Any]]:
        entry = self.db_map.get(db_name)
        if not isinstance(entry, dict) or not entry.get("database_id"):
            raise AppFlowyMigrationError(f"database {db_name!r} is absent from DB map")
        base = (
            f"{self.base}/api/workspace/{self.workspace_id}/database/"
            f"{entry['database_id']}/row"
        )
        response = self.client.get(base, headers=self.headers)
        response.raise_for_status()
        row_ids = [str(row["id"]) for row in response.json()["data"]]
        details: list[dict[str, Any]] = []
        for start in range(0, len(row_ids), 40):
            response = self.client.get(
                base + "/detail", headers=self.headers,
                params={"ids": ",".join(row_ids[start:start + 40])},
            )
            response.raise_for_status()
            details.extend({
                **row,
                "database_id": entry["database_id"],
            } for row in response.json()["data"])
        if len(details) != len(row_ids):
            raise AppFlowyMigrationError(
                f"{db_name}: listed {len(row_ids)} rows but read {len(details)} details")
        return details


def _source_hash(row_id: str, cells: dict[str, Any]) -> str:
    raw = json.dumps(
        {"row_id": row_id, "cells": cells},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_action(status: str) -> str:
    if status in {"Broken", "Needs Geoff"}:
        return "block_card"
    if status in {"Reading", "Trying", "Using", "Scheduled"}:
        return "start_todo"
    if status in {"Read", "Done", "Published", "Archived", "Retired"}:
        return "finish_todo"
    if status == "In Queue":
        return "stage_card"
    return "add_mission_card"


def _imported_fields(
    spec: MigrationSpec,
    cells: dict[str, Any],
) -> dict[str, Any]:
    imported = {
        target: cells[source]
        for source, target in spec.fields.items()
        if source in cells and cells[source] not in (None, "")
    }
    for target, sources in (spec.field_aliases or {}).items():
        value = _value(cells, *sources)
        if value not in (None, ""):
            imported[target] = value
    return imported


def plan_database(
    *, spec: MigrationSpec, rows: list[dict[str, Any]],
    provider: CommandCenterBoardProvider, imported_at: str,
    identity_overrides: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    existing = {str(card["card_id"]): card for card in provider.list_cards()}
    operations: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    for row in rows:
        row_id = _text(row.get("id"))
        cells = row.get("cells")
        if not row_id or not isinstance(cells, dict):
            raise AppFlowyMigrationError(
                f"{spec.source_db}: every row needs a stable id and object cells")
        database_id = _text(row.get("database_id"))
        if not database_id:
            raise AppFlowyMigrationError(
                f"{spec.source_db} row {row_id}: source database id is missing")
        base_card_id = spec.identity(cells, row_id, spec.account)
        card_id = (identity_overrides or {}).get(
            (spec.source_db, row_id), base_card_id)
        previous_row = identities.get(card_id)
        if previous_row and previous_row != row_id:
            raise AppFlowyMigrationError(
                f"{spec.source_db}: rows {previous_row!r} and {row_id!r} "
                f"resolve to duplicate card id {card_id!r}")
        identities[card_id] = row_id
        status_value = cells.get("Status")
        if status_value in (None, ""):
            source_status = None
        elif not isinstance(status_value, str):
            raise AppFlowyMigrationError(
                f"{spec.source_db} row {row_id}: Status must be text, got "
                f"{type(status_value).__name__}")
        else:
            source_status = status_value.strip()
            if source_status not in spec.statuses:
                raise AppFlowyMigrationError(
                    f"{spec.source_db} row {row_id}: unsupported Status "
                    f"{source_status!r}; expected {sorted(spec.statuses)}")

        current = existing.get(card_id)
        imported = _imported_fields(spec, cells)
        if spec.account:
            imported["account"] = spec.account
        prior_imported = (
            current.get("appflowy_last_imported_fields", {}) if current else {})
        if not isinstance(prior_imported, dict):
            raise AppFlowyMigrationError(
                f"{spec.source_db} card {card_id!r}: invalid imported-field base")
        merged: dict[str, Any] = {}
        conflicts: dict[str, dict[str, Any]] = {}
        for field, incoming in imported.items():
            if (
                current is None or field not in current
                or current.get(field) == prior_imported.get(field)
                or current.get(field) == incoming
            ):
                merged[field] = incoming
            else:
                conflicts[field] = {
                    "board_value": current.get(field),
                    "appflowy_value": incoming,
                    "last_imported_value": prior_imported.get(field),
                }

        digest = _source_hash(row_id, cells)
        revisions = current.get("appflowy_revisions", []) if current else []
        if (
            not isinstance(revisions, list)
            or any(not isinstance(revision, dict) for revision in revisions)
        ):
            raise AppFlowyMigrationError(
                f"{spec.source_db} card {card_id!r}: invalid AppFlowy revisions")
        if not revisions or revisions[-1].get("source_sha256") != digest:
            revisions = [*revisions, {
                "source_sha256": digest,
                "captured_at": imported_at,
                "row_id": row_id,
                "cells": cells,
            }]
        fields = {
            **merged,
            "appflowy_row_id": row_id,
            "appflowy_database": spec.source_db,
            "appflowy_database_id": database_id,
            "appflowy_source_sha256": digest,
            "appflowy_source_cells": cells,
            "appflowy_revisions": revisions,
            "appflowy_revision_count": len(revisions),
            "appflowy_last_imported_fields": imported,
            "appflowy_importer": IMPORTER_ID,
            "appflowy_identity_base": base_card_id,
            "appflowy_identity_disambiguated": card_id != base_card_id,
            "appflowy_migration_conflicts": conflicts,
        }
        if current is None or current.get("appflowy_source_sha256") != digest:
            fields["appflowy_imported_at"] = imported_at
        changed_fields = sorted(
            key for key, value in fields.items()
            if current is None or current.get(key) != value
        )
        changed = bool(changed_fields)
        operations.append({
            "card_id": card_id,
            "fields": fields,
            "source_status": source_status,
            "needs_status": current is None or current.get("status") is None,
            "changed": changed,
            "changed_fields": changed_fields,
            "conflicts": conflicts,
        })
    changed_field_counts: dict[str, int] = {}
    for operation in operations:
        for field_name in operation["changed_fields"]:
            changed_field_counts[field_name] = (
                changed_field_counts.get(field_name, 0) + 1
            )
    return {
        "source_db": spec.source_db,
        "target_board": spec.target_board,
        "source_rows": len(rows),
        "create": sum(op["card_id"] not in existing for op in operations),
        "update": sum(op["card_id"] in existing and op["changed"] for op in operations),
        "noop": sum(op["card_id"] in existing and not op["changed"] for op in operations),
        "conflict_cards": sum(bool(op["conflicts"]) for op in operations),
        "status_initializations": sum(
            bool(op["needs_status"] and op["source_status"])
            for op in operations
        ),
        "changed_field_counts": changed_field_counts,
        "operations": operations,
    }


def apply_plan(
    *, spec: MigrationSpec, rows: list[dict[str, Any]],
    provider: CommandCenterBoardProvider, store_dir: Path,
    imported_at: str,
    identity_overrides: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    """Re-plan and apply while the target board cannot change underneath us."""
    with board_write_lock(store_dir, provider.board_id):
        # The preview plan validates every source before any write. This second
        # plan is deliberate: a cockpit edit may have landed after preview but
        # before this lock. Re-evaluating divergence here preserves that edit
        # and records a conflict instead of applying stale merged fields.
        plan = plan_database(
            spec=spec,
            rows=rows,
            provider=provider,
            imported_at=imported_at,
            identity_overrides=identity_overrides,
        )
        for operation in plan["operations"]:
            if operation["changed"]:
                provider.upsert_card(operation["card_id"], operation["fields"])
            if operation["needs_status"] and operation["source_status"]:
                emit_event(
                    provider.log,
                    action=_event_action(operation["source_status"]),
                    board_id=provider.board_id,
                    card_id=operation["card_id"],
                    source_surface="reconciler",
                    actor_type="system",
                    status_after=operation["source_status"],
                    evidence_ref=(
                        f"appflowy:{plan['source_db']}:"
                        f"{operation['fields']['appflowy_row_id']}"
                    ),
                )
        return plan


def migrate(
    *, source: AppFlowyReadClient, store_dir: Path, event_log_path: Path,
    apply: bool, now: datetime | None = None,
) -> dict[str, Any]:
    imported_at = (now or datetime.now(timezone.utc)).isoformat()
    fetched = [(spec, source.rows(spec.source_db)) for spec in SPECS]
    candidates: dict[tuple[str, str], list[tuple[MigrationSpec, str]]] = {}
    for spec, rows in fetched:
        for row in rows:
            row_id = _text(row.get("id"))
            cells = row.get("cells")
            if row_id and isinstance(cells, dict):
                base_id = spec.identity(cells, row_id, spec.account)
                candidates.setdefault((spec.target_board, base_id), []).append(
                    (spec, row_id))
    identity_overrides: dict[tuple[str, str], str] = {}
    for (target_board, base_id), owners in candidates.items():
        if len(owners) < 2:
            continue
        if any(not spec.account for spec, _ in owners):
            raise AppFlowyMigrationError(
                f"{target_board}: source rows collide on card id {base_id!r}")
        # Preserve the final source's legacy identity (matching the historical
        # apply order); qualify earlier account rows. This repairs an already
        # shared carrier without deleting or renaming it.
        for spec, row_id in owners[:-1]:
            identity_overrides[(spec.source_db, row_id)] = (
                f"{spec.account}:{base_id}")
    resolved: dict[tuple[str, str], tuple[str, str]] = {}
    for spec, rows in fetched:
        for row in rows:
            row_id = _text(row.get("id"))
            cells = row.get("cells")
            if not row_id or not isinstance(cells, dict):
                continue
            base_id = spec.identity(cells, row_id, spec.account)
            card_id = identity_overrides.get((spec.source_db, row_id), base_id)
            key = (spec.target_board, card_id)
            if key in resolved:
                raise AppFlowyMigrationError(
                    f"{spec.target_board}: unresolved source identity collision "
                    f"at {card_id!r}")
            resolved[key] = (spec.source_db, row_id)
    plans: list[tuple[
        dict[str, Any], CommandCenterBoardProvider, MigrationSpec,
        list[dict[str, Any]],
    ]] = []
    for spec, rows in fetched:
        provider = CommandCenterBoardProvider(
            board_id=spec.target_board,
            event_log=EventLog(event_log_path),
            store_dir=store_dir,
        )
        plans.append((
            plan_database(
                spec=spec, rows=rows, provider=provider, imported_at=imported_at,
                identity_overrides=identity_overrides),
            provider,
            spec,
            rows,
        ))
    if apply:
        plans = [
            (
                apply_plan(
                    spec=spec,
                    rows=rows,
                    provider=provider,
                    store_dir=store_dir,
                    imported_at=imported_at,
                    identity_overrides=identity_overrides,
                ),
                provider,
                spec,
                rows,
            )
            for _preview, provider, spec, rows in plans
        ]
    public = [
        {k: v for k, v in plan.items() if k != "operations"}
        for plan, _provider, _spec, _rows in plans
    ]
    return {
        "status": "applied" if apply else "dry_run",
        "writes_performed": apply,
        "source_rows": sum(plan["source_rows"] for plan in public),
        "identity_disambiguations": len(identity_overrides),
        "databases": public,
    }


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AppFlowyMigrationError(f"required environment variable {name} is missing")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(prog="appflowy-migrate")
    parser.add_argument("--db-map", default=str(DEFAULT_DB_MAP))
    parser.add_argument("--store-dir", default="generated/boards")
    parser.add_argument("--event-log", default="generated/kanban-events.jsonl")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        source = AppFlowyReadClient(
            base_url=_required_env("APPFLOWY_BASE_URL"),
            workspace_id=_required_env("APPFLOWY_WORKSPACE_ID"),
            db_map_path=Path(args.db_map),
            auth_url=os.environ.get("APPFLOWY_AUTH_URL") or (
                _required_env("APPFLOWY_BASE_URL") + "/gotrue"),
        )
        source.login(
            email=_required_env("APPFLOWY_EMAIL"),
            password=_required_env("APPFLOWY_PASSWORD"),
        )
        result = migrate(
            source=source,
            store_dir=Path(args.store_dir),
            event_log_path=Path(args.event_log),
            apply=args.apply,
        )
    except (AppFlowyMigrationError, httpx.HTTPError, OSError, json.JSONDecodeError) as exc:
        print(f"appflowy-migrate: BLOCKED\n  {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

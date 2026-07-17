"""Audited Books board enrichment from the local checklist and Open Library.

Dry-run is the default. Work-level aggregates remain separate from edition
fields, and refreshes preserve any operator value that diverged after import.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from command_center.boards.command_center_provider import CommandCenterBoardProvider
from command_center.books.enrichment import (
    BookIdentity,
    book_identity_from_card,
    checklist_match,
    extract_open_library_metadata,
    match_open_library_work,
    merge_imported_metadata,
    normalized_title,
    parse_book_checklist,
    title_matching_documents,
)
from command_center.kanban_sync.events import EventLog


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE = ROOT / "generated/boards"
DEFAULT_EVENTS = ROOT / "generated/kanban-events.jsonl"
DEFAULT_CHECKLIST = ROOT / "data/book-checklist.md"
DEFAULT_CACHE = ROOT / "generated/book-metadata-cache.json"
DEFAULT_REPORT = ROOT / "generated/book-metadata-report.json"
BOARD_ID = "reading_library"
CACHE_SCHEMA_VERSION = 1
IMPORTER_ID = "book-metadata-enrichment.v1"
OPEN_LIBRARY_FIELDS = (
    "key,title,author_name,subject,first_publish_year,isbn,"
    "number_of_pages_median,language,publisher"
)
_QUERY_QUALIFIER = re.compile(r"\s*\([^()]+\)\s*$")
_EVENT_ONLY_FIELDS = frozenset({
    "status", "board_id", "repo_id", "last_event_id", "last_actor",
})


class BookEnrichmentError(RuntimeError):
    pass


def _cache_key(identity: BookIdentity) -> str:
    value = f"{normalized_title(identity.title)}\0{normalized_title(identity.author)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _query_title(title: str) -> str:
    stripped = _QUERY_QUALIFIER.sub("", title).strip()
    return stripped or title.strip()


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": CACHE_SCHEMA_VERSION, "records": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BookEnrichmentError(f"metadata cache is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise BookEnrichmentError(
            f"metadata cache has an unsupported schema: {path}")
    if not isinstance(value.get("records"), dict):
        raise BookEnrichmentError(f"metadata cache records must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class OpenLibrarySearchClient:
    def __init__(self, *, contact: str | None = None, timeout: float = 30.0):
        user_agent = "llm-station-book-enrichment/1.0"
        if contact:
            user_agent += f" ({contact})"
        self.minimum_interval = 0.36 if contact else 1.05
        self._last_request_finished: float | None = None
        self._client = httpx.Client(
            base_url="https://openlibrary.org",
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def search(self, identities: list[BookIdentity], *, limit: int) -> dict[str, Any]:
        if self._last_request_finished is not None:
            remaining = self.minimum_interval - (
                time.monotonic() - self._last_request_finished)
            if remaining > 0:
                time.sleep(remaining)
        quoted = []
        for identity in identities:
            title = _query_title(identity.title)
            escaped = title.replace("\\", "\\\\").replace('"', '\\"')
            quoted.append(f'"{escaped}"')
        query = "title:(" + " OR ".join(dict.fromkeys(quoted)) + ")"
        try:
            response = self._client.get("/search.json", params={
                "q": query,
                "fields": OPEN_LIBRARY_FIELDS,
                "limit": limit,
            })
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BookEnrichmentError(f"Open Library search failed: {exc}") from exc
        finally:
            self._last_request_finished = time.monotonic()
        if not isinstance(payload, dict) or not isinstance(payload.get("docs"), list):
            raise BookEnrichmentError("Open Library response must contain a docs list")
        if not all(isinstance(document, dict) for document in payload["docs"]):
            raise BookEnrichmentError("Open Library docs must contain only objects")
        return payload


def _chunks(values: list[BookIdentity], size: int) -> Iterable[list[BookIdentity]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def fetch_records(
    identities: list[BookIdentity],
    *,
    cache: dict[str, Any],
    client: OpenLibrarySearchClient | None,
    refresh: bool,
    batch_size: int,
    result_limit: int,
    fetched_at: str,
) -> tuple[dict[str, Any], int]:
    records = cache["records"]
    unique = {
        _cache_key(identity): identity for identity in identities
    }
    missing = [
        identity for key, identity in unique.items()
        if refresh or key not in records
    ]
    if missing and client is None:
        raise BookEnrichmentError(
            f"offline cache is missing {len(missing)} book identities")
    requests = 0
    for batch in _chunks(missing, batch_size):
        assert client is not None
        payload = client.search(batch, limit=result_limit)
        requests += 1
        documents = payload["docs"]
        total = payload.get("numFound", payload.get("num_found"))
        truncated = isinstance(total, int) and total > len(documents)
        for identity in batch:
            records[_cache_key(identity)] = {
                "identity": {"title": identity.title, "author": identity.author},
                "fetched_at": fetched_at,
                "batch_truncated": truncated,
                "documents": title_matching_documents(identity, documents),
            }
    cache["updated_at"] = fetched_at
    return cache, requests


def _storage_fields(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in card.items()
        if key not in _EVENT_ONLY_FIELDS
    }


def build_plan(
    cards: list[dict[str, Any]],
    *,
    cache: dict[str, Any],
    checklist_text: str,
    checklist_sha256: str,
) -> dict[str, Any]:
    checklist_entries = parse_book_checklist(checklist_text)
    records = cache["records"]
    outcomes: Counter[str] = Counter()
    field_changes: Counter[str] = Counter()
    operations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    truncated_cards = 0

    for card in cards:
        card_id = card.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            raise BookEnrichmentError("every Books card must have a nonblank card_id")
        identity = book_identity_from_card(card)
        if identity is None:
            outcomes["missing_identity"] += 1
            unresolved.append({"card_id": card_id, "reason": "missing_identity"})
            continue

        local = checklist_match(identity, checklist_entries)
        incoming: dict[str, Any] = {}
        provenance: dict[str, Any] = {"schema_version": 1}
        genres: list[str] = []
        if local is not None:
            outcomes["checklist_matched"] += 1
            incoming["recommended_format"] = (
                "Audiobook" if local.format == "audio" else "Page / print")
            incoming["audio_hours_estimate"] = local.audio_hours
            if local.tier == "Fic":
                genres.append("Fiction")
            provenance["local_checklist"] = {
                "source": "data/book-checklist.md",
                "source_sha256": checklist_sha256,
                "match_basis": "exact_normalized_title_and_author_tokens",
                "title": local.title,
                "author": local.author,
            }
        else:
            outcomes["checklist_no_match"] += 1

        record = records.get(_cache_key(identity))
        if not isinstance(record, dict):
            raise BookEnrichmentError(
                f"metadata cache record missing for {card_id!r}")
        documents = record.get("documents")
        if not isinstance(documents, list) or not all(
            isinstance(document, dict) for document in documents
        ):
            raise BookEnrichmentError(
                f"metadata cache documents are invalid for {card_id!r}")
        if record.get("batch_truncated") is True:
            truncated_cards += 1
        match = match_open_library_work(identity, documents)
        outcomes[f"open_library_{match.status}"] += 1
        if match.work is not None:
            external = extract_open_library_metadata(match.work)
            for genre in external.pop("genres", []):
                if genre not in genres:
                    genres.append(genre)
            incoming.update(external)
            provenance["open_library"] = {
                "work_id": incoming["open_library_work_id"],
                "url": incoming["open_library_url"],
                "fetched_at": record.get("fetched_at"),
                "match_basis": match.reason,
            }
        else:
            unresolved.append({
                "card_id": card_id,
                "title": identity.title,
                "author": identity.author,
                "reason": f"open_library_{match.status}",
                "candidate_work_ids": list(match.candidate_work_ids),
                "batch_truncated": record.get("batch_truncated") is True,
            })
        if genres:
            incoming["genres"] = genres
        if not incoming:
            continue
        incoming["book_metadata_provenance"] = provenance
        incoming["book_metadata_importer"] = IMPORTER_ID
        merged = merge_imported_metadata(_storage_fields(card), incoming)
        for field in merged.changed_fields:
            field_changes[field] += 1
        operations.append({
            "card_id": card_id,
            "incoming": incoming,
            "changed": bool(merged.changed_fields),
            "changed_fields": list(merged.changed_fields),
            "conflicts": merged.conflicts,
        })

    return {
        "cards": len(cards),
        "checklist_rows": len(checklist_entries),
        "outcomes": dict(sorted(outcomes.items())),
        "changed_cards": sum(operation["changed"] for operation in operations),
        "conflict_cards": sum(bool(operation["conflicts"]) for operation in operations),
        "field_change_counts": dict(sorted(field_changes.items())),
        "truncated_batch_cards": truncated_cards,
        "unresolved": unresolved,
        "operations": operations,
    }


def apply_plan(
    provider: CommandCenterBoardProvider,
    plan: dict[str, Any],
) -> int:
    mutations = {}
    for operation in plan["operations"]:
        if not operation["changed"]:
            continue
        incoming = operation["incoming"]

        def mutate(
            current: dict[str, Any], *, incoming_fields: dict[str, Any] = incoming,
        ) -> dict[str, Any]:
            return merge_imported_metadata(current, incoming_fields).fields

        mutations[operation["card_id"]] = mutate
    provider.mutate_card_fields_batch(mutations)
    return len(mutations)


def enrich(
    *,
    store_dir: Path,
    event_log: Path,
    checklist_path: Path,
    cache_path: Path,
    report_path: Path,
    apply: bool,
    offline: bool,
    refresh: bool,
    contact: str | None,
    batch_size: int,
    result_limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    try:
        checklist_text = checklist_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BookEnrichmentError(
            f"book checklist is unreadable: {checklist_path}: {exc}") from exc
    checklist_sha = hashlib.sha256(checklist_text.encode("utf-8")).hexdigest()
    provider = CommandCenterBoardProvider(
        board_id=BOARD_ID,
        event_log=EventLog(event_log),
        store_dir=store_dir,
    )
    cards = provider.list_cards()
    identities = [
        identity for card in cards
        if (identity := book_identity_from_card(card)) is not None
    ]
    cache = _load_cache(cache_path)
    client = None if offline else OpenLibrarySearchClient(contact=contact)
    try:
        cache, requests = fetch_records(
            identities,
            cache=cache,
            client=client,
            refresh=refresh,
            batch_size=batch_size,
            result_limit=result_limit,
            fetched_at=generated_at,
        )
    finally:
        if client is not None:
            client.close()
    _write_json(cache_path, cache)
    plan = build_plan(
        cards,
        cache=cache,
        checklist_text=checklist_text,
        checklist_sha256=checklist_sha,
    )
    applied_cards = apply_plan(provider, plan) if apply else 0
    public_plan = {key: value for key, value in plan.items() if key != "operations"}
    report = {
        "status": "applied" if apply else "dry_run",
        "writes_performed": apply,
        "generated_at": generated_at,
        "board_id": BOARD_ID,
        "source": {
            "checklist": str(checklist_path),
            "checklist_sha256": checklist_sha,
            "open_library_requests": requests,
            "cache": str(cache_path),
        },
        **public_plan,
        "applied_cards": applied_cards,
    }
    _write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cc book-enrich")
    parser.add_argument("--store-dir", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--event-log", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--contact",
        help="contact email included in the Open Library User-Agent",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--result-limit", type=int, default=200)
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 20:
        parser.error("--batch-size must be between 1 and 20")
    if args.result_limit < 1 or args.result_limit > 1000:
        parser.error("--result-limit must be between 1 and 1000")
    if args.offline and args.refresh:
        parser.error("--offline and --refresh cannot be combined")
    try:
        report = enrich(
            store_dir=args.store_dir,
            event_log=args.event_log,
            checklist_path=args.checklist,
            cache_path=args.cache,
            report_path=args.report,
            apply=args.apply,
            offline=args.offline,
            refresh=args.refresh,
            contact=args.contact,
            batch_size=args.batch_size,
            result_limit=args.result_limit,
        )
    except BookEnrichmentError as exc:
        print(f"book-enrich: BLOCKED\n  {exc}", file=sys.stderr)
        return 2
    summary = {key: report[key] for key in (
        "status", "writes_performed", "cards", "changed_cards",
        "applied_cards", "conflict_cards", "truncated_batch_cards", "outcomes",
    )}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

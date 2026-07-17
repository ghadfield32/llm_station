"""Pure matching and extraction rules for provenance-backed book metadata."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Literal


_CHECKLIST_LINE = re.compile(
    r"^- \[ \] (?P<title>.+?) — (?P<author>.+?) · "
    r"`\[(?P<tier>[^\]]+)\]` (?P<format>audio|page) · "
    r"~(?P<hours>\d+(?:\.\d+)?)h(?:\b|$)"
)
_TRAILING_QUALIFIER = re.compile(r"\s*\([^()]++\)\s*$")
_STRUCTURED_CATEGORY = re.compile(r"^(?P<category>[A-Z][A-Z &'’-]+)\s*/\s*")
_AUTHOR_STOP_TOKENS = frozenset({
    "and", "edited", "editor", "editors", "eds", "the", "translator",
    "translators", "with", "et", "al",
})


@dataclass(frozen=True)
class BookIdentity:
    title: str
    author: str


@dataclass(frozen=True)
class ChecklistEntry:
    title: str
    author: str
    tier: str
    format: Literal["audio", "page"]
    audio_hours: float


@dataclass(frozen=True)
class WorkMatch:
    status: Literal["matched", "ambiguous", "no_match", "missing_identity"]
    reason: str
    work: dict[str, Any] | None = None
    candidate_work_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataMerge:
    fields: dict[str, Any]
    conflicts: dict[str, dict[str, Any]]
    changed_fields: tuple[str, ...]


def _normalized_tokens(value: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", value)
    folded = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()
    return tuple(re.findall(r"[a-z0-9]+", folded))


def normalized_title(value: str) -> str:
    return " ".join(_normalized_tokens(value))


def title_variants(value: str) -> frozenset[str]:
    variants = {normalized_title(value)}
    without_qualifier = _TRAILING_QUALIFIER.sub("", value).strip()
    if without_qualifier:
        variants.add(normalized_title(without_qualifier))
    return frozenset(variant for variant in variants if variant)


def _author_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token for token in _normalized_tokens(value)
        if len(token) > 1 and token not in _AUTHOR_STOP_TOKENS
    )


def parse_book_checklist(markdown: str) -> list[ChecklistEntry]:
    """Parse only explicit book rows; prose and research sprints are ignored."""
    entries: list[ChecklistEntry] = []
    for raw_line in markdown.splitlines():
        match = _CHECKLIST_LINE.match(raw_line.strip())
        if match is None:
            continue
        title = match.group("title").replace("**", "").strip()
        if title.endswith("★"):
            title = title[:-1].rstrip()
        entries.append(ChecklistEntry(
            title=title,
            author=match.group("author").strip(),
            tier=match.group("tier").strip(),
            format=match.group("format"),  # type: ignore[arg-type]
            audio_hours=float(match.group("hours")),
        ))
    return entries


def book_identity_from_card(card: dict[str, Any]) -> BookIdentity | None:
    source_cells = card.get("appflowy_source_cells")
    if source_cells is not None and not isinstance(source_cells, dict):
        raise ValueError("book appflowy_source_cells must be an object")
    source_cells = source_cells or {}
    title = ""
    for field, value in (
        ("title", card.get("title")),
        ("Title", card.get("Title")),
        ("Name", card.get("Name")),
        ("appflowy_source_cells.Title", source_cells.get("Title")),
        ("appflowy_source_cells.Name", source_cells.get("Name")),
    ):
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ValueError(f"book {field} must be text")
        title = value.strip()
        if title:
            break
    author = card.get("author")
    if author in (None, ""):
        return None
    if not isinstance(author, str):
        raise ValueError("book author must be text")
    author = author.strip()
    return BookIdentity(title, author) if title and author else None


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merge_imported_metadata(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> MetadataMerge:
    """Merge a source refresh while retaining any divergent operator values."""
    prior = current.get("book_metadata_last_imported_fields", {})
    if not isinstance(prior, dict):
        raise ValueError("book_metadata_last_imported_fields must be an object")
    fields = dict(current)
    imported = dict(prior)
    conflicts: dict[str, dict[str, Any]] = {}
    for field, source_value in incoming.items():
        board_value = current.get(field)
        prior_value = prior.get(field)
        if not _blank(board_value) and board_value != prior_value:
            if board_value != source_value:
                conflicts[field] = {
                    "board_value": board_value,
                    "source_value": source_value,
                    "last_imported_value": prior_value,
                }
            continue
        fields[field] = source_value
        imported[field] = source_value
    fields["book_metadata_last_imported_fields"] = imported
    if conflicts:
        fields["book_metadata_conflicts"] = conflicts
    else:
        fields.pop("book_metadata_conflicts", None)
    changed = tuple(sorted(
        field for field in set(current) | set(fields)
        if current.get(field) != fields.get(field)
    ))
    return MetadataMerge(fields=fields, conflicts=conflicts, changed_fields=changed)


def checklist_match(
    identity: BookIdentity,
    entries: Iterable[ChecklistEntry],
) -> ChecklistEntry | None:
    wanted_titles = title_variants(identity.title)
    wanted_authors = _author_tokens(identity.author)
    if not wanted_titles or not wanted_authors:
        return None
    matches = [
        entry for entry in entries
        if normalized_title(entry.title) in wanted_titles
        and wanted_authors.issubset(_author_tokens(entry.author))
    ]
    return matches[0] if len(matches) == 1 else None


def title_matching_documents(
    identity: BookIdentity,
    documents: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    variants = title_variants(identity.title)
    return [
        document for document in documents
        if isinstance(document.get("title"), str)
        and normalized_title(document["title"]) in variants
    ]


def match_open_library_work(
    identity: BookIdentity,
    documents: Iterable[dict[str, Any]],
) -> WorkMatch:
    """Accept one exact normalized work only; never select among editions."""
    source_authors = _author_tokens(identity.author)
    if not title_variants(identity.title) or not source_authors:
        return WorkMatch(
            status="missing_identity",
            reason="nonblank_title_and_author_required",
        )

    candidates: dict[str, dict[str, Any]] = {}
    for document in title_matching_documents(identity, documents):
        authors = document.get("author_name")
        if not isinstance(authors, list) or not all(
            isinstance(author, str) for author in authors
        ):
            continue
        candidate_authors = _author_tokens(" ".join(authors))
        if not source_authors.issubset(candidate_authors):
            continue
        key = document.get("key")
        if not isinstance(key, str) or not key.startswith("/works/"):
            continue
        candidates.setdefault(key, document)

    candidate_ids = tuple(sorted(candidates))
    if not candidate_ids:
        return WorkMatch(
            status="no_match",
            reason="no_exact_normalized_title_and_author_match",
        )
    if len(candidate_ids) > 1:
        return WorkMatch(
            status="ambiguous",
            reason="multiple_exact_title_author_works",
            candidate_work_ids=candidate_ids,
        )
    return WorkMatch(
        status="matched",
        reason="exact_normalized_title_and_author_tokens",
        work=candidates[candidate_ids[0]],
        candidate_work_ids=candidate_ids,
    )


def _string_list(work: dict[str, Any], field: str) -> list[str]:
    value = work.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Open Library field {field!r} must be a string list")
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))


def _structured_genres(subjects: Iterable[str]) -> list[str]:
    genres: list[str] = []
    for subject in subjects:
        match = _STRUCTURED_CATEGORY.match(subject)
        if match is None:
            continue
        category = match.group("category").strip().title()
        if category not in genres:
            genres.append(category)
    return genres


def extract_open_library_metadata(work: dict[str, Any]) -> dict[str, Any]:
    """Extract work-level facts without promoting edition aggregates to facts."""
    key = work.get("key")
    if not isinstance(key, str) or not key.startswith("/works/"):
        raise ValueError("matched Open Library work must have a /works/ key")
    subjects = _string_list(work, "subject")
    metadata: dict[str, Any] = {
        "open_library_work_id": key,
        "open_library_url": f"https://openlibrary.org{key}",
    }
    values = {
        "genres": _structured_genres(subjects),
        "subjects": subjects,
        "languages": _string_list(work, "language"),
        "publishers": _string_list(work, "publisher"),
        "isbns": _string_list(work, "isbn"),
    }
    metadata.update({name: value for name, value in values.items() if value})
    for source_name, target_name in (
        ("first_publish_year", "first_publish_year"),
        ("number_of_pages_median", "page_count_median"),
    ):
        value = work.get(source_name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Open Library field {source_name!r} must be an integer")
        metadata[target_name] = value
    return metadata

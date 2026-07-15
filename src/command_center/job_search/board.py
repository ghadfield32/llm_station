from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from command_center.job_search.application_memory import (
    create_prepared_application,
    load_application,
)
from command_center.job_search.cache_io import read_json_file
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.retention import plan_retention
from command_center.job_search.scoring import application_id_for
from command_center.job_search.schemas import (
    AutomationClass,
    AutomationResult,
    CanonicalJob,
    FitResult,
    JobSearchConfig,
    ResumeSelection,
    repo_root,
)

BoardBackend = Literal["local", "internal"]

BOARD_COLUMNS = [
    "Suggested Jobs",
    "Selected by Geoff",
    "In Progress",
    "Needs Geoff",
    "Completed",
    "Interviewing",
    "Rejected / Skip",
    "Closed / Archived",
]

REQUIRED_CARD_FIELDS = [
    "job_key",
    "company",
    "role_title",
    "location",
    "remote_type",
    "source",
    "portal",
    "apply_url",
    "salary_text",
    "salary_min",
    "salary_max",
    "category",
    "fit_score",
    "automation_class",
    "manual_reason",
    "resume_variant",
    "why_apply",
    "risks",
    "deadline",
    "last_seen_at",
    "application_id",
    "next_action",
    "materials_path",
    "company_tier",
    "score_explanation",
    "claude_review_url",
]

FIELD_TYPES: dict[str, str] = {
    "job_key": "string",
    "company": "string",
    "role_title": "string",
    "location": "string",
    "remote_type": "remote | hybrid | onsite | unknown",
    "source": "string",
    "portal": "string",
    "apply_url": "string",
    "salary_text": "string | null",
    "salary_min": "number | null",
    "salary_max": "number | null",
    "category": "string",
    "fit_score": "number",
    "automation_class": "bot_possible | prepare_only | manual_required | skip",
    "manual_reason": "string | null",
    "resume_variant": "string",
    "why_apply": "string",
    "risks": "string",
    "deadline": "date | null",
    "last_seen_at": "datetime",
    "application_id": "string | null",
    "next_action": "string | null",
    "materials_path": "string | null",
    "company_tier": "none | sports_team | sports_tech | faang | major_other",
    "score_explanation": "string",
    "claude_review_url": "string",
}

BOT_OWNED_FIELDS = {
    "fit_score",
    "automation_class",
    "category",
    "manual_reason",
    "resume_variant",
    "risks",
    "why_apply",
    "last_seen_at",
    "materials_path",
    "application_id",
    "company_tier",
    "score_explanation",
    "claude_review_url",
}
MIXED_UPDATE_WHEN_EMPTY_FIELDS = {"salary_text", "deadline", "next_action"}
USER_OWNED_FIELDS = {"notes", "custom_priority", "geoff_comments", "manual_decision"}

STATE_SCHEMA = "command-center.job-search-board-state.v1"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _merged_env(env: dict[str, str] | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    values.update(_read_dotenv(repo_root() / ".env"))
    values.update(os.environ)
    if env is not None:
        values.update(env)
    return values


# ---- internal backend (command_center_ui provider) --------------------------
# The cockpit-native board: rich fields live in the BoardProvider card store
# under generated/boards/, status truth is the governed kanban event log. Same
# columns, same selection gate; the cockpit "Jobs" domain reads it directly.
INTERNAL_BOARD_ID = "job_search_pipeline_internal"
# column -> the governed verb that legally produces it (wall verbs unmappable,
# so no internal write can ever approve/merge/delete by construction).
_INTERNAL_COLUMN_ACTIONS = {
    "Suggested Jobs": "add_mission_card",
    "Selected by Geoff": "stage_card",
    "In Progress": "start_todo",
    "Needs Geoff": "block_card",
    "Completed": "finish_todo",
    "Interviewing": "stage_card",
    "Rejected / Skip": "reject_card",
    "Closed / Archived": "finish_todo",
}
_INTERNAL_FOLD_KEYS = frozenset({
    "card_id", "status", "board_id", "repo_id", "last_event_id", "last_actor"})


def _internal_provider(env: dict[str, str] | None = None):
    from command_center.boards.command_center_provider import (
        CommandCenterBoardProvider,
    )
    from command_center.kanban_sync.events import EventLog

    merged = _merged_env(env)
    log = Path(merged.get("KANBAN_EVENT_LOG")
               or repo_root() / "generated" / "kanban-events.jsonl")
    store = Path(merged.get("KANBAN_BOARD_STORE")
                 or repo_root() / "generated" / "boards")
    return CommandCenterBoardProvider(
        board_id=INTERNAL_BOARD_ID, event_log=EventLog(log), store_dir=store)


def _internal_cards(provider) -> list[dict[str, Any]]:
    """Provider cards -> the job-search card shape ({card_id, column, fields})."""
    cards = []
    for card in provider.list_cards():
        fields = {k: v for k, v in card.items() if k not in _INTERNAL_FOLD_KEYS}
        cards.append({"card_id": card["card_id"],
                      "column": card.get("status") or "Suggested Jobs",
                      "fields": fields})
    return cards


def _internal_write(provider, card: dict[str, Any], *,
                    previous_column: str | None) -> None:
    """Upsert the card's fields; emit the governed event only on a column change."""
    from command_center.kanban_sync.events import emit_event

    provider.upsert_card(card["card_id"], dict(card.get("fields") or {}))
    column = card.get("column") or "Suggested Jobs"
    if column == previous_column:
        return
    action = _INTERNAL_COLUMN_ACTIONS.get(column)
    if action is None:
        raise RuntimeError(
            f"no governed action produces column {column!r} on the internal board")
    emit_event(provider.log, action=action, board_id=provider.board_id,
               card_id=card["card_id"], source_surface="internal_ui",
               actor_type="agent", status_before=previous_column,
               status_after=column)


def board_state_path(root: Path, cfg: JobSearchConfig | None = None) -> Path:
    config = cfg or load_config()
    return root / "board" / f"{config.job_search.board_name}.json"


def board_schema() -> dict[str, Any]:
    return {
        "board_name": load_config().job_search.board_name,
        "columns": BOARD_COLUMNS,
        "required_fields": REQUIRED_CARD_FIELDS,
        "field_types": FIELD_TYPES,
        "field_ownership": {
            "bot_owned": sorted(BOT_OWNED_FIELDS),
            "mixed_update_when_empty": sorted(MIXED_UPDATE_WHEN_EMPTY_FIELDS),
            "user_owned": sorted(USER_OWNED_FIELDS),
        },
    }


def _empty_state(cfg: JobSearchConfig) -> dict[str, Any]:
    now = _now()
    return {
        "schema_version": STATE_SCHEMA,
        "board_name": cfg.job_search.board_name,
        "columns": BOARD_COLUMNS,
        "field_types": FIELD_TYPES,
        "cards": [],
        "events": [],
        "created_at": now,
        "updated_at": now,
    }


def _normalize_state(state: dict[str, Any], cfg: JobSearchConfig) -> dict[str, Any]:
    state.setdefault("schema_version", STATE_SCHEMA)
    state.setdefault("board_name", cfg.job_search.board_name)
    state.setdefault("columns", [])
    state.setdefault("field_types", {})
    state.setdefault("cards", [])
    state.setdefault("events", [])
    for column in BOARD_COLUMNS:
        if column not in state["columns"]:
            state["columns"].append(column)
    state["field_types"].update(FIELD_TYPES)
    return state


def load_local_state(root: Path, cfg: JobSearchConfig | None = None) -> dict[str, Any]:
    config = cfg or load_config()
    path = board_state_path(root, config)
    if not path.exists():
        return _empty_state(config)
    return _normalize_state(json.loads(path.read_text(encoding="utf-8")), config)


def save_local_state(root: Path, state: dict[str, Any], cfg: JobSearchConfig | None = None) -> Path:
    config = cfg or load_config()
    ensure_data_dirs(root)
    path = board_state_path(root, config)
    state["updated_at"] = _now()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _card_id(job_key: str) -> str:
    return f"job_{job_key}"


def _event(
    state: dict[str, Any],
    *,
    action: str,
    card_id: str,
    from_column: str | None,
    to_column: str | None,
) -> None:
    state.setdefault("events", []).append(
        {
            "ts": _now(),
            "action": action,
            "card_id": card_id,
            "from_column": from_column,
            "to_column": to_column,
            "actor": "job_search_bot",
        }
    )


def _set_column(state: dict[str, Any], card: dict[str, Any], column: str, action: str) -> None:
    previous = card.get("column")
    if previous == column:
        return
    card["column"] = column
    _event(state, action=action, card_id=card["card_id"], from_column=previous, to_column=column)


def _load_suggestions(root: Path) -> list[dict[str, Any]]:
    suggestions = []
    for path in sorted((root / "source_cache" / "suggestions").glob("*.json")):
        suggestions.append(read_json_file(path))
    return suggestions


def _load_suggestion(root: Path, job_key: str) -> dict[str, Any]:
    path = root / "source_cache" / "suggestions" / f"{job_key}.json"
    if not path.exists():
        raise RuntimeError(f"missing cached suggestion for job_key {job_key!r}")
    return read_json_file(path)


def _suggestion_rank_key(suggestion: dict[str, Any]) -> tuple[int, str, str, str]:
    job = suggestion.get("job", {})
    return (
        -int(suggestion.get("fit", {}).get("score") or 0),
        str(job.get("company") or ""),
        str(job.get("role_title") or ""),
        str(job.get("job_key") or ""),
    )


def _suggestion_automation_class(suggestion: dict[str, Any]) -> str:
    return str(suggestion.get("automation", {}).get("value") or "")


def _suggestion_class_counts(suggestions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for suggestion in suggestions:
        key = _suggestion_automation_class(suggestion) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _daily_suggestion_limit(
    suggestions: list[dict[str, Any]],
    cfg: JobSearchConfig,
) -> list[dict[str, Any]]:
    ranked = sorted(suggestions, key=_suggestion_rank_key)
    limit = cfg.job_search.max_suggested_jobs_per_day
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()

    def add_group(automation_class: str, group_limit: int) -> None:
        if group_limit <= 0:
            return
        for suggestion in ranked:
            if len(selected) >= limit:
                return
            job_key = str(suggestion.get("job", {}).get("job_key") or "")
            if job_key in selected_keys:
                continue
            if _suggestion_automation_class(suggestion) != automation_class:
                continue
            selected.append(suggestion)
            selected_keys.add(job_key)
            if sum(1 for item in selected if _suggestion_automation_class(item) == automation_class) >= group_limit:
                return

    add_group("bot_possible", cfg.job_search.max_bot_possible_suggestions_per_day)
    add_group("manual_required", cfg.job_search.max_manual_required_suggestions_per_day)
    for suggestion in ranked:
        if len(selected) >= limit:
            break
        job_key = str(suggestion.get("job", {}).get("job_key") or "")
        if job_key not in selected_keys:
            selected.append(suggestion)
            selected_keys.add(job_key)
    return selected


def _claude_review_url(job: dict[str, Any], fit: dict[str, Any]) -> str:
    prompt = (
        f"Help me review this job before I apply: {job.get('company', '')} - "
        f"{job.get('role_title', '')}. Posting: {job.get('apply_url', '')}. "
        f"Our fit score is {fit.get('score', '?')}/100. "
        f"Reasons: {'; '.join(fit.get('reasons') or [])}. "
        "Tell me what to double check, what to ask about, and how to position my experience."
    )
    return "https://claude.ai/new?q=" + quote(prompt)


def _normalize_ts(value: Any) -> Any:
    """One UTC ISO-8601 shape (+00:00) for timestamps. Live sources emit
    date-only and Z-suffixed variants; a single format keeps card sorting and
    display honest. Unparseable values pass through untouched."""
    if not isinstance(value, str) or not value.strip():
        return value
    raw = value.strip()
    try:
        if len(raw) == 10:  # YYYY-MM-DD (seen from live feeds): midnight UTC
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).isoformat()


def fields_from_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    job = suggestion["job"]
    fit = suggestion["fit"]
    automation = suggestion["automation"]
    selection = suggestion["selection"]
    blockers = automation.get("blockers") or []
    risks = list(fit.get("risks") or []) + list(fit.get("gaps") or [])
    return {
        "job_key": job["job_key"],
        "company": job["company"],
        "role_title": job["role_title"],
        "location": job["location"],
        "remote_type": job.get("remote_type", "unknown"),
        "source": job.get("source", "local_file"),
        "portal": job.get("portal", "unknown"),
        "apply_url": job.get("apply_url", ""),
        "salary_text": job.get("salary_text"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "category": selection["resume_variant"],
        "fit_score": fit["score"],
        "automation_class": automation["value"],
        "manual_reason": "; ".join(blockers) if blockers else automation.get("reason"),
        "resume_variant": selection["resume_variant"],
        "why_apply": "; ".join(fit.get("reasons") or []),
        "risks": "; ".join(risks),
        "deadline": job.get("deadline"),
        "last_seen_at": _normalize_ts(job["last_seen_at"]),
        "application_id": None,
        "next_action": "Review suggestion and move to Selected by Geoff if it is worth applying.",
        "materials_path": None,
        "company_tier": fit.get("company_tier", "none"),
        "score_explanation": fit.get("explanation", ""),
        "claude_review_url": _claude_review_url(job, fit),
    }


def _new_card_from_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    fields = fields_from_suggestion(suggestion)
    return {
        "card_id": _card_id(fields["job_key"]),
        "column": "Suggested Jobs",
        "fields": fields,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _merge_card_fields(existing: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    fields = existing.setdefault("fields", {})
    for name in REQUIRED_CARD_FIELDS:
        if name not in fields:
            fields[name] = incoming.get(name)
            changed.append(name)
    for name in BOT_OWNED_FIELDS:
        if fields.get(name) != incoming.get(name):
            fields[name] = incoming.get(name)
            changed.append(name)
    for name in MIXED_UPDATE_WHEN_EMPTY_FIELDS:
        if not fields.get(name) and incoming.get(name):
            fields[name] = incoming.get(name)
            changed.append(name)
    existing["updated_at"] = _now()
    return sorted(set(changed))


def _find_cards_by_job_key(state: dict[str, Any], job_key: str) -> list[dict[str, Any]]:
    return [c for c in state["cards"] if c.get("fields", {}).get("job_key") == job_key]


def _application_exists(root: Path, application_id: str | None) -> bool:
    if not application_id:
        return False
    return (root / "applications_active" / application_id / "application.yml").exists()


def board_setup(
    *,
    backend: BoardBackend = "internal",
    apply: bool = False,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    schema = board_schema()
    if backend == "internal":
        provider = _internal_provider(env)
        exists = provider.store_dir.is_dir()
        if apply:
            provider.store_dir.mkdir(parents=True, exist_ok=True)
        return {
            "operation": "board_setup",
            "backend": backend,
            "status": "applied" if apply else "dry_run",
            "board_id": INTERNAL_BOARD_ID,
            "board_name": config.job_search.board_name,
            "schema": schema,
            "card_store": str(provider.store_dir),
            "event_log": str(provider.log.path),
            "registry_entry": "configs/kanban_boards.yaml: job_search_pipeline_internal",
            "would_create_store": not exists,
            "writes_performed": apply,
        }

    state = load_local_state(base, config)
    path = board_state_path(base, config)
    if not apply:
        return {
            "operation": "board_setup",
            "backend": backend,
            "status": "dry_run",
            "board_name": config.job_search.board_name,
            "schema": schema,
            "state_path": str(path),
            "would_create_state_file": not path.exists(),
            "writes_performed": False,
        }
    save_local_state(base, state, config)
    return {
        "operation": "board_setup",
        "backend": backend,
        "status": "applied",
        "board_name": config.job_search.board_name,
        "state_path": str(path),
        "writes_performed": True,
    }


def analyze_cards(cards: list[dict[str, Any]], *, root: Path) -> dict[str, Any]:
    counts = {column: 0 for column in BOARD_COLUMNS}
    missing_required: list[dict[str, Any]] = []
    job_key_to_cards: dict[str, list[str]] = {}
    for card in cards:
        column = card.get("column") or "Suggested Jobs"
        counts[column] = counts.get(column, 0) + 1
        fields = card.get("fields", {})
        missing = [name for name in REQUIRED_CARD_FIELDS if name not in fields]
        if missing:
            missing_required.append({"card_id": card.get("card_id"), "missing_fields": missing})
        job_key = fields.get("job_key")
        if job_key:
            job_key_to_cards.setdefault(str(job_key), []).append(str(card.get("card_id")))
    duplicates = [
        {"job_key": job_key, "card_ids": card_ids}
        for job_key, card_ids in sorted(job_key_to_cards.items())
        if len(card_ids) > 1
    ]
    retention_rows = {row["application_id"]: row for row in plan_retention(root=root)["records"]}
    completed_missing_memory = [
        {
            "card_id": card["card_id"],
            "application_id": card.get("fields", {}).get("application_id"),
        }
        for card in cards
        if card.get("column") == "Completed"
        and not _application_exists(root, card.get("fields", {}).get("application_id"))
    ]
    active_retention = []
    for card in cards:
        if card.get("column") not in {"Interviewing", "Completed"}:
            continue
        application_id = card.get("fields", {}).get("application_id")
        if application_id and application_id in retention_rows:
            active_retention.append(
                {
                    "card_id": card["card_id"],
                    "application_id": application_id,
                    "retention": retention_rows[application_id],
                }
            )
    return {
        "counts_by_column": counts,
        "cards_by_column": {
            column: [
                {
                    "card_id": card.get("card_id"),
                    "job_key": card.get("fields", {}).get("job_key"),
                    "company": card.get("fields", {}).get("company"),
                    "role_title": card.get("fields", {}).get("role_title"),
                    "fit_score": card.get("fields", {}).get("fit_score"),
                }
                for card in cards
                if card.get("column") == column
            ]
            for column in BOARD_COLUMNS
        },
        "missing_required_fields": missing_required,
        "duplicate_job_keys": duplicates,
        "selected_ready": [
            card for card in cards if card.get("column") == "Selected by Geoff"
        ],
        "blocked_manual_cards": [
            card
            for card in cards
            if card.get("column") == "Needs Geoff"
            or card.get("fields", {}).get("automation_class") in {"manual_required", "prepare_only"}
        ],
        "completed_missing_application_memory": completed_missing_memory,
        "active_retention": active_retention,
    }


def board_snapshot(
    *,
    backend: BoardBackend = "internal",
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    if backend == "internal":
        cards = _internal_cards(_internal_provider(env))
    else:
        cards = load_local_state(base, config)["cards"]
    return {
        "operation": "board_snapshot",
        "backend": backend,
        "status": "ok",
        "board_name": config.job_search.board_name,
        "writes_performed": False,
        **analyze_cards(cards, root=base),
    }


def board_doctor(
    *,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Health-check the authoritative first-party Jobs board."""
    snapshot = board_snapshot(backend="internal", root=root, cfg=cfg, env=env)
    return {
        "operation": "board_doctor",
        "backend": "internal",
        "status": snapshot["status"],
        "board_name": snapshot["board_name"],
        "checks": {
            "board_store_readable": True,
            "canonical_columns": list(BOARD_COLUMNS),
            "cards": snapshot["total_cards"],
        },
        "writes_performed": False,
    }


def publish_suggestions(
    *,
    backend: BoardBackend = "internal",
    apply: bool = False,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
    # Live paths (daily DAG, CLI default) pass ("fixture",) so example postings
    # from docs/job_search/examples can never land on a real board as jobs;
    # the default () keeps direct/test callers unchanged.
    exclude_sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    all_suggestions = _load_suggestions(base)
    excluded = {s.strip().lower() for s in exclude_sources}
    eligible_suggestions = [
        item
        for item in all_suggestions
        if int(item["fit"]["score"]) >= config.ranking.min_score_to_show
        and (item["job"].get("source") or "").strip().lower() not in excluded
    ]
    suggestions = _daily_suggestion_limit(eligible_suggestions, config)
    daily_suggestion_targets = {
        "bot_possible": config.job_search.max_bot_possible_suggestions_per_day,
        "manual_required": config.job_search.max_manual_required_suggestions_per_day,
        "total": config.job_search.max_suggested_jobs_per_day,
    }
    below_threshold = {
        str(item["job"]["job_key"]): item
        for item in all_suggestions
        if int(item["fit"]["score"]) < config.ranking.min_score_to_show
    }
    if backend == "internal":
        provider = _internal_provider(env)
        existing = _internal_cards(provider)
        result = _publish_into_cards(
            existing,
            suggestions,
            apply=apply,
            below_threshold=below_threshold,
            min_score_to_show=config.ranking.min_score_to_show,
            eligible_suggestions_seen=len(eligible_suggestions),
            daily_suggestion_limit=config.job_search.max_suggested_jobs_per_day,
            eligible_suggestion_counts=_suggestion_class_counts(eligible_suggestions),
            selected_suggestion_counts=_suggestion_class_counts(suggestions),
            daily_suggestion_targets=daily_suggestion_targets,
        )
        if apply:
            previous = {c["card_id"]: c["column"] for c in existing}
            for card in result["cards_to_write"]:
                _internal_write(provider, card,
                                previous_column=previous.get(card["card_id"]))
                previous[card["card_id"]] = card.get("column") or "Suggested Jobs"
        result.pop("cards_to_write", None)
        result["operation"] = "publish_suggestions"
        result["backend"] = backend
        result["board_id"] = INTERNAL_BOARD_ID
        result["writes_performed"] = apply
        return result

    state = load_local_state(base, config)
    result = _publish_into_cards(
        state["cards"],
        suggestions,
        apply=apply,
        below_threshold=below_threshold,
        min_score_to_show=config.ranking.min_score_to_show,
        eligible_suggestions_seen=len(eligible_suggestions),
        daily_suggestion_limit=config.job_search.max_suggested_jobs_per_day,
        eligible_suggestion_counts=_suggestion_class_counts(eligible_suggestions),
        selected_suggestion_counts=_suggestion_class_counts(suggestions),
        daily_suggestion_targets=daily_suggestion_targets,
    )
    if apply:
        state["cards"] = result["cards"]
        for card in result["created_cards"]:
            _event(
                state,
                action="publish_suggestion",
                card_id=card["card_id"],
                from_column=None,
                to_column="Suggested Jobs",
            )
        for card in result["retired_below_threshold"]:
            _event(
                state,
                action="retire_below_threshold",
                card_id=card["card_id"],
                from_column="Suggested Jobs",
                to_column="Rejected / Skip",
            )
        for card in result["retired_duplicate_apply_url"]:
            _event(
                state,
                action="retire_duplicate_apply_url",
                card_id=card["card_id"],
                from_column="Suggested Jobs",
                to_column="Rejected / Skip",
            )
        save_local_state(base, state, config)
    result.pop("cards_to_write", None)
    result["operation"] = "publish_suggestions"
    result["backend"] = backend
    result["writes_performed"] = apply
    return result


def _publish_into_cards(
    cards: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    *,
    apply: bool,
    min_score_to_show: int,
    eligible_suggestions_seen: int,
    daily_suggestion_limit: int,
    eligible_suggestion_counts: dict[str, int],
    selected_suggestion_counts: dict[str, int],
    daily_suggestion_targets: dict[str, int],
    below_threshold: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    working = json.loads(json.dumps(cards))
    created_cards: list[dict[str, Any]] = []
    updated_cards: list[dict[str, Any]] = []
    retired_below_threshold: list[dict[str, Any]] = []
    retired_duplicate_apply_url: list[dict[str, Any]] = []
    skipped_existing_user_column: list[dict[str, Any]] = []
    cards_to_write: list[dict[str, Any]] = []
    for suggestion in suggestions:
        incoming = _new_card_from_suggestion(suggestion)
        job_key = incoming["fields"]["job_key"]
        apply_url = str(incoming["fields"].get("apply_url") or "")
        existing = [card for card in working if card.get("fields", {}).get("job_key") == job_key]
        duplicate_urls = [
            card
            for card in working
            if str(card.get("fields", {}).get("apply_url") or "") == apply_url
            and str(card.get("fields", {}).get("job_key") or "") != job_key
        ]
        if duplicate_urls and not existing:
            anchor = duplicate_urls[0]
            skipped_existing_user_column.append(
                {
                    "job_key": job_key,
                    "card_id": incoming.get("card_id"),
                    "column": "not_created",
                    "reason": "duplicate_apply_url",
                    "duplicate_of": anchor.get("card_id"),
                }
            )
            continue
        if not existing:
            created_cards.append(incoming)
            cards_to_write.append(incoming)
            if apply:
                working.append(incoming)
            continue
        for card in existing:
            if card.get("column") != "Suggested Jobs":
                skipped_existing_user_column.append(
                    {"job_key": job_key, "card_id": card.get("card_id"), "column": card.get("column")}
                )
                continue
            changed = _merge_card_fields(card, incoming["fields"])
            if changed:
                updated_cards.append({"card_id": card["card_id"], "job_key": job_key, "updated_fields": changed})
                cards_to_write.append(card)
    cards_by_url: dict[str, list[dict[str, Any]]] = {}
    for card in working:
        apply_url = str(card.get("fields", {}).get("apply_url") or "")
        if apply_url:
            cards_by_url.setdefault(apply_url, []).append(card)
    for apply_url, same_url_cards in cards_by_url.items():
        if len(same_url_cards) < 2:
            continue
        anchor = sorted(
            same_url_cards,
            key=lambda card: (
                0 if card.get("column") != "Suggested Jobs" else 1,
                str(card.get("created_at") or ""),
                str(card.get("card_id") or ""),
            ),
        )[0]
        for card in same_url_cards:
            if card.get("card_id") == anchor.get("card_id"):
                continue
            if card.get("column") != "Suggested Jobs":
                skipped_existing_user_column.append(
                    {
                        "job_key": card.get("fields", {}).get("job_key"),
                        "card_id": card.get("card_id"),
                        "column": card.get("column"),
                        "reason": "duplicate_apply_url_user_owned",
                        "duplicate_of": anchor.get("card_id"),
                    }
                )
                continue
            fields = card.setdefault("fields", {})
            retire_note = f"Retired as duplicate of {anchor.get('card_id')} with the same apply_url."
            changed = []
            if fields.get("next_action") != retire_note:
                fields["next_action"] = retire_note
                changed.append("next_action")
            card["column"] = "Rejected / Skip"
            changed.append("column")
            row = {
                "card_id": card["card_id"],
                "job_key": fields.get("job_key"),
                "duplicate_of": anchor.get("card_id"),
                "apply_url": apply_url,
                "updated_fields": sorted(set(changed)),
            }
            if row not in retired_duplicate_apply_url:
                retired_duplicate_apply_url.append(row)
                cards_to_write.append(card)
    below_threshold = below_threshold or {}
    for card in working:
        fields = card.get("fields", {})
        job_key = str(fields.get("job_key") or "")
        suggestion = below_threshold.get(job_key)
        auto_retired = (
            card.get("column") == "Rejected / Skip"
            and str(fields.get("next_action") or "").startswith(
                "Retired from Suggested Jobs after rescoring below"
            )
        )
        if not suggestion or (card.get("column") != "Suggested Jobs" and not auto_retired):
            continue
        incoming = fields_from_suggestion(suggestion)
        changed = _merge_card_fields(card, incoming)
        fields = card.setdefault("fields", {})
        retire_note = (
            f"Retired from Suggested Jobs after rescoring below the "
            f"{min_score_to_show} show threshold."
        )
        if fields.get("next_action") != retire_note:
            fields["next_action"] = retire_note
            changed.append("next_action")
        if card.get("column") != "Rejected / Skip":
            card["column"] = "Rejected / Skip"
            changed.append("column")
        retired_below_threshold.append(
            {
                "card_id": card["card_id"],
                "job_key": job_key,
                "fit_score": incoming["fit_score"],
                "updated_fields": sorted(set(changed)),
            }
        )
        cards_to_write.append(card)
    return {
        "status": "applied" if apply else "dry_run",
        "suggestions_seen": len(suggestions),
        "eligible_suggestions_seen": eligible_suggestions_seen,
        "daily_suggestion_limit": daily_suggestion_limit,
        "daily_suggestion_targets": daily_suggestion_targets,
        "eligible_suggestion_counts": eligible_suggestion_counts,
        "selected_suggestion_counts": selected_suggestion_counts,
        "would_create": [card["fields"]["job_key"] for card in created_cards],
        "would_update": updated_cards,
        "would_retire_below_threshold": retired_below_threshold,
        "would_retire_duplicate_apply_url": retired_duplicate_apply_url,
        "created_cards": created_cards if apply else [],
        "retired_below_threshold": retired_below_threshold if apply else [],
        "retired_duplicate_apply_url": retired_duplicate_apply_url if apply else [],
        "skipped_existing_user_column": skipped_existing_user_column,
        "cards": working if apply else cards,
        "cards_to_write": cards_to_write if apply else [],
    }


def process_selected(
    *,
    backend: BoardBackend = "internal",
    apply: bool = False,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
    executor: str = "auto",
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    if backend == "internal":
        provider = _internal_provider(env)
        existing = _internal_cards(provider)
        result = _process_selected_cards(
            existing,
            base,
            apply=apply,
            executor=executor,
            max_selected=config.job_search.max_selected_jobs_per_day,
        )
        if apply:
            previous = {c["card_id"]: c["column"] for c in existing}
            for card in result["cards_to_write"]:
                _internal_write(provider, card,
                                previous_column=previous.get(card["card_id"]))
                previous[card["card_id"]] = card.get("column") or "Suggested Jobs"
        result.pop("cards_to_write", None)
        result["operation"] = "process_selected"
        result["backend"] = backend
        result["board_id"] = INTERNAL_BOARD_ID
        result["writes_performed"] = apply
        return result

    state = load_local_state(base, config)
    result = _process_selected_cards(
        state["cards"],
        base,
        apply=apply,
        executor=executor,
        state=state,
        max_selected=config.job_search.max_selected_jobs_per_day,
    )
    if apply:
        state["cards"] = result["cards"]
        save_local_state(base, state, config)
    result.pop("cards_to_write", None)
    result["operation"] = "process_selected"
    result["backend"] = backend
    result["writes_performed"] = apply
    return result


def _target_column_for(automation: AutomationResult) -> str:
    if automation.value in {AutomationClass.MANUAL_REQUIRED, AutomationClass.PREPARE_ONLY}:
        return "Needs Geoff"
    return "Needs Geoff"


def _has_prepared_materials(card: dict[str, Any]) -> bool:
    fields = card.get("fields", {})
    return bool(fields.get("application_id") or fields.get("materials_path"))


def _is_processable_selection(card: dict[str, Any]) -> bool:
    column = card.get("column")
    if column == "Selected by Geoff":
        return True
    return column == "In Progress" and not _has_prepared_materials(card)


def _process_selected_cards(
    cards: list[dict[str, Any]],
    root: Path,
    *,
    apply: bool,
    executor: str,
    state: dict[str, Any] | None = None,
    max_selected: int | None = None,
) -> dict[str, Any]:
    working = json.loads(json.dumps(cards))
    all_selected = [card for card in working if _is_processable_selection(card)]
    selected = all_selected[:max_selected] if max_selected else all_selected
    deferred = all_selected[len(selected):]
    ignored = [
        {"card_id": card.get("card_id"), "column": card.get("column")}
        for card in working
        if not _is_processable_selection(card)
    ] + [
        {"card_id": card.get("card_id"), "column": card.get("column"), "reason": "daily_selected_limit"}
        for card in deferred
    ]
    plans: list[dict[str, Any]] = []
    cards_to_write: list[dict[str, Any]] = []
    for card in selected:
        job_key = card.get("fields", {}).get("job_key")
        suggestion = _load_suggestion(root, str(job_key))
        job = CanonicalJob.model_validate(suggestion["job"])
        fit = FitResult.model_validate(suggestion["fit"])
        automation = AutomationResult.model_validate(suggestion["automation"])
        selection = ResumeSelection.model_validate(suggestion["selection"])
        if selection.rejected_claims:
            raise RuntimeError("claim validation failed: " + "; ".join(selection.rejected_claims))
        target = _target_column_for(automation)
        planned_application_id = application_id_for(job, _today())
        plan = {
            "card_id": card["card_id"],
            "job_key": job.job_key,
            "company": job.company,
            "role_title": job.role_title,
            "resume_variant": selection.resume_variant,
            "automation_class": automation.value,
            "source_column": card.get("column"),
            "target_column": target,
            "planned_application_id": planned_application_id,
            "would_submit": False,
            "would_send_message": False,
        }
        plans.append(plan)
        if not apply:
            continue
        if state is not None:
            original = next(c for c in state["cards"] if c["card_id"] == card["card_id"])
            _set_column(state, original, "In Progress", "process_selected_start")
        card["column"] = "In Progress"
        cards_to_write.append(json.loads(json.dumps(card)))
        app_dir = create_prepared_application(job, fit, automation, selection, root=root, executor=executor)
        _, record = load_application(app_dir.name, root=root)
        card["fields"].update(
            {
                "application_id": record.application_id,
                "materials_path": str(app_dir),
                "next_action": record.followup.get("next_action"),
                "manual_reason": record.manual_reason,
                "auto_answered": "; ".join(record.auto_answered),
                "automation_class": record.automation_class.value,
                "resume_variant": record.resume_variant,
                "last_seen_at": _now(),
                # packet-review provenance so the cockpit can badge cards
                # without opening the packet
                "generation_mode": str(record.generation.get("mode") or "unknown"),
                "revision": record.revision,
                "review_state": record.review_state,
            }
        )
        if state is not None:
            original = next(c for c in state["cards"] if c["card_id"] == card["card_id"])
            original["fields"] = card["fields"]
            _set_column(state, original, target, "process_selected_route_needs_geoff")
        card["column"] = target
        cards_to_write.append(json.loads(json.dumps(card)))
        plan["application_id"] = record.application_id
        plan["materials_path"] = str(app_dir)
    return {
        "status": "applied" if apply else "dry_run",
        "selected_count": len(selected),
        "selected_limit": max_selected,
        "deferred_selected_count": len(deferred),
        "ignored_count": len(ignored),
        "ignored_cards": ignored,
        "plans": plans,
        "cards": working if apply else cards,
        "cards_to_write": cards_to_write,
    }


def mark_submitted_on_board(
    application_id: str,
    *,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    path = board_state_path(base, config)
    if not path.exists():
        return {"status": "not_configured", "updated_cards": [], "writes_performed": False}
    state = load_local_state(base, config)
    updated: list[str] = []
    for card in state["cards"]:
        if card.get("fields", {}).get("application_id") != application_id:
            continue
        _set_column(state, card, "Completed", "mark_submitted")
        card["fields"]["next_action"] = "Wait 5 business days, then follow up if no response."
        updated.append(card["card_id"])
    if updated:
        save_local_state(base, state, config)
    return {"status": "updated" if updated else "not_found", "updated_cards": updated, "writes_performed": bool(updated)}


def note_activity_on_board(
    application_id: str,
    note_type: str,
    *,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    path = board_state_path(base, config)
    if not path.exists():
        return {"status": "not_configured", "updated_cards": [], "writes_performed": False}
    if "recruiter" not in note_type and "interview" not in note_type:
        return {"status": "ignored_note_type", "updated_cards": [], "writes_performed": False}
    state = load_local_state(base, config)
    updated: list[str] = []
    for card in state["cards"]:
        if card.get("fields", {}).get("application_id") != application_id:
            continue
        _set_column(state, card, "Interviewing", "note_activity_interviewing")
        card["fields"]["next_action"] = "Review refreshed follow-up pack and reply draft."
        updated.append(card["card_id"])
    if updated:
        save_local_state(base, state, config)
    return {"status": "updated" if updated else "not_found", "updated_cards": updated, "writes_performed": bool(updated)}

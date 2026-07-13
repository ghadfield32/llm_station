from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx

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

BoardBackend = Literal["appflowy", "local", "internal"]

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

APPFLOWY_REQUIRED_ENV = (
    "APPFLOWY_BASE_URL",
    "APPFLOWY_WORKSPACE_ID",
    "APPFLOWY_EMAIL",
    "APPFLOWY_PASSWORD",
)
GROWTHOS_ROOT = repo_root() / "appflowy_kanban" / "growth-os"
DB_MAP_PATH = GROWTHOS_ROOT / "config" / "databases.json"
SCHEMA_PATH = GROWTHOS_ROOT / "config" / "schema.yaml"
STATE_SCHEMA = "command-center.job-search-board-state.v1"

APPFLOWY_FIELD_TYPE_IDS = {
    "text": 0,
    "longtext": 0,
    "number": 1,
    "date": 2,
    "select": 3,
    "url": 6,
}
SELECT_COLORS = ["Purple", "Orange", "Yellow", "Green", "Blue", "Pink", "Aqua"]

# AppFlowy's self-hosted REST API cannot set a board view's group-by field, edit
# select options, delete/reorder fields, or delete rows. A fresh grid always ships
# a groupable "Type" field that hijacks board grouping, so a REST-created board
# opens grouped by the empty "Type" column ("No Type") with no draggable stages.
# The database itself is correct (Status has all 8 stage options); only the board
# VIEW's grouping must be set once, in the AppFlowy client. These steps are the
# single manual action required to turn the board into a working Kanban.
GROUP_FIELD = "Status"
MANUAL_GROUPING_STEPS = [
    "Open the job_search_pipeline board and click the 'Board' tab (not 'Grid').",
    "Open the board view settings: the '...' (Settings) menu at the top-right of "
    "the board on desktop, or the settings icon on mobile.",
    "Choose 'Group by' and select 'Status'.",
    "The eight pipeline columns (Suggested Jobs ... Closed / Archived) appear "
    "immediately, with the current cards under 'Suggested Jobs'. You can now drag "
    "cards between stages.",
    "Optional cleanup (one time): delete the 3 blank starter rows AppFlowy created "
    "(right-click a card -> Delete), and hide the default 'Type' and 'Done' fields "
    "on cards via the card/field settings. These are AppFlowy defaults the REST API "
    "cannot remove; they do not affect the pipeline.",
]


def manual_grouping_guidance() -> dict[str, Any]:
    return {
        "why": (
            "AppFlowy's self-hosted REST API cannot set a board view's group field. "
            "The board opens grouped by AppFlowy's default empty 'Type' field, so it "
            "shows one 'No Type' column and nothing to drag between. This is a one-time "
            "client-side setup, not a data problem: the Status field already has all "
            "8 pipeline stages and every card is tagged."
        ),
        "group_by_field": GROUP_FIELD,
        "steps": list(MANUAL_GROUPING_STEPS),
    }


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
    values.update(_read_dotenv(GROWTHOS_ROOT / ".env"))
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


def appflowy_readiness(
    *,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
    require_database_mapping: bool = False,
) -> dict[str, Any]:
    config = cfg or load_config()
    values = _merged_env(env)
    missing_env = [name for name in APPFLOWY_REQUIRED_ENV if not values.get(name)]
    blockers = [f"missing_env:{name}" for name in missing_env]
    if not GROWTHOS_ROOT.exists():
        blockers.append(f"missing_growthos_root:{GROWTHOS_ROOT}")
    if not SCHEMA_PATH.exists():
        blockers.append(f"missing_growthos_schema:{SCHEMA_PATH}")
    if require_database_mapping:
        if not DB_MAP_PATH.exists():
            blockers.append(f"missing_database_map:{DB_MAP_PATH}")
        else:
            db_map = json.loads(DB_MAP_PATH.read_text(encoding="utf-8"))
            if config.job_search.board_name not in db_map:
                blockers.append(f"missing_database_mapping:{config.job_search.board_name}")
    return {
        "ready": not blockers,
        "backend": "appflowy",
        "board_name": config.job_search.board_name,
        "required_env": list(APPFLOWY_REQUIRED_ENV),
        "blockers": blockers,
        "setup_hint": (
            "Run `uv run cc appflowy-init`, set APPFLOWY_* values in .env or "
            "appflowy_kanban/growth-os/.env, start AppFlowy, then run "
            "`uv run cc job-search board-setup --apply`."
        ),
    }


def _appflowy_field_specs() -> list[tuple[str, Any]]:
    return [
        ("role_title", "text"),
        ("Status", {"type": "select", "options": BOARD_COLUMNS}),
        ("job_key", "text"),
        ("company", "text"),
        ("location", "text"),
        ("remote_type", {"type": "select", "options": ["remote", "hybrid", "onsite", "unknown"]}),
        ("source", "text"),
        ("portal", "text"),
        ("apply_url", "url"),
        ("salary_text", "text"),
        ("salary_min", "number"),
        ("salary_max", "number"),
        ("category", "text"),
        ("fit_score", "number"),
        (
            "automation_class",
            {"type": "select", "options": [member.value for member in AutomationClass]},
        ),
        ("manual_reason", "longtext"),
        ("resume_variant", "text"),
        ("why_apply", "longtext"),
        ("risks", "longtext"),
        ("deadline", "date"),
        ("last_seen_at", "date"),
        ("application_id", "text"),
        ("next_action", "longtext"),
        ("materials_path", "text"),
        (
            "company_tier",
            {"type": "select", "options": ["none", "sports_team", "sports_tech", "faang", "major_other"]},
        ),
        ("score_explanation", "longtext"),
        ("claude_review_url", "url"),
    ]


def _field_payload(name: str, spec: Any) -> dict[str, Any]:
    if isinstance(spec, str):
        ftype, options = spec, None
    else:
        ftype, options = spec["type"], spec.get("options")
    payload = {"name": name, "field_type": APPFLOWY_FIELD_TYPE_IDS[ftype], "type_option_data": None}
    if options:
        content = {
            "disable_color": False,
            "options": [
                {"id": secrets.token_hex(3), "name": str(option), "color": SELECT_COLORS[i % len(SELECT_COLORS)]}
                for i, option in enumerate(options)
            ],
        }
        payload["type_option_data"] = {"content": json.dumps(content)}
    return payload


def _appflowy_login(client: httpx.Client, env: dict[str, str]) -> dict[str, str]:
    base = env["APPFLOWY_BASE_URL"].rstrip("/")
    r = client.post(
        f"{base}/gotrue/token?grant_type=password",
        json={"email": env["APPFLOWY_EMAIL"], "password": env["APPFLOWY_PASSWORD"]},
    )
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("AppFlowy login returned no access_token")
    return {"Authorization": f"Bearer {token}"}


def _find_parent_space(client: httpx.Client, env: dict[str, str], headers: dict[str, str]) -> str:
    base = env["APPFLOWY_BASE_URL"].rstrip("/")
    ws = env["APPFLOWY_WORKSPACE_ID"]
    r = client.get(f"{base}/api/workspace/{ws}/folder", params={"depth": 1}, headers=headers)
    r.raise_for_status()
    root = r.json()["data"]
    for child in root.get("children", []):
        if child.get("is_space"):
            return child["view_id"]
    return root["view_id"]


def _fetch_field_mapping(
    client: httpx.Client,
    env: dict[str, str],
    db_id: str,
    headers: dict[str, str],
    title_col: str,
) -> tuple[str, dict[str, str]]:
    base = env["APPFLOWY_BASE_URL"].rstrip("/")
    ws = env["APPFLOWY_WORKSPACE_ID"]
    r = client.get(f"{base}/api/workspace/{ws}/database/{db_id}/fields", headers=headers)
    r.raise_for_status()
    live_fields = r.json()["data"]
    primary_id = next(field["id"] for field in live_fields if field.get("is_primary"))
    fields = {field["name"]: field["id"] for field in live_fields}
    fields[title_col] = primary_id
    return primary_id, fields


def _wire_value(value: Any) -> Any:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, str) and "T" in value and value.endswith("+00:00"):
        return value.split("T", 1)[0]
    return value


class AppFlowyJobSearchClient:
    def __init__(self, cfg: JobSearchConfig, env: dict[str, str]):
        self.cfg = cfg
        self.env = env
        self.base = env["APPFLOWY_BASE_URL"].rstrip("/")
        self.ws = env["APPFLOWY_WORKSPACE_ID"]
        self.client = httpx.Client(timeout=30)
        self.headers = _appflowy_login(self.client, env)
        self.db_map = json.loads(DB_MAP_PATH.read_text(encoding="utf-8"))
        self.entry = self.db_map[cfg.job_search.board_name]

    def close(self) -> None:
        self.client.close()

    def _field_ids(self) -> dict[str, str]:
        return self.entry["fields"]

    def list_fields(self) -> list[dict[str, Any]]:
        db_id = self.entry["database_id"]
        r = self.client.get(
            f"{self.base}/api/workspace/{self.ws}/database/{db_id}/fields",
            headers=self.headers,
        )
        r.raise_for_status()
        return r.json()["data"]

    def list_cards(self) -> list[dict[str, Any]]:
        db_id = self.entry["database_id"]
        rows = self.client.get(
            f"{self.base}/api/workspace/{self.ws}/database/{db_id}/row",
            headers=self.headers,
        )
        rows.raise_for_status()
        row_ids = [row["id"] for row in rows.json()["data"]]
        cards: list[dict[str, Any]] = []
        for i in range(0, len(row_ids), 40):
            detail = self.client.get(
                f"{self.base}/api/workspace/{self.ws}/database/{db_id}/row/detail",
                headers=self.headers,
                params={"ids": ",".join(row_ids[i:i + 40])},
            )
            detail.raise_for_status()
            for row in detail.json()["data"]:
                cells = row.get("cells", row)
                fields = {name: cells.get(name) for name in REQUIRED_CARD_FIELDS}
                fields["role_title"] = cells.get("role_title") or cells.get("Name")
                cards.append(
                    {
                        "card_id": row.get("id") or _card_id(str(fields.get("job_key") or "")),
                        "column": cells.get("Status") or "Suggested Jobs",
                        "fields": fields,
                    }
                )
        return cards

    def upsert_card(self, card: dict[str, Any]) -> None:
        fields = self._field_ids()
        cells = {"Status": card["column"], **card["fields"]}
        wire = {
            fields[name]: _wire_value(value)
            for name, value in cells.items()
            if name in fields and value is not None and value != ""
        }
        r = self.client.put(
            f"{self.base}/api/workspace/{self.ws}/database/{self.entry['database_id']}/row",
            headers=self.headers,
            json={"pre_hash": card["fields"]["job_key"], "cells": wire, "document": None},
        )
        r.raise_for_status()
        if r.json().get("code") != 0:
            raise RuntimeError(f"AppFlowy row upsert failed: {r.text[:200]}")


def _reconcile_appflowy_board(cfg: JobSearchConfig, env: dict[str, str]) -> dict[str, Any]:
    db_map = json.loads(DB_MAP_PATH.read_text(encoding="utf-8")) if DB_MAP_PATH.exists() else {}
    name = cfg.job_search.board_name
    schema_fields = _appflowy_field_specs()
    title_col = schema_fields[0][0]
    base = env["APPFLOWY_BASE_URL"].rstrip("/")
    ws = env["APPFLOWY_WORKSPACE_ID"]
    added_fields: list[str] = []
    with httpx.Client(timeout=30) as client:
        headers = _appflowy_login(client, env)
        parent = _find_parent_space(client, env, headers)
        if name in db_map:
            db_id = db_map[name]["database_id"]
            primary_id, live_fields = _fetch_field_mapping(client, env, db_id, headers, title_col)
            for field_name, spec in schema_fields[1:]:
                if field_name in live_fields:
                    continue
                fr = client.post(
                    f"{base}/api/workspace/{ws}/database/{db_id}/fields",
                    headers=headers,
                    json=_field_payload(field_name, spec),
                )
                fr.raise_for_status()
                if fr.json().get("code") != 0:
                    raise RuntimeError(f"{name}.{field_name}: {fr.text[:200]}")
                added_fields.append(field_name)
            primary_id, live_fields = _fetch_field_mapping(client, env, db_id, headers, title_col)
            db_map[name] = {
                "view_id": db_map[name]["view_id"],
                "database_id": db_id,
                "primary_field_id": primary_id,
                "title_column": title_col,
                "fields": live_fields,
            }
            DB_MAP_PATH.write_text(json.dumps(db_map, indent=2), encoding="utf-8")
            return {
                "status": "applied",
                "created": False,
                "added_fields": added_fields,
                "database_map_path": str(DB_MAP_PATH),
            }

        r = client.post(
            f"{base}/api/workspace/{ws}/page-view",
            headers=headers,
            json={"parent_view_id": parent, "layout": 1, "name": name},
        )
        r.raise_for_status()
        data = r.json()["data"]
        view_id, db_id = data["view_id"], data["database_id"]
        for field_name, spec in schema_fields[1:]:
            fr = client.post(
                f"{base}/api/workspace/{ws}/database/{db_id}/fields",
                headers=headers,
                json=_field_payload(field_name, spec),
            )
            fr.raise_for_status()
            if fr.json().get("code") != 0:
                raise RuntimeError(f"{name}.{field_name}: {fr.text[:200]}")
            added_fields.append(field_name)
        primary_id, live_fields = _fetch_field_mapping(client, env, db_id, headers, title_col)
        vr = client.post(
            f"{base}/api/workspace/{ws}/page-view/{view_id}/database-view",
            headers=headers,
            json={"parent_view_id": view_id, "layout": 2, "name": "Board", "database_id": db_id, "embedded": False},
        )
        vr.raise_for_status()
        db_map[name] = {
            "view_id": view_id,
            "database_id": db_id,
            "primary_field_id": primary_id,
            "title_column": title_col,
            "fields": live_fields,
        }
        DB_MAP_PATH.write_text(json.dumps(db_map, indent=2), encoding="utf-8")
    return {
        "status": "applied",
        "created": True,
        "added_fields": added_fields,
        "database_map_path": str(DB_MAP_PATH),
    }


def board_setup(
    *,
    backend: BoardBackend = "appflowy",
    apply: bool = False,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    schema = board_schema()
    if backend == "appflowy":
        readiness = appflowy_readiness(cfg=config, env=env, require_database_mapping=False)
        result = {
            "operation": "board_setup",
            "backend": backend,
            "board_name": config.job_search.board_name,
            "schema": schema,
            "writes_performed": False,
        }
        if not readiness["ready"]:
            result.update({"status": "blocked", "readiness": readiness})
            return result
        if not apply:
            result.update(
                {
                    "status": "dry_run",
                    "would_create_or_reconcile": config.job_search.board_name,
                    "next": "rerun with --apply to create/reconcile the AppFlowy board",
                    "manual_grouping": manual_grouping_guidance(),
                }
            )
            return result
        applied = _reconcile_appflowy_board(config, _merged_env(env))
        result.update(applied)
        result["writes_performed"] = True
        result["manual_grouping"] = manual_grouping_guidance()
        result["important"] = (
            "REQUIRED ONE-TIME STEP: set the board's 'Group by' to 'Status' in the "
            "AppFlowy client, or the board shows a single 'No Type' column with nothing "
            "to drag. See manual_grouping.steps."
        )
        return result

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
    backend: BoardBackend = "appflowy",
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    if backend == "appflowy":
        readiness = appflowy_readiness(cfg=config, env=env, require_database_mapping=True)
        if not readiness["ready"]:
            return {
                "operation": "board_snapshot",
                "backend": backend,
                "status": "blocked",
                "readiness": readiness,
                "writes_performed": False,
            }
        client = AppFlowyJobSearchClient(config, _merged_env(env))
        try:
            cards = client.list_cards()
        finally:
            client.close()
    elif backend == "internal":
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
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Health-check the live AppFlowy board and always surface the one-time
    group-by-Status step, which the REST API cannot perform for us."""
    config = cfg or load_config()
    readiness = appflowy_readiness(cfg=config, env=env, require_database_mapping=True)
    result: dict[str, Any] = {
        "operation": "board_doctor",
        "backend": "appflowy",
        "board_name": config.job_search.board_name,
        "manual_grouping": manual_grouping_guidance(),
        "writes_performed": False,
    }
    if not readiness["ready"]:
        result.update({"status": "blocked", "readiness": readiness})
        return result

    client = AppFlowyJobSearchClient(config, _merged_env(env))
    try:
        fields = client.list_fields()
        cards = client.list_cards()
    finally:
        client.close()

    status_field = next((f for f in fields if f.get("name") == GROUP_FIELD), None)
    status_options: list[str] = []
    if status_field:
        content = (status_field.get("type_option") or {}).get("content") or {}
        status_options = [o.get("name") for o in content.get("options", [])]
    expected = set(BOARD_COLUMNS)
    missing_options = sorted(expected - set(status_options))

    blank_rows = [
        card
        for card in cards
        if not (card.get("fields", {}).get("job_key") or "").strip()
    ]
    default_field_names = {f.get("name") for f in fields}
    junk_fields = sorted(default_field_names & {"Type", "Done"})

    checks = {
        "status_field_present": status_field is not None,
        "status_has_all_stage_options": not missing_options,
        "missing_status_options": missing_options,
        "real_cards": len(cards) - len(blank_rows),
        "blank_starter_rows": len(blank_rows),
        "leftover_default_fields": junk_fields,
    }
    healthy = checks["status_field_present"] and checks["status_has_all_stage_options"]
    result.update(
        {
            "status": "ok" if healthy else "needs_attention",
            "checks": checks,
            "next_step": (
                "The database is correctly set up. Set the board view's 'Group by' to "
                "'Status' in AppFlowy (see manual_grouping.steps) to get draggable columns."
            ),
        }
    )
    return result


def publish_suggestions(
    *,
    backend: BoardBackend = "appflowy",
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
    if backend == "appflowy":
        readiness = appflowy_readiness(cfg=config, env=env, require_database_mapping=True)
        if not readiness["ready"]:
            return {
                "operation": "publish_suggestions",
                "backend": backend,
                "status": "blocked",
                "readiness": readiness,
                "writes_performed": False,
            }
        client = AppFlowyJobSearchClient(config, _merged_env(env))
        try:
            cards = client.list_cards()
            result = _publish_into_cards(
                cards,
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
                for card in result["cards_to_write"]:
                    client.upsert_card(card)
        finally:
            client.close()
        result.pop("cards_to_write", None)
        return {
            "operation": "publish_suggestions",
            "backend": backend,
            **result,
            "writes_performed": apply,
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
    backend: BoardBackend = "appflowy",
    apply: bool = False,
    root: Path | None = None,
    cfg: JobSearchConfig | None = None,
    env: dict[str, str] | None = None,
    executor: str = "auto",
) -> dict[str, Any]:
    config = cfg or load_config()
    base = root or data_root(config)
    ensure_data_dirs(base)
    if backend == "appflowy":
        readiness = appflowy_readiness(cfg=config, env=env, require_database_mapping=True)
        if not readiness["ready"]:
            return {
                "operation": "process_selected",
                "backend": backend,
                "status": "blocked",
                "readiness": readiness,
                "writes_performed": False,
            }
        client = AppFlowyJobSearchClient(config, _merged_env(env))
        try:
            cards = client.list_cards()
            result = _process_selected_cards(
                cards,
                base,
                apply=apply,
                executor=executor,
                max_selected=config.job_search.max_selected_jobs_per_day,
            )
            if apply:
                for card in result["cards_to_write"]:
                    client.upsert_card(card)
        finally:
            client.close()
        result.pop("cards_to_write", None)
        return {
            "operation": "process_selected",
            "backend": backend,
            **result,
            "writes_performed": apply,
        }

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

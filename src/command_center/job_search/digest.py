from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from command_center.job_search.cache_io import read_json_file
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.retention import plan_retention

DIGEST_COLUMNS = ("Suggested Jobs", "Needs Geoff")


def _fit_score(value: Any) -> int | float:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    return int(parsed) if parsed.is_integer() else parsed


def build_digest_items(cards: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Purely project reviewable board cards into the proactive digest shape."""
    items: list[dict[str, Any]] = []
    for card in cards:
        column = str(card.get("column") or card.get("status") or "")
        if column not in DIGEST_COLUMNS:
            continue
        nested_fields = card.get("fields")
        fields = nested_fields if isinstance(nested_fields, Mapping) else card
        apply_url = str(fields.get("apply_url") or "")
        card_id = str(card.get("card_id") or "")
        review_href = apply_url
        if column == "Needs Geoff" and card_id:
            review_href = (
                "/api/domain/job_application/card/"
                f"{quote(card_id, safe='')}/packet"
            )
        items.append(
            {
                "company": str(fields.get("company") or ""),
                "role": str(fields.get("role_title") or fields.get("role") or ""),
                "fit_score": _fit_score(fields.get("fit_score")),
                "automation_class": str(fields.get("automation_class") or ""),
                "apply_url": apply_url,
                "review_href": review_href,
                "column": column,
            }
        )
    column_order = {column: index for index, column in enumerate(DIGEST_COLUMNS)}
    return sorted(
        items,
        key=lambda item: (
            column_order[item["column"]],
            -float(item["fit_score"]),
            item["company"].casefold(),
            item["role"].casefold(),
        ),
    )


def read_digest_items(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Read the board once, then hand projection to the pure item builder."""
    cfg = load_config()
    base = root or data_root(cfg)
    if root is None:
        from command_center.job_search.board import _internal_cards, _internal_provider

        cards = _internal_cards(_internal_provider())
    else:
        from command_center.job_search.board import load_local_state

        cards = load_local_state(base, cfg)["cards"]
    return build_digest_items(cards)


def _append_item(lines: list[str], item: Mapping[str, Any]) -> None:
    lines.append(
        f"- {item['company']} - {item['role']}: "
        f"{item['fit_score']}/100, {item['automation_class']}"
    )
    lines.append(f"  - Apply: {item['apply_url'] or '(not provided)'}")
    lines.append(f"  - Review: {item['review_href'] or '(not provided)'}")


def write_digest(*, root: Path | None = None) -> Path:
    cfg = load_config()
    base = root or data_root(cfg)
    ensure_data_dirs(base)
    suggestions = []
    for path in (base / "source_cache" / "suggestions").glob("*.json"):
        suggestions.append(read_json_file(path))
    items = read_digest_items(root=root)
    suggested = [item for item in items if item["column"] == "Suggested Jobs"]
    needs_geoff = [item for item in items if item["column"] == "Needs Geoff"]
    retention = plan_retention(root=base)
    lines = [
        "# Job Search Digest",
        "",
        "## Suggested Jobs",
        f"- Cached suggestions: {len(suggestions)}",
    ]
    for item in suggested[:5]:
        _append_item(lines, item)
    lines.extend(["", "## Needs Geoff"])
    if not needs_geoff:
        lines.append(
            "- Review prepared applications in "
            "`data/job_search/applications_active/*`."
        )
        lines.append("- Manual blockers are listed in each `application.yml`.")
    for item in needs_geoff[:5]:
        _append_item(lines, item)
    lines.extend(
        [
            "",
            "## Retention",
            f"- Records scanned: {len(retention['records'])}",
        ]
    )
    for row in retention["records"]:
        lines.append(f"- {row['application_id']}: {row['action']} until {row['retention_until']}")
    out = Path(cfg.job_search.digest_path)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out

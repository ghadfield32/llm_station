from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from command_center.job_search.schemas import JobSearchConfig, repo_root

CONFIG_PATH = Path("configs/job_search.yaml")
PROFILE_SETTINGS_REL = Path("profile/search_settings.yml")


def _resolve_data_root(root: Path, raw: dict[str, Any]) -> Path:
    data_root = raw.get("job_search", {}).get("data_root", "data/job_search")
    return root / Path(str(data_root)).expanduser()


def profile_settings_path(config: JobSearchConfig | None = None,
                          raw: dict[str, Any] | None = None) -> Path:
    root = repo_root()
    if config is not None:
        base = root / Path(config.job_search.data_root).expanduser()
    else:
        base = _resolve_data_root(root, raw or {})
    return base / PROFILE_SETTINGS_REL


def merge_profile_settings(base: dict[str, Any],
                           override: dict[str, Any] | None) -> dict[str, Any]:
    """Merge writable profile settings into the canonical job-search config.

    The override intentionally supports only operator-tunable search settings.
    It does not allow changing safety gates such as auto-submit behavior.
    """
    if not override:
        return deepcopy(base)

    merged = deepcopy(base)
    for section in ("job_search", "ranking"):
        values = override.get(section)
        if isinstance(values, dict):
            merged.setdefault(section, {}).update(values)

    patches = override.get("job_categories")
    if isinstance(patches, list):
        category_list = merged.setdefault("job_categories", [])
        categories = {
            str(category.get("id")): category
            for category in category_list
            if isinstance(category, dict) and category.get("id")
        }
        for patch in patches:
            if not isinstance(patch, dict) or not patch.get("id"):
                continue
            cat_id = str(patch["id"])
            category = categories.get(cat_id)
            if patch.get("remove"):
                # search types are adjustable both ways: a removed category
                # disappears from scoring and discovery until re-added
                if category is not None:
                    category_list.remove(category)
                    categories.pop(cat_id, None)
                continue
            if category is None:
                # NEW category added from the settings drawer; must carry the
                # full shape — JobSearchConfig validation rejects partials
                category = {"id": cat_id}
                category_list.append(category)
                categories[cat_id] = category
            for key in ("keywords", "role_focus", "resume_variant"):
                if key in patch:
                    category[key] = patch[key]

    return merged


def load_config(path: Path | None = None) -> JobSearchConfig:
    root = repo_root()
    cfg_path = root / (path or CONFIG_PATH)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base = JobSearchConfig.model_validate(data)
    settings_path = profile_settings_path(base)
    if not settings_path.is_file():
        return base
    override = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    return JobSearchConfig.model_validate(merge_profile_settings(data, override))


def data_root(config: JobSearchConfig | None = None) -> Path:
    cfg = config or load_config()
    return repo_root() / cfg.job_search.data_root


def ensure_data_dirs(root: Path) -> None:
    for rel in (
        "profile/inbox",
        "evidence",
        "applications_active",
        "applications_archive",
        "board",
        "skip_index",
        "source_cache/suggestions",
        "validation_runs",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)

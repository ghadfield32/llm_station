from __future__ import annotations

from pathlib import Path

import yaml

from command_center.job_search.schemas import JobSearchConfig, repo_root

CONFIG_PATH = Path("configs/job_search.yaml")


def load_config(path: Path | None = None) -> JobSearchConfig:
    root = repo_root()
    cfg_path = root / (path or CONFIG_PATH)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return JobSearchConfig.model_validate(data)


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

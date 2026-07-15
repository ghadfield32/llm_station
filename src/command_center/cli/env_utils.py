"""Small config/env readers shared by CLIs; values are never printed here."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def read_yaml(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def read_dotenv(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return values
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env(*paths: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        values.update(read_dotenv(path))
    values.update(os.environ)
    return values
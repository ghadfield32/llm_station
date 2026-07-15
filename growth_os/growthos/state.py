"""Dedupe state: remember which external_ids we've already pushed, so reruns
are idempotent and we never double-post a paper or repo."""
from __future__ import annotations
import json
from pathlib import Path


class SeenStore:
    def __init__(self, state_dir: str):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        return self.dir / f"seen_{kind}.json"

    def load(self, kind: str) -> set[str]:
        p = self._path(kind)
        if p.exists():
            try:
                return set(json.loads(p.read_text()))
            except Exception:
                return set()
        return set()

    def add(self, kind: str, ids: list[str]) -> None:
        seen = self.load(kind)
        seen.update(ids)
        self._path(kind).write_text(json.dumps(sorted(seen)))

    def filter_new(self, kind: str, items):
        seen = self.load(kind)
        return [i for i in items if i.external_id not in seen]

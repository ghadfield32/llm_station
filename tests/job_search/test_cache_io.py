from __future__ import annotations

import pytest

from command_center.job_search.cache_io import read_json_file, write_json_file_atomic
from command_center.job_search.config import ensure_data_dirs
from command_center.job_search.digest import write_digest


def test_atomic_json_write_creates_valid_cache_file(tmp_path):
    path = tmp_path / "source_cache" / "suggestions" / "example.json"

    write_json_file_atomic(path, {"job": {"job_key": "example"}, "fit": {"score": 90}})

    assert read_json_file(path)["fit"]["score"] == 90
    assert not list(path.parent.glob(".*.tmp"))


def test_digest_reports_corrupt_suggestion_cache_path(tmp_path):
    ensure_data_dirs(tmp_path)
    broken = tmp_path / "source_cache" / "suggestions" / "broken.json"
    broken.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="broken.json"):
        write_digest(root=tmp_path)

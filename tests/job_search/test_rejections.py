"""Rejection capture + the report that turns rejections into filter/scoring
suggestions."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from command_center.job_search.rejections import (
    load_rejections,
    record_rejection,
    rejection_report,
)
from command_center.job_search.schemas import JobSearchConfig

CONFIG = Path("configs/job_search.yaml")


def _cfg() -> JobSearchConfig:
    return JobSearchConfig.model_validate(
        yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def test_record_and_load_roundtrip(tmp_path):
    record_rejection(tmp_path, job_key="a", reason_code="salary",
                     company="X", note="too low")
    rows = load_rejections(tmp_path)
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "salary"
    assert rows[0]["note"] == "too low"


def test_unknown_reason_code_raises(tmp_path):
    with pytest.raises(ValueError):
        record_rejection(tmp_path, job_key="a", reason_code="banana")


def test_report_flags_uncaught_location_as_high_priority(tmp_path):
    # a remote job the filter would NOT hard-exclude, rejected for location =>
    # a filter gap the report should surface as high priority
    record_rejection(tmp_path, job_key="a", reason_code="location",
                     location="Remote", remote_type="remote")
    report = rejection_report(tmp_path, cfg=_cfg())
    assert report["total_rejections"] == 1
    high = [s for s in report["suggestions"]
            if s["area"] == "locations" and s["priority"] == "high"]
    assert high, report["suggestions"]


def test_report_marks_filter_working_when_mismatch_already_caught(tmp_path):
    # an onsite NY job the filter DOES hard-exclude: not a gap, so the locations
    # suggestion should be low priority ("filter is doing its job")
    record_rejection(tmp_path, job_key="b", reason_code="location",
                     location="New York, NY", remote_type="onsite")
    report = rejection_report(tmp_path, cfg=_cfg())
    loc = [s for s in report["suggestions"] if s["area"] == "locations"]
    assert loc and loc[0]["priority"] == "low"


def test_report_suggests_raising_show_bar_for_surfaced_low_fit(tmp_path):
    cfg = _cfg()
    record_rejection(tmp_path, job_key="c", reason_code="low_fit",
                     fit_score=cfg.ranking.min_score_to_show + 3)
    report = rejection_report(tmp_path, cfg=cfg)
    assert any(s["area"] == "ranking" for s in report["suggestions"])


def test_load_rejections_skips_corrupt_line(tmp_path):
    path = tmp_path / "rejections" / "rejections.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"reason_code": "salary"}\nnot json\n', encoding="utf-8")
    rows = load_rejections(tmp_path)
    assert len(rows) == 1

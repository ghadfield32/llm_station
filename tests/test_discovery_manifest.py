"""
The report manifest sidecar: deterministic output sha256, injected (not wall-clock) produced_at,
honest-null provenance, and the pipeline writing `<report>.manifest.json` on apply (only).
"""
from __future__ import annotations

import json

from command_center.improvement.discovery import (
    Finding, ObserverCharter, Pillar, ScanPipeline, build_manifest, write_manifest,
)
from command_center.improvement.discovery.sources import ScanOutcome, Scanner
from command_center.improvement.registry import ExperimentRegistry

NOW = "2026-06-13T06:00:00+00:00"


def _outcomes():
    f = Finding(pillar=Pillar.CODE_QUALITY, source="t", title="x", claim="c", evidence="e")
    return [ScanOutcome("code_health", Pillar.CODE_QUALITY, [f]),
            ScanOutcome("arxiv", Pillar.FULL_IDEA, [], error="ConnectionError: down")]


def test_manifest_is_deterministic_and_injected_timestamp():
    m1 = build_manifest(report_markdown="# R", produced_at=NOW, outcomes=_outcomes(),
                        n_findings=1, n_drafted=1, method="wsjf")
    m2 = build_manifest(report_markdown="# R", produced_at=NOW, outcomes=_outcomes(),
                        n_findings=1, n_drafted=1, method="wsjf")
    assert m1.output_sha256 == m2.output_sha256          # same content → same hash
    assert m1.input_sha256 == m2.input_sha256
    assert m1.produced_at == NOW                          # injected, not wall-clock
    # output hash actually tracks the content
    m3 = build_manifest(report_markdown="# DIFFERENT", produced_at=NOW, outcomes=_outcomes(),
                        n_findings=1, n_drafted=1, method="wsjf")
    assert m3.output_sha256 != m1.output_sha256


def test_manifest_records_sources_counts_and_provenance():
    m = build_manifest(report_markdown="# R", produced_at=NOW, outcomes=_outcomes(),
                       n_findings=1, n_drafted=1, method="wsjf")
    d = m.to_dict()
    assert d["counts"] == {"n_sources": 2, "n_failed": 1, "n_findings": 1, "n_drafted": 1}
    assert {s["name"] for s in d["sources"]} == {"code_health", "arxiv"}
    assert d["library_versions"]["python"]               # python version present
    assert "git_sha" in d                                # present (str or honest null)
    assert json.loads(json.dumps(d))["method"] == "wsjf"  # serializable


def test_write_manifest_sidecar_path(tmp_path):
    m = build_manifest(report_markdown="# R", produced_at=NOW, outcomes=_outcomes(),
                       n_findings=1, n_drafted=0, method="ice")
    report = tmp_path / "report.md"
    report.write_text("# R", encoding="utf-8")
    path = write_manifest(report, m)
    assert path.endswith("report.md.manifest.json")
    loaded = json.loads((tmp_path / "report.md.manifest.json").read_text(encoding="utf-8"))
    assert loaded["output_sha256"] == m.output_sha256


class _Scanner(Scanner):
    name = "code_health"
    pillar = Pillar.CODE_QUALITY

    def scan(self):
        return [Finding(pillar=Pillar.CODE_QUALITY, source="t", title="y",
                        claim="c", evidence="e")]


def test_pipeline_writes_manifest_on_apply_only(tmp_path):
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    charter = ObserverCharter(reg, report_path=tmp_path / "report.md")
    pipe = ScanPipeline(charter)
    # dry-run: no manifest
    dry = pipe.run([_Scanner()], date="2026-06-13", now_iso=NOW, apply=False)
    assert dry.manifest_path == ""
    assert not (tmp_path / "report.md.manifest.json").exists()
    # apply: manifest written next to the report, produced_at is the injected logical ts
    rep = pipe.run([_Scanner()], date="2026-06-13", now_iso=NOW, apply=True)
    assert rep.manifest_path.endswith("report.md.manifest.json")
    man = json.loads((tmp_path / "report.md.manifest.json").read_text(encoding="utf-8"))
    assert man["produced_at"] == NOW
    assert man["counts"]["n_drafted"] == len(rep.drafted_ids)

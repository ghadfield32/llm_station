"""
Triage + report + the end-to-end scan pipeline.

The load-bearing guarantees: a dry run writes NOTHING, apply drafts only `Proposed` cards,
a second run is idempotent (no duplicate cards), a human rejection is remembered and the
finding is suppressed (negative-result memory), failed sources are surfaced not hidden, and
the card cap holds surplus rather than silently dropping it.
"""
from __future__ import annotations

from command_center.improvement.discovery import (
    Finding, ObserverCharter, Pillar, ScanPipeline, Scanner, Triage, TriageDecision,
)
from command_center.improvement.discovery.sources import Scanner as _Scanner
from command_center.improvement.lifecycle import Actor, ExperimentStatus
from command_center.improvement.registry import ExperimentRegistry

NOW = "2026-06-13T08:00:00+00:00"


class StaticScanner(_Scanner):
    """A scanner that returns a fixed list of findings (for deterministic pipeline tests)."""

    def __init__(self, name, pillar, findings):
        self.name = name
        self.pillar = pillar
        self._findings = findings

    def scan(self):
        return list(self._findings)


class BoomScanner(_Scanner):
    name = "boom"
    pillar = Pillar.DATA_HANDLING

    def scan(self):
        raise ConnectionError("feed offline")


def _f(title, *, pillar=Pillar.CODE_QUALITY, confidence=0.8, **kw) -> Finding:
    return Finding(pillar=pillar, source="t", title=title, claim="c", evidence="e",
                   confidence=confidence, **kw)


def _reg(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))


def _pipeline(tmp_path, **kw):
    reg = _reg(tmp_path)
    charter = ObserverCharter(reg, report_path=tmp_path / "report.md")
    return ScanPipeline(charter, **kw), reg


# ------------------------------------------------------------------- triage units

def test_triage_noise_below_confidence(tmp_path):
    t = Triage(_reg(tmp_path), min_confidence=0.5)
    res = t.classify([_f("x", confidence=0.3)], now_iso=NOW)
    assert res[0].decision is TriageDecision.NOISE


def test_triage_within_batch_duplicate(tmp_path):
    f1, f2 = _f("same"), _f("same")
    res = Triage(_reg(tmp_path)).classify([f1, f2], now_iso=NOW)
    assert res[0].decision is TriageDecision.DRAFT
    assert res[1].decision is TriageDecision.DUPLICATE_BATCH


def test_triage_duplicate_open(tmp_path):
    reg = _reg(tmp_path)
    f = _f("already open")
    reg.register(f.to_experiment_definition())            # lands as Proposed
    res = Triage(reg).classify([f], now_iso=NOW)
    assert res[0].decision is TriageDecision.DUPLICATE_OPEN


def test_triage_negative_memory_after_rejection(tmp_path):
    reg = _reg(tmp_path)
    f = _f("bad idea")
    reg.register(f.to_experiment_definition())
    reg.set_status(f.experiment_id, ExperimentStatus.REJECTED, actor=Actor.HUMAN, note="no")
    res = Triage(reg).classify([f], now_iso=NOW)
    assert res[0].decision is TriageDecision.NEGATIVE_MEMORY


def test_triage_cooldown_for_soft_terminal(tmp_path):
    reg = _reg(tmp_path)
    f = _f("deferred one")
    reg.register(f.to_experiment_definition())
    reg.set_status(f.experiment_id, ExperimentStatus.DEFERRED, actor=Actor.HUMAN, note="later")
    res = Triage(reg, cooldown_hours=168).classify([f], now_iso=NOW)
    assert res[0].decision is TriageDecision.COOLDOWN


# ------------------------------------------------------------------- pipeline

def test_dry_run_writes_nothing_but_reports_everything(tmp_path):
    pipe, reg = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, [_f("improve A"), _f("improve B")])]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=False)
    assert rep.applied is False
    assert reg.list_experiments() == []                   # ZERO writes
    assert (tmp_path / "report.md").exists() is False     # no file written
    assert len(rep.would_draft_ids) == 2
    assert "DRY RUN" in rep.report_markdown
    assert "improve A" in rep.report_markdown


def test_apply_drafts_only_proposed_cards_and_writes_report(tmp_path):
    pipe, reg = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, [_f("improve A"), _f("improve B")])]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    rows = reg.list_experiments()
    assert len(rows) == 2
    assert all(r["status"] == ExperimentStatus.PROPOSED.value for r in rows)
    assert set(rep.drafted_ids) == {r["experiment_id"] for r in rows}
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Daily")


def test_second_apply_is_idempotent(tmp_path):
    pipe, reg = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, [_f("improve A")])]
    pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    rep2 = pipe.run(scanners, date="2026-06-14", now_iso=NOW, apply=True)
    assert reg.list_experiments() and len(reg.list_experiments()) == 1   # no duplicate
    assert rep2.drafted_ids == []                                        # nothing new drafted


def test_negative_memory_suppresses_and_is_reported(tmp_path):
    pipe, reg = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, [_f("rejected idea")])]
    pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    eid = reg.list_experiments()[0]["experiment_id"]
    reg.set_status(eid, ExperimentStatus.REJECTED, actor=Actor.HUMAN, note="declined")
    rep = pipe.run(scanners, date="2026-06-14", now_iso=NOW, apply=True)
    assert rep.suppressed_negative == 1
    assert rep.drafted_ids == []
    assert "negative-result memory" in rep.report_markdown
    assert "rejected idea" in rep.report_markdown


def test_failed_source_is_surfaced_in_report(tmp_path):
    pipe, _ = _pipeline(tmp_path)
    scanners = [BoomScanner(), StaticScanner("ok", Pillar.CODE_QUALITY, [_f("real one")])]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    assert rep.n_failed == 1
    assert "Failed sources" in rep.report_markdown
    assert "feed offline" in rep.report_markdown
    # the healthy source still produced its card
    assert len(rep.drafted_ids) == 1


def test_card_cap_holds_surplus_without_dropping(tmp_path):
    pipe, reg = _pipeline(tmp_path, max_cards=2)
    findings = [_f(f"idea {i}", impact=i / 10) for i in range(5)]
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, findings)]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    assert len(rep.drafted_ids) == 2
    assert rep.n_capped == 3
    assert "held by card cap" in rep.report_markdown.lower()
    assert len(reg.list_experiments()) == 2


def test_pipeline_report_keeps_human_wall_language(tmp_path):
    pipe, _ = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.AUTOMATION, [_f("auto", pillar=Pillar.AUTOMATION)])]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=True)
    md = rep.report_markdown
    assert "human" in md.lower() and "Proposed" in md
    assert "promoted, merged, or deployed" in md


def test_scanreport_to_dict_is_serializable(tmp_path):
    import json
    pipe, _ = _pipeline(tmp_path)
    scanners = [StaticScanner("s", Pillar.CODE_QUALITY, [_f("x")])]
    rep = pipe.run(scanners, date="2026-06-13", now_iso=NOW, apply=False)
    assert json.loads(json.dumps(rep.to_dict()))["applied"] is False


def test_scanner_protocol_export():
    # the public Scanner symbol is the ABC scanners implement
    assert Scanner is _Scanner

"""
Scanners: the deterministic offline code-health reader, the injected-fetch feed scanners,
the Ledger reliability reader, and the failure-is-first-class `run_scanners` contract.
"""
from __future__ import annotations

import textwrap

import pytest

from command_center.improvement.discovery import (
    CodeHealthScanner, CodeHealthThresholds, DependencyScanner, KanbanScanner,
    LedgerHealthScanner, ModelRegistryScanner, PapersScanner, Pillar, ScanOutcome,
    run_scanners, wsjf,
)
from command_center.improvement.discovery.sources import Scanner
from command_center.improvement.registry import ExperimentRegistry


# --------------------------------------------------------------------- code health

def _write_repo(root):
    pkg = root / "pkg"
    pkg.mkdir()
    # a function well over the statement threshold
    long_body = "\n".join(f"    x{i} = {i}" for i in range(40))
    (pkg / "long.py").write_text(f"def big():\n{long_body}\n    return x0\n", encoding="utf-8")
    # a swallowed exception (the banned pattern) + some debt markers
    (pkg / "swallow.py").write_text(textwrap.dedent("""
        def risky():
            try:
                do()
            except Exception:
                pass  # TODO fix this
        # FIXME later
        # HACK temporary
    """), encoding="utf-8")
    # an oversized module
    (pkg / "huge.py").write_text("x = 1\n" * 50, encoding="utf-8")


def test_code_health_finds_swallow_long_func_and_debt(tmp_path):
    _write_repo(tmp_path)
    t = CodeHealthThresholds(max_function_statements=20, max_module_lines=40,
                             min_debt_markers=3, min_swallowed_excepts=1)
    findings = CodeHealthScanner(tmp_path, thresholds=t).scan()
    titles = {f.title for f in findings}
    assert "remove swallowed exceptions" in titles
    assert "refactor over-long functions" in titles
    assert "split oversized modules" in titles
    assert "burn down TODO/FIXME debt" in titles
    swallow = next(f for f in findings if f.title == "remove swallowed exceptions")
    assert swallow.pillar is Pillar.CODE_QUALITY
    assert swallow.detail["count"] >= 1
    assert "swallow.py" in swallow.evidence


def test_code_health_is_deterministic_and_clean_tree_is_silent(tmp_path):
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    s = CodeHealthScanner(tmp_path, thresholds=CodeHealthThresholds())
    assert s.scan() == []                                   # nothing breaches
    # determinism: identical inputs -> identical experiment ids
    _write_repo(tmp_path)
    t = CodeHealthThresholds(max_function_statements=20, max_module_lines=40, min_debt_markers=3)
    ids1 = [f.experiment_id for f in CodeHealthScanner(tmp_path, thresholds=t).scan()]
    ids2 = [f.experiment_id for f in CodeHealthScanner(tmp_path, thresholds=t).scan()]
    assert ids1 == ids2


def test_code_health_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CodeHealthScanner(tmp_path / "nope").scan()


def test_code_health_runs_on_the_real_src_tree():
    # smoke: it parses the actual repo without error and returns a list of CODE_QUALITY/STRUCTURE
    findings = CodeHealthScanner("src").scan()
    assert isinstance(findings, list)
    for f in findings:
        assert f.source == "code_health"


# --------------------------------------------------------------------- feed scanners

def test_papers_scanner_filters_by_relevance():
    feed = [
        {"title": "A great method", "abstract": "lifts recall", "url": "u1", "relevance": 0.8,
         "applicability": 0.7},
        {"title": "Irrelevant", "abstract": "...", "url": "u2", "relevance": 0.2},
    ]
    findings = PapersScanner(lambda: feed, min_relevance=0.6).scan()
    assert len(findings) == 1
    assert findings[0].pillar is Pillar.FULL_IDEA
    assert findings[0].source == "arxiv"


def test_model_registry_only_proposes_when_candidate_beats_incumbent():
    feed = [
        {"model": "claude-x", "provider": "anthropic", "metric": "accuracy",
         "candidate": 0.9, "incumbent": 0.8, "direction": "increase"},
        {"model": "worse", "provider": "p", "metric": "accuracy",
         "candidate": 0.7, "incumbent": 0.8, "direction": "increase"},
        {"model": "cheaper", "provider": "p", "metric": "latency_ms",
         "candidate": 100, "incumbent": 200, "direction": "decrease"},
    ]
    findings = ModelRegistryScanner(lambda: feed).scan()
    titles = {f.title for f in findings}
    assert "evaluate claude-x on accuracy" in titles
    assert "evaluate cheaper on latency_ms" in titles
    assert all("worse" not in t for t in titles)


def test_dependency_scanner_critical_outranks_minor_under_wsjf():
    feed = [
        {"package": "lib-a", "current": "1.0", "latest": "1.1", "severity": "none"},
        {"package": "lib-b", "current": "2.0", "latest": "2.0", "severity": "none"},  # no change
        {"package": "lib-c", "current": "3.0", "latest": "3.1", "severity": "critical",
         "advisory": "RCE CVE-2026-9999"},
    ]
    findings = {f.detail["package"]: f for f in DependencyScanner(lambda: feed).scan()}
    assert "lib-b" not in findings                          # nothing to do
    assert set(findings) == {"lib-a", "lib-c"}
    assert wsjf(findings["lib-c"]) > wsjf(findings["lib-a"])  # critical CVE rises


def test_kanban_scanner_flags_aged_and_blocked():
    feed = [
        {"title": "fresh", "column": "Doing", "age_days": 2, "blocked": False},
        {"title": "stale", "column": "Doing", "age_days": 30, "blocked": False},
        {"title": "blocked-now", "column": "Doing", "age_days": 1, "blocked": True},
    ]
    titles = {f.title for f in KanbanScanner(lambda: feed, max_age_days=14).scan()}
    assert any("stale" in t for t in titles)
    assert any("blocked-now" in t for t in titles)
    assert not any("fresh" in t for t in titles)


def test_feed_scanner_propagates_fetch_failure():
    def boom():
        raise ConnectionError("arxiv down")
    with pytest.raises(ConnectionError):
        PapersScanner(boom).scan()


# --------------------------------------------------------------------- ledger health

def test_ledger_health_flags_a_cluster_of_failures(tmp_path):
    from command_center.improvement.discovery import Finding
    from command_center.improvement.lifecycle import Actor, ExperimentStatus
    from command_center.improvement.schema import TargetType
    reg = ExperimentRegistry(db_path=str(tmp_path / "l.db"))
    # two judge experiments that ended badly
    for i in range(2):
        d = Finding(pillar=Pillar.RULES_STANDARDS, source="x", title=f"judge tweak {i}",
                    claim="c", evidence="e",
                    suggested_target_type=TargetType.JUDGE).to_experiment_definition()
        reg.register(d)
        # a human stops each experiment early as Rejected (a permitted early-exit edge)
        reg.set_status(d.experiment_id, ExperimentStatus.REJECTED,
                       actor=Actor.HUMAN, note="not pursuing")
    findings = LedgerHealthScanner(reg, min_cluster=2).scan()
    assert len(findings) == 1
    assert findings[0].pillar is Pillar.RELIABILITY_OBSERVABILITY
    assert findings[0].detail["target_type"] == "judge"
    assert findings[0].detail["count"] == 2


# --------------------------------------------------------------------- run_scanners

class _Boom(Scanner):
    name = "boom"
    pillar = Pillar.AUTOMATION

    def scan(self):
        raise RuntimeError("kaboom")


class _Quiet(Scanner):
    name = "quiet"
    pillar = Pillar.AUTOMATION

    def scan(self):
        return []


def test_run_scanners_isolate_records_failure_not_swallows_it():
    outcomes = run_scanners([_Boom(), _Quiet()], isolate=True)
    by = {o.scanner: o for o in outcomes}
    assert by["boom"].ok is False and "kaboom" in by["boom"].error
    assert by["quiet"].ok is True
    # the failure is a *visible* outcome object, never a silently dropped source
    assert isinstance(by["boom"], ScanOutcome)


def test_run_scanners_strict_raises_loud():
    with pytest.raises(RuntimeError, match="kaboom"):
        run_scanners([_Boom()], isolate=False)

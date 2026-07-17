"""
The Airflow-free DAG glue: building one scanner per source spec, running a single source with
failure captured (not swallowed), the collect→draft→emit `finish` stage, and the XCom-safe
round-trip serialization the dynamic task mapping relies on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from command_center.improvement.discovery import (
    CodeHealthScanner, DependencyScanner, Finding, KanbanScanner, LedgerHealthScanner,
    ModelRegistryScanner, PapersScanner, Pillar, ScanOutcome, build_scanner, finish,
    offline_specs, registered_repository_specs, scan_one, scheduled_source_registry,
)
from command_center.improvement.discovery import dag_support
from command_center.improvement.discovery.dag_support import SOURCE_REGISTRY
from command_center.improvement.registry import ExperimentRegistry

NOW = "2026-06-13T08:00:00+00:00"


def _reg(tmp_path):
    return ExperimentRegistry(db_path=str(tmp_path / "ledger.db"))


# ------------------------------------------------------------------- build_scanner

@pytest.mark.parametrize("kind,cls", [
    ("code_health", CodeHealthScanner), ("ledger", LedgerHealthScanner),
    ("papers", PapersScanner), ("model_registry", ModelRegistryScanner),
    ("dependencies", DependencyScanner), ("kanban", KanbanScanner),
])
def test_build_scanner_for_each_kind(tmp_path, kind, cls):
    spec = {"name": kind, "kind": kind, "pillar": "code_quality", "config": {"root": "src"}}
    s = build_scanner(spec, _reg(tmp_path), fetch=lambda _s: [])
    assert isinstance(s, cls)


def test_build_scanner_feed_without_fetch_raises(tmp_path):
    spec = {"name": "arxiv", "kind": "papers", "pillar": "full_idea", "config": {}}
    with pytest.raises(ValueError, match="requires a fetch"):
        build_scanner(spec, _reg(tmp_path), fetch=None)


def test_build_scanner_unknown_kind_raises(tmp_path):
    spec = {"name": "weird", "kind": "weird", "pillar": "automation", "config": {}}
    with pytest.raises(ValueError, match="unknown source kind"):
        build_scanner(spec, _reg(tmp_path), fetch=lambda _s: [])


# ------------------------------------------------------------------- scan_one

def test_scan_one_offline_code_health(tmp_path):
    spec = {"name": "code_health", "kind": "code_health", "pillar": "code_quality",
            "config": {"root": "src"}}
    out = scan_one(spec, _reg(tmp_path))
    assert out["scanner"] == "code_health" and out["error"] == ""
    assert isinstance(out["findings"], list)


def test_scan_one_feed_with_records(tmp_path):
    spec = {"name": "litellm_registry", "kind": "model_registry",
            "pillar": "updated_metrics", "config": {}}
    records = [{"model": "m", "provider": "p", "metric": "acc",
                "candidate": 0.9, "incumbent": 0.8, "direction": "increase"}]
    out = scan_one(spec, _reg(tmp_path), fetch=lambda _s: records)
    assert out["error"] == "" and len(out["findings"]) == 1


def test_scan_one_attaches_repository_scope_and_reason(tmp_path):
    spec = {
        "name": "repo_scoped_models", "kind": "model_registry",
        "pillar": "updated_metrics", "config": {
            "repo_ids": ["example_repo"],
            "repository_reason": "Its model adapter can benefit from this candidate.",
        },
    }
    records = [{"model": "m", "provider": "p", "metric": "acc",
                "candidate": 0.9, "incumbent": 0.8, "direction": "increase"}]
    out = scan_one(spec, _reg(tmp_path), fetch=lambda _s: records)
    detail = out["findings"][0]["detail"]
    assert detail["repo_ids"] == ["example_repo"]
    assert detail["repository_reason"].startswith("Its model adapter")


def test_scan_one_captures_fetch_failure_not_swallowed(tmp_path):
    spec = {"name": "arxiv", "kind": "papers", "pillar": "full_idea", "config": {}}

    def boom(_s):
        raise ConnectionError("arxiv down")

    out = scan_one(spec, _reg(tmp_path), fetch=boom)
    assert out["findings"] == []
    assert "arxiv down" in out["error"]            # captured + reportable, not lost


# ------------------------------------------------------------------- finish

def _outcome(title):
    f = Finding(pillar=Pillar.CODE_QUALITY, source="t", title=title, claim="c", evidence="e")
    return ScanOutcome("code_health", Pillar.CODE_QUALITY, [f]).to_dict()


def test_finish_apply_drafts_proposed_cards_and_report(tmp_path):
    reg = _reg(tmp_path)
    report_path = tmp_path / "report.md"
    res = finish([_outcome("A"), _outcome("B")], reg, date="2026-06-13", now_iso=NOW,
                 apply=True, report_path=str(report_path))
    assert res["applied"] is True and len(res["drafted"]) == 2
    rows = reg.list_experiments()
    assert all(r["status"] == "Proposed" for r in rows)
    assert report_path.read_text(encoding="utf-8").startswith("# Daily")


def test_finish_dry_run_writes_nothing(tmp_path):
    reg = _reg(tmp_path)
    report_path = tmp_path / "report.md"
    res = finish([_outcome("A")], reg, date="2026-06-13", now_iso=NOW, apply=False,
                 report_path=str(report_path))
    assert res["applied"] is False
    assert reg.list_experiments() == []
    assert report_path.exists() is False


def test_finish_drafts_kanban_cards_with_injected_drafter(tmp_path):
    reg = _reg(tmp_path)
    calls = []

    def fake_card(**kw):
        calls.append(kw)
        return "drafted 1 card(s) in Backlog"

    res = finish([_outcome("A"), _outcome("B")], reg, date="2026-06-13", now_iso=NOW, apply=True,
                 draft_kanban=True, kanban_top=1, card_drafter=fake_card,
                 report_path=str(tmp_path / "r.md"))
    assert len(calls) == 1                              # kanban_top=1
    assert calls[0]["section"] == "Command Center" and calls[0]["risk"] in {"L0", "L1", "L2"}
    assert len(res["kanban_cards"]) == 1               # surfaced in the result


def test_finish_no_kanban_by_default(tmp_path):
    res = finish([_outcome("A")], _reg(tmp_path), date="2026-06-13", now_iso=NOW, apply=True,
                 report_path=str(tmp_path / "r.md"))
    assert "kanban_cards" not in res                   # off unless explicitly enabled


def test_finish_dry_run_never_drafts_kanban(tmp_path):
    calls = []
    res = finish([_outcome("A")], _reg(tmp_path), date="2026-06-13", now_iso=NOW, apply=False,
                 draft_kanban=True, card_drafter=lambda **kw: calls.append(kw),
                 report_path=str(tmp_path / "r.md"))
    assert calls == [] and "kanban_cards" not in res   # dry-run draws no cards


def test_finish_surfaces_failed_source(tmp_path):
    reg = _reg(tmp_path)
    failed = ScanOutcome("arxiv", Pillar.FULL_IDEA, [], error="ConnectionError: down").to_dict()
    res = finish([failed, _outcome("A")], reg, date="2026-06-13", now_iso=NOW, apply=True,
                 report_path=str(tmp_path / "r.md"))
    assert res["n_failed"] == 1 and "arxiv" in res["failed_sources"]


# ------------------------------------------------------------------- serialization

def test_finding_round_trips_through_dict():
    f = Finding(pillar=Pillar.UPDATED_METRICS, source="litellm", title="try model",
                claim="c", evidence="e", impact=0.7, effort=2.0, detail={"n_sources": 2})
    g = Finding.from_dict(f.to_dict())
    assert g.pillar is f.pillar
    assert g.suggested_target_type is f.suggested_target_type
    assert g.experiment_id == f.experiment_id
    assert g.impact == f.impact and g.detail == f.detail


def test_scanoutcome_round_trips_through_dict():
    f = Finding(pillar=Pillar.AUTOMATION, source="kanban", title="x", claim="c", evidence="e")
    o = ScanOutcome("kanban", Pillar.AUTOMATION, [f], error="")
    o2 = ScanOutcome.from_dict(o.to_dict())
    assert o2.scanner == "kanban" and o2.pillar is Pillar.AUTOMATION
    assert o2.findings[0].experiment_id == f.experiment_id


# ------------------------------------------------------------------- registry shape

def test_source_registry_spans_pillars_and_offline_subset():
    pillars = {s["pillar"] for s in SOURCE_REGISTRY}
    # the registry touches several distinct pillars (not just one)
    assert len(pillars) >= 4
    offline = {s["name"] for s in offline_specs()}
    assert offline == {"code_health", "ledger"}      # the two network-free sources


def test_scheduled_registry_expands_every_registered_repository(monkeypatch, tmp_path):
    monkeypatch.delenv("BETTS_BASKETBALL_LOCAL_PATH", raising=False)
    specs = registered_repository_specs(
        "configs/autonomy.yaml", self_root=tmp_path / "llm_station")
    by_name = {spec["name"]: spec for spec in specs}
    assert set(by_name) == {"code_health_llm_station", "code_health_betts_basketball"}
    assert by_name["code_health_llm_station"]["config"]["root"] == str(
        tmp_path / "llm_station")
    betts = by_name["code_health_betts_basketball"]["config"]
    assert Path(betts["root"]).parts[-2:] == (
        "__missing_registered_repo_path__", "betts_basketball")
    assert betts["repo_ids"] == ["betts_basketball"]
    assert "declared capabilities" in betts["repository_reason"]


def test_scheduled_registry_replaces_single_static_code_scan(monkeypatch, tmp_path):
    monkeypatch.setenv("SELF_IMPROVEMENT_REPO_CONFIG", "configs/autonomy.yaml")
    monkeypatch.setenv("SELF_IMPROVEMENT_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("BETTS_BASKETBALL_LOCAL_PATH", raising=False)
    specs = scheduled_source_registry()
    code_specs = [spec for spec in specs if spec["kind"] == "code_health"]
    assert {spec["config"]["repo_ids"][0] for spec in code_specs} == {
        "llm_station", "betts_basketball"}
    assert all(spec["name"] != "code_health" for spec in code_specs)


def test_codesota_source_registered_and_runs_through_scan_one(tmp_path):
    """The frontier-watch CodeSOTA source is a registered model_registry feed, and its
    adapter-shaped records flow through the DAG's single-source path to findings."""
    spec = next(s for s in SOURCE_REGISTRY if s["name"] == "codesota")
    assert spec["kind"] == "model_registry" and spec["pillar"] == "updated_metrics"
    # records in the shape discovery.codesota.fetch_codesota_records() produces
    records = [{"model": "Claude Mythos Preview", "provider": "Anthropic",
                "metric": "swe-bench-verified-agentic_resolve_rate",
                "candidate": 93.9, "incumbent": 80.9, "direction": "increase",
                "source_name": "codesota"}]
    out = scan_one(spec, _reg(tmp_path), fetch=lambda _s: records)
    assert out["error"] == "" and len(out["findings"]) == 1


# ------------------------------------------------------------------- fetch_records routing

def test_fetch_records_live_source_bypasses_the_variable(monkeypatch):
    """A LIVE_FETCHERS source (codesota) pulls fresh at scan time and must NEVER read a
    Variable — there is no `improvement_feed_codesota` to set."""
    variable_calls: list[str] = []

    def variable_get(key: str) -> str:
        variable_calls.append(key)            # records every Variable lookup
        return "[]"

    monkeypatch.setitem(dag_support.LIVE_FETCHERS, "codesota",
                        lambda: [{"model": "live", "metric": "m",
                                  "candidate": 2, "incumbent": 1}])
    records = dag_support.fetch_records({"name": "codesota"}, variable_get)
    assert records == [{"model": "live", "metric": "m", "candidate": 2, "incumbent": 1}]
    assert variable_calls == []               # the Variable path was never touched


def test_kanban_source_is_live_and_never_uses_a_stale_airflow_variable(monkeypatch):
    variable_calls: list[str] = []
    monkeypatch.setitem(dag_support.LIVE_FETCHERS, "kanban_cycle_time",
                        lambda: [{"board_id": "b", "title": "x"}])
    records = dag_support.fetch_records(
        {"name": "kanban_cycle_time"},
        lambda key: variable_calls.append(key) or "[]",
    )
    assert records == [{"board_id": "b", "title": "x"}]
    assert variable_calls == []


def test_fetch_records_non_live_source_reads_its_variable():
    """Every non-live source still reads its pre-ingested `improvement_feed_<name>` Variable."""
    seen: dict[str, str] = {"improvement_feed_arxiv": '[{"title": "x", "relevance": 0.9}]'}
    records = dag_support.fetch_records({"name": "arxiv"}, lambda key: seen[key])
    assert records == [{"title": "x", "relevance": 0.9}]


def test_fetch_records_live_fetch_failure_is_not_swallowed(monkeypatch):
    """A live fetcher that raises propagates — the isolate guard turns it into a visible
    failed source, never a silent empty feed."""
    def boom() -> list[dict]:
        raise ConnectionError("codesota down")

    monkeypatch.setitem(dag_support.LIVE_FETCHERS, "codesota", boom)
    with pytest.raises(ConnectionError, match="codesota down"):
        dag_support.fetch_records({"name": "codesota"}, lambda key: "[]")

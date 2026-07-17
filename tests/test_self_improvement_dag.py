"""
Structural validation of the Airflow DAG WITHOUT importing Airflow (it isn't a dependency of
this package). We parse the file with `ast` and assert the contract the addendum requires:
TaskFlow `@dag`/`@task`, dynamic task mapping (`.expand`), a DatasetOrTimeSchedule (daily +
on-demand), the five pipeline stages, the "set it loose" trigger asset, and — most importantly —
that the DAG imports NO promotion/merge/deploy capability (observer-only is structural).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

DAG_PATH = Path(__file__).resolve().parents[1] / "dags" / "self_improvement_daily.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(DAG_PATH.read_text(encoding="utf-8"), filename=str(DAG_PATH))


@pytest.fixture(scope="module")
def src() -> str:
    return DAG_PATH.read_text(encoding="utf-8")


def test_dag_file_is_valid_python(tree):
    assert isinstance(tree, ast.Module)


def _decorator_names(node: ast.AST) -> set[str]:
    names = set()
    for d in getattr(node, "decorator_list", []):
        if isinstance(d, ast.Name):
            names.add(d.id)
        elif isinstance(d, ast.Call):
            f = d.func
            names.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
        elif isinstance(d, ast.Attribute):
            names.add(d.attr)
    return names


def test_has_taskflow_dag_and_task_decorators(tree):
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    decos = set().union(*(_decorator_names(f) for f in funcs)) if funcs else set()
    assert "dag" in decos, "no @dag decorated function (TaskFlow API)"
    assert "task" in decos, "no @task decorated function"


def test_uses_dynamic_task_mapping_expand(tree):
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert any(c.func.attr == "expand" for c in calls), "dynamic task mapping (.expand) not used"


def test_schedule_is_dataset_or_time(tree, src):
    assert "DatasetOrTimeSchedule" in src
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert any(c.func.id == "DatasetOrTimeSchedule" for c in calls), \
        "schedule must be a DatasetOrTimeSchedule (daily cron + on-demand asset)"
    assert any(c.func.id == "CronTriggerTimetable" for c in calls)


def test_declares_the_five_pipeline_stages(tree):
    stages = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "STAGES" for t in node.targets):
            stages = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    assert stages == ["scan", "classify_and_dedup", "score_and_rank",
                      "draft_proposals", "emit_report_and_cards"]


def test_set_it_loose_trigger_asset_present(src):
    # the touchpoint signal any of Kanban/Discord/CLI can fire
    assert "scan-request" in src
    assert "Dataset(" in src


def test_observer_only_no_promotion_or_merge_imports(tree, src):
    # the DAG must not import any promote/merge/deploy capability
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
    blob = " ".join(imported).lower()
    for forbidden in ("promotioncontroller", "promotion", "set_status", "merge", "deploy"):
        assert forbidden not in blob, f"observer DAG must not import {forbidden!r}"
    # it routes ALL effects through the tested, charter-bound dag_support glue
    assert "dag_support" in src


def test_observer_only_banner_and_human_wall_documented(src):
    low = src.lower()
    assert "observer-only" in low
    assert "human-only" in low and "promotion" in low
    assert "no write/promote/merge/deploy credentials" in low


def test_idempotency_guards_present(src):
    assert "max_active_runs=1" in src           # no overlapping scans
    assert "catchup=False" in src               # no backfill storms


def test_kanban_drafting_is_wired_and_optional(src):
    # the wired first-party board receives drafts by default; report-only is an explicit opt-out
    assert "SELF_IMPROVEMENT_KANBAN" in src
    assert "draft_kanban=KANBAN" in src
    assert '"true"' in src


def test_sources_expand_from_the_validated_repository_registry(src):
    assert "dag_support.scheduled_source_registry()" in src
    assert "SOURCE_REGISTRY" not in src

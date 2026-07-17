"""Backup-gated DAGs write only to the canonical protected host stores."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_airflow_outputs_are_canonical_and_writable_backup_sources():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    airflow = compose["services"]["airflow"]
    environment = {
        key: value
        for row in airflow["environment"]
        for key, value in [row.split("=", 1)]
    }
    assert environment["KANBAN_BOARD_STORE"] == "/snapshot/boards"
    assert environment["KANBAN_EVENT_LOG"] == "/snapshot/kanban-events.jsonl"
    assert environment["SELF_IMPROVEMENT_REPORT_PATH"] == (
        "/snapshot/self-improvement-report.md")
    assert environment["SELF_IMPROVEMENT_REPO_CONFIG"] == (
        "/opt/airflow/repo/configs/autonomy.yaml")
    assert environment["SELF_IMPROVEMENT_REPO_ROOT"] == "/opt/airflow/repo"
    assert environment["BETTS_BASKETBALL_LOCAL_PATH"] == "/backup-sources/betts"
    generated = next(volume for volume in airflow["volumes"]
                     if volume.startswith("./generated:/snapshot"))
    assert not generated.endswith(":ro")


def test_dag_backup_xcoms_are_minimal_receipts():
    for name in ("job_search_daily.py", "self_improvement_daily.py"):
        source = (ROOT / "dags" / name).read_text(encoding="utf-8")
        assert '"snapshot_id", "source_set_watermark"' in source
        assert "return create_default_snapshot()" not in source
        assert '"sources"' not in source[source.index("def verified_runtime_backup"):][:700]

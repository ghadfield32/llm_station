"""Immutable runtime snapshot, verification, and staging-restore contracts."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import command_center.runtime_backup as runtime_backup
from command_center.runtime_backup import (
    BackupError,
    BackupSource,
    create_snapshot,
    default_sources,
    restore_to_empty,
    verify_snapshot,
    verify_snapshot_authorities,
)


def _fixture_sources(tmp_path):
    boards = tmp_path / "boards"
    (boards / "tasks").mkdir(parents=True)
    (boards / "tasks" / "one.json").write_text('{"title":"Keep me"}\n')
    events = tmp_path / "events.jsonl"
    events.write_text('{"event_id":"E-1"}\n')
    config = tmp_path / "boards.yaml"
    config.write_text("schema_version: test.v1\nboards: []\n")
    db_path = tmp_path / "ledger.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE work_items (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO work_items VALUES ('W-1', 'Keep me')")
    return [
        BackupSource("ledger", db_path, "sqlite"),
        BackupSource("boards", boards, "tree"),
        BackupSource("kanban_events", events, "file"),
        BackupSource("kanban_config", config, "file", sensitive=False),
    ]


def test_create_verify_and_restore_to_empty_staging(tmp_path):
    root = tmp_path / "backups"
    manifest = create_snapshot(
        root, _fixture_sources(tmp_path),
        now=datetime(2026, 7, 16, 4, tzinfo=timezone.utc),
    )
    snapshot = root / manifest["snapshot_id"]

    assert manifest["retention"] == "forever-no-automatic-delete"
    assert verify_snapshot(snapshot)["source_set_watermark"] == manifest["source_set_watermark"]
    restored = tmp_path / "restore"
    restore_to_empty(snapshot, restored)
    assert (restored / "data/boards/tasks/one.json").is_file()
    with sqlite3.connect(restored / "data/ledger.sqlite3") as db:
        assert db.execute("SELECT title FROM work_items").fetchone() == ("Keep me",)


def test_same_exact_watermark_and_timestamp_reconciles_without_overwrite(tmp_path):
    root = tmp_path / "backups"
    sources = _fixture_sources(tmp_path)
    now = datetime(2026, 7, 16, 4, tzinfo=timezone.utc)
    first = create_snapshot(root, sources, now=now)
    before = (root / first["snapshot_id"] / "manifest.json").read_bytes()
    second = create_snapshot(root, sources, now=now)
    assert second["snapshot_id"] == first["snapshot_id"]
    assert (root / first["snapshot_id"] / "manifest.json").read_bytes() == before


def test_same_exact_watermark_reuses_snapshot_across_later_gate_time(tmp_path):
    root = tmp_path / "backups"
    sources = _fixture_sources(tmp_path)
    first = create_snapshot(
        root, sources, now=datetime(2026, 7, 16, 4, tzinfo=timezone.utc))
    second = create_snapshot(
        root, sources, now=datetime(2026, 7, 17, 4, tzinfo=timezone.utc))
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["reused_exact_watermark"] is True
    assert second["gate_checked_at"].startswith("2026-07-17")
    assert len([path for path in root.iterdir() if not path.name.startswith(".")]) == 1


def test_changed_source_creates_new_content_addressed_snapshot(tmp_path):
    root = tmp_path / "backups"
    sources = _fixture_sources(tmp_path)
    first = create_snapshot(root, sources)
    (tmp_path / "events.jsonl").write_text('{"event_id":"E-1"}\n{"event_id":"E-2"}\n')
    second = create_snapshot(root, sources)
    assert first["source_set_watermark"] != second["source_set_watermark"]
    assert first["snapshot_id"] != second["snapshot_id"]
    assert len([path for path in root.iterdir() if not path.name.startswith(".")]) == 2


def test_mismatched_receipts_are_prefiltered_before_full_verification(
    tmp_path, monkeypatch,
):
    root = tmp_path / "backups"
    sources = _fixture_sources(tmp_path)
    first = create_snapshot(root, sources)
    (tmp_path / "events.jsonl").write_text(
        '{"event_id":"E-1"}\n{"event_id":"E-2"}\n')

    verified_paths = []
    original_verify = runtime_backup.verify_snapshot

    def tracked_verify(path):
        verified_paths.append(path)
        return original_verify(path)

    monkeypatch.setattr(runtime_backup, "verify_snapshot", tracked_verify)
    second = create_snapshot(root, sources)

    assert root / first["snapshot_id"] not in verified_paths
    assert verified_paths == [root / second["snapshot_id"]]


def test_missing_required_source_fails_closed(tmp_path):
    with pytest.raises(BackupError, match="required backup source is missing"):
        create_snapshot(
            tmp_path / "backups",
            [BackupSource("missing", tmp_path / "missing.json", "file")],
        )


def test_optional_missing_source_is_recorded(tmp_path):
    sources = _fixture_sources(tmp_path)
    sources.append(BackupSource("optional", tmp_path / "none", "tree", required=False))
    manifest = create_snapshot(tmp_path / "backups", sources)
    row = next(source for source in manifest["sources"] if source["name"] == "optional")
    assert row == {"name": "optional", "present": False, "required": False}


def test_tamper_is_detected_and_restore_refuses_nonempty_target(tmp_path):
    root = tmp_path / "backups"
    sources = _fixture_sources(tmp_path)
    manifest = create_snapshot(root, sources)
    (tmp_path / "events.jsonl").write_text(
        '{"event_id":"E-1"}\n{"event_id":"E-2"}\n')
    clean = create_snapshot(root, sources)
    clean_snapshot = root / clean["snapshot_id"]
    snapshot = root / manifest["snapshot_id"]
    (snapshot / "data/boards/tasks/one.json").write_text("tampered")
    with pytest.raises(BackupError, match="hash mismatch"):
        verify_snapshot(snapshot)

    target = tmp_path / "restore"
    target.mkdir()
    (target / "existing").write_text("never overwrite")
    with pytest.raises(BackupError, match="empty directory"):
        restore_to_empty(clean_snapshot, target)


def test_symlink_and_backup_root_recursion_are_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    link = source / "unsafe"
    try:
        link.symlink_to(tmp_path / "elsewhere")
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(BackupError, match="symlink"):
        create_snapshot(
            tmp_path / "backups", [BackupSource("source", source, "tree")]
        )
    with pytest.raises(BackupError, match="recursion"):
        create_snapshot(
            tmp_path / "backups", [BackupSource("root", tmp_path / "backups", "tree")]
        )


def test_invalid_jsonl_fails_semantic_validation(tmp_path):
    sources = _fixture_sources(tmp_path)
    (tmp_path / "events.jsonl").write_text("not-json\n")
    with pytest.raises(BackupError, match="invalid kanban_events JSONL"):
        create_snapshot(tmp_path / "backups", sources)


def test_manifest_is_last_and_no_staging_survives_success(tmp_path):
    root = tmp_path / "backups"
    manifest = create_snapshot(root, _fixture_sources(tmp_path))
    snapshot = root / manifest["snapshot_id"]
    parsed = json.loads((snapshot / "manifest.json").read_text())
    assert parsed["snapshot_id"] == manifest["snapshot_id"]
    assert not list(root.glob(".staging-*"))


def test_operational_status_and_cache_are_excluded_from_canonical_tree(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "canonical.json").write_text('{"keep": true}')
    (state / "watcher_status.json").write_text('{"changes_each_cycle": true}')
    (state / "source_cache").mkdir()
    (state / "source_cache" / "large.tmpdata").write_text("ignore")
    manifest = create_snapshot(
        tmp_path / "backups", [BackupSource("growth_state", state, "tree")])
    files = manifest["sources"][0]["files"]
    assert [row["path"] for row in files] == ["canonical.json"]


def test_default_backup_refuses_to_guess_a_possibly_stale_host_ledger(monkeypatch):
    monkeypatch.delenv("KANBAN_BACKUP_LEDGER_DB", raising=False)
    with pytest.raises(BackupError, match="KANBAN_BACKUP_LEDGER_DB is required"):
        default_sources()


def test_default_backup_includes_authoritative_research_repo_registry(
    monkeypatch, tmp_path,
):
    ledger = tmp_path / "ledger.db"
    autonomy = tmp_path / "autonomy.yaml"
    autonomy.write_text(
        "schema_version: command-center.autonomy.v1\n", encoding="utf-8")
    monkeypatch.setenv("KANBAN_BACKUP_LEDGER_DB", str(ledger))
    monkeypatch.setenv("KANBAN_BACKUP_AUTONOMY_CONFIG", str(autonomy))

    sources = {source.name: source for source in default_sources()}

    assert sources["autonomy_config"].path == autonomy
    assert sources["autonomy_config"].required is True
    assert sources["autonomy_config"].sensitive is False


def test_autonomy_registry_change_changes_backup_watermark(tmp_path):
    autonomy = tmp_path / "autonomy.yaml"
    data = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs" / "autonomy.yaml")
        .read_text(encoding="utf-8"))
    autonomy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    source = [BackupSource(
        "autonomy_config", autonomy, "file", sensitive=False)]
    first = create_snapshot(tmp_path / "backups", source)
    data["completed_work"].append("backup_watermark_test")
    autonomy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    second = create_snapshot(tmp_path / "backups", source)

    assert second["source_set_watermark"] != first["source_set_watermark"]


def test_refresh_snapshot_authorities_fail_closed_when_missing_or_stale(
    tmp_path,
):
    domain = tmp_path / "domain.yaml"
    autonomy = tmp_path / "autonomy.yaml"
    domain.write_text(
        "schema_version: command-center.domain-surfaces.v1\ndomains: []\n",
        encoding="utf-8",
    )
    autonomy.write_text(
        (Path(__file__).resolve().parents[1] / "configs" / "autonomy.yaml")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    sources = [
        BackupSource("domain_config", domain, "file", sensitive=False),
        BackupSource("autonomy_config", autonomy, "file", sensitive=False),
    ]
    complete = create_snapshot(tmp_path / "complete", sources)
    snapshot = tmp_path / "complete" / complete["snapshot_id"]

    assert verify_snapshot_authorities(snapshot, sources)["snapshot_id"] == (
        complete["snapshot_id"])

    autonomy.write_text(
        autonomy.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    with pytest.raises(BackupError, match="authority is stale"):
        verify_snapshot_authorities(snapshot, sources)

    domain_only = create_snapshot(tmp_path / "domain-only", sources[:1])
    with pytest.raises(BackupError, match="missing required authority"):
        verify_snapshot_authorities(
            tmp_path / "domain-only" / domain_only["snapshot_id"],
            sources,
        )


def test_wal_commit_changes_logical_sqlite_watermark_and_is_restored(tmp_path):
    db_path = tmp_path / "ledger.db"
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
    source = [BackupSource("ledger", db_path, "sqlite")]
    root = tmp_path / "backups"
    first = create_snapshot(root, source)

    with sqlite3.connect(db_path) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO records DEFAULT VALUES")
        writer.commit()
        second = create_snapshot(root, source)

    assert second["source_set_watermark"] != first["source_set_watermark"]
    assert second["snapshot_id"] != first["snapshot_id"]
    restored = tmp_path / "restore-wal"
    restore_to_empty(root / second["snapshot_id"], restored)
    with sqlite3.connect(restored / "data/ledger.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM records").fetchone() == (1,)


def test_manifest_traversal_is_rejected_for_verify_and_restore(tmp_path):
    root = tmp_path / "backups"
    manifest = create_snapshot(root, _fixture_sources(tmp_path))
    snapshot = root / manifest["snapshot_id"]
    manifest_path = snapshot / "manifest.json"
    tampered = json.loads(manifest_path.read_text())
    tampered["sources"][0]["snapshot_path"] = "../outside.db"
    manifest_path.write_text(json.dumps(tampered))
    with pytest.raises(BackupError, match="unsafe snapshot_path"):
        verify_snapshot(snapshot)
    with pytest.raises(BackupError, match="unsafe snapshot_path"):
        restore_to_empty(snapshot, tmp_path / "restore-traversal")


def test_copied_content_must_match_recorded_source_fingerprint(tmp_path, monkeypatch):
    import command_center.runtime_backup as backup

    source = _fixture_sources(tmp_path)[1]
    original = backup._copy_source

    def mismatched(item, root):
        result = original(item, root)
        result["copied_source_fingerprint"] = "not-the-source"
        return result

    monkeypatch.setattr(backup, "_copy_source", mismatched)
    with pytest.raises(BackupError, match="changed while copying"):
        create_snapshot(tmp_path / "backups", [source])


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path regression")
def test_windows_long_paths_verify_and_restore(tmp_path):
    source = tmp_path / "source"
    relative = Path("nested-" + "a" * 70) / ("https___" + "b" * 170 + ".json")
    card = source / relative
    native_card = Path("\\\\?\\" + str(card.resolve(strict=False)))
    native_card.parent.mkdir(parents=True)
    native_card.write_text('{"title":"long path"}\n', encoding="utf-8")
    assert len(str(card.resolve(strict=False))) > 260

    snapshot = create_snapshot(
        tmp_path / "backups",
        [BackupSource("boards", source, "tree")],
    )
    snapshot_root = tmp_path / "backups" / str(snapshot["snapshot_id"])
    verified = verify_snapshot(snapshot_root)
    assert verified["source_set_watermark"] == snapshot["source_set_watermark"]

    restored = tmp_path / "restored"
    restore_to_empty(snapshot_root, restored)
    restored_card = restored / "data" / "boards" / relative
    assert Path("\\\\?\\" + str(restored_card.resolve(strict=False))).read_text(
        encoding="utf-8"
    ) == '{"title":"long path"}\n'

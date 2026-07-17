"""Operator CLI for immutable runtime snapshots and staging-only restores."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from command_center.runtime_backup import (
    BackupError,
    create_default_snapshot,
    restore_to_empty,
    verify_snapshot,
)


def _root() -> Path:
    return Path(os.environ.get("KANBAN_BACKUP_ROOT", "backups/kanban"))


def _latest(root: Path) -> Path:
    rows = sorted(
        path for path in root.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    )
    if not rows:
        raise BackupError(f"no snapshots found under {root}")
    return rows[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cc backup")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create", help="create and verify a current content-addressed snapshot")
    verify = sub.add_parser("verify", help="verify one snapshot (latest by default)")
    verify.add_argument("snapshot", nargs="?")
    sub.add_parser("list", help="list immutable snapshots")
    restore = sub.add_parser("restore", help="restore only into an empty staging directory")
    restore.add_argument("--snapshot")
    restore.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    root = _root()
    try:
        if args.command == "create":
            result = create_default_snapshot()
        elif args.command == "verify":
            result = verify_snapshot(Path(args.snapshot) if args.snapshot else _latest(root))
        elif args.command == "list":
            result = {
                "backup_root": str(root),
                "snapshots": [
                    verify_snapshot(path)["snapshot_id"]
                    for path in sorted(root.glob("*"))
                    if path.is_dir() and not path.name.startswith(".")
                ],
            }
        else:
            snapshot = Path(args.snapshot) if args.snapshot else _latest(root)
            result = restore_to_empty(snapshot, Path(args.target))
        if args.command in {"create", "verify"}:
            result = {
                key: result.get(key) for key in (
                    "schema_version", "snapshot_id", "created_at", "gate_checked_at",
                    "source_set_watermark", "consistency", "retention", "protection",
                    "reused_exact_watermark",
                ) if result.get(key) is not None
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, OSError, ValueError) as exc:
        parser.exit(1, f"backup failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

"""Durable memory store: persistence + injection/review/prune/verify.

Records live in a JSONL store (per-deployment runtime state). Injection — the
cross-conversation recall path — returns ONLY human-approved, non-stale records
that match the requested scope+subject namespace, each citing its source_ref.
Unapproved records are never injected; project/board memory is namespaced by a
stable id so one repo's memory cannot leak into another.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from command_center.schemas import MemoryRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_stale(record: MemoryRecord, now: datetime) -> bool:
    """A record is stale only per its own retention_policy — no global threshold."""
    policy = record.retention_policy
    if policy == "keep_until_superseded":
        return False
    # form validated by the schema: expire_after_days:<N>
    days = int(policy.split(":", 1)[1])
    return _parse_ts(record.updated_at) + timedelta(days=days) < now


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[MemoryRecord]:
        if not self.path.is_file():
            return []
        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(MemoryRecord.model_validate_json(line))
        return records

    def _save(self, records: list[MemoryRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8"
        )

    def add(self, record: MemoryRecord) -> MemoryRecord:
        records = self.load()
        if any(r.memory_id == record.memory_id for r in records):
            raise ValueError(f"memory_id {record.memory_id!r} already exists")
        records.append(record)  # MemoryRecord validation already rejected secrets/no-source
        self._save(records)
        return record

    def inject(
        self, *, scope: str, subject: str, now: Callable[[], datetime] | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return recall-eligible memories for scope+subject (the cross-conversation path)."""
        when = now() if callable(now) else (now or _utc_now())
        out: list[dict[str, Any]] = []
        for r in self.load():
            if r.scope != scope or r.subject != subject:
                continue
            if not r.approved_by_human:      # unapproved memory is never recalled
                continue
            if r.inject_policy == "never":
                continue
            if is_stale(r, when):
                continue
            out.append({"memory_id": r.memory_id, "value": r.value,
                        "source_ref": r.source_ref, "confidence": r.confidence,
                        "scope": r.scope, "subject": r.subject})
        return out

    def review(self, *, now: datetime | None = None) -> dict[str, Any]:
        when = now or _utc_now()
        rows = [{
            "memory_id": r.memory_id, "scope": r.scope, "subject": r.subject,
            "approved_by_human": r.approved_by_human, "sensitivity": r.sensitivity,
            "redaction_status": r.redaction_status, "inject_policy": r.inject_policy,
            "retention_policy": r.retention_policy, "stale": is_stale(r, when),
            "source_ref": r.source_ref,
        } for r in self.load()]
        return {
            "store_path": str(self.path), "total": len(rows),
            "approved": sum(1 for r in rows if r["approved_by_human"]),
            "pending_approval": sum(1 for r in rows if not r["approved_by_human"]),
            "stale": sum(1 for r in rows if r["stale"]),
            "records": rows,
        }

    def prune(self, *, now: datetime | None = None, apply: bool = False) -> dict[str, Any]:
        when = now or _utc_now()
        records = self.load()
        stale = [r for r in records if is_stale(r, when)]
        if apply and stale:
            self._save([r for r in records if not is_stale(r, when)])
        return {
            "store_path": str(self.path), "stale_count": len(stale),
            "stale_ids": [r.memory_id for r in stale],
            "removed": len(stale) if apply else 0, "applied": apply,
        }

    def verify(self) -> dict[str, Any]:
        blockers: list[str] = []
        seen: set[str] = set()
        records = self.load()  # load() re-validates each record via the schema
        for r in records:
            if r.memory_id in seen:
                blockers.append(f"duplicate_memory_id_{r.memory_id}")
            seen.add(r.memory_id)
            if not r.source_ref:
                blockers.append(f"missing_source_ref_{r.memory_id}")
            if r.sensitivity == "confidential" and r.redaction_status != "redacted":
                blockers.append(f"unredacted_confidential_{r.memory_id}")
        return {
            "schema_version": "command-center.memory-verify.v1",
            "store_path": str(self.path),
            "status": "pass" if not blockers else "blocked",
            "record_count": len(records),
            "blockers": blockers,
        }


def inject_memories(
    *, store_path: Path, scope: str, subject: str,
    now: Callable[[], datetime] | datetime | None = None,
) -> list[dict[str, Any]]:
    """Convenience entry point for the gateway to recall approved memories."""
    return MemoryStore(store_path).inject(scope=scope, subject=subject, now=now)

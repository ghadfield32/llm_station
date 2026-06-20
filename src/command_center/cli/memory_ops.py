"""Memory operations: add / review / prune / verify.

Durable cross-conversation memory. New records default to UNAPPROVED (pending) —
they are never recalled in another conversation until a human approves them with
--approved-by. Secrets are rejected at add time; provenance (--source-ref) is
required; project/board memory is namespaced by a stable id.

  cc memory-add --scope project --subject <repo_id> --value "<fact>" \
      --source-ref <ref> [--approved-by <name>] [--sensitivity internal] \
      [--inject-policy on_subject_match] [--retention-policy keep_until_superseded]
  cc memory-review
  cc memory-prune [--apply]
  cc memory-verify
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from command_center.memory import MemoryStore
from command_center.schemas import MemoryConfig, MemoryRecord

ROOT = Path(__file__).resolve().parents[3]
CONFIG = "configs/memory.yaml"


def _load_config(root: Path) -> MemoryConfig:
    return MemoryConfig.model_validate(
        yaml.safe_load((root / CONFIG).read_text(encoding="utf-8"))
    )


def _store(root: Path, cfg: MemoryConfig) -> MemoryStore:
    store_path = Path(cfg.store_path)
    if not store_path.is_absolute():
        store_path = root / store_path
    return MemoryStore(store_path)


def _memory_id(scope: str, subject: str, value: str, created_at: str) -> str:
    digest = hashlib.sha256(f"{scope}|{subject}|{value}|{created_at}".encode("utf-8")).hexdigest()
    return f"mem-{scope}-{digest[:12]}"


def add_memory(
    *, root: Path, scope: str, subject: str, value: str, source_ref: str,
    sensitivity: str, inject_policy: str | None, retention_policy: str | None,
    confidence: float, approved_by: str | None, redaction_status: str,
    now: datetime | None = None,
) -> dict:
    cfg = _load_config(root)
    when = (now or datetime.now(timezone.utc)).isoformat()
    record = MemoryRecord(
        memory_id=_memory_id(scope, subject, value, when),
        scope=scope,  # type: ignore[arg-type]
        subject=subject,
        value=value,
        source_ref=source_ref,
        created_at=when,
        updated_at=when,
        confidence=confidence,
        sensitivity=sensitivity,  # type: ignore[arg-type]
        redaction_status=redaction_status,  # type: ignore[arg-type]
        approved_by_human=bool(approved_by),
        inject_policy=inject_policy or cfg.default_inject_policy,
        retention_policy=retention_policy or cfg.default_retention_policy,
    )  # validation rejects secrets / missing source_ref / bad namespace
    _store(root, cfg).add(record)
    return {
        "status": "added", "memory_id": record.memory_id,
        "approved_by_human": record.approved_by_human,
        "approved_by": approved_by,
        "note": ("recallable in other conversations" if record.approved_by_human
                 else "PENDING approval -- not recalled until a human approves with --approved-by"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="memory-ops")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    pa.add_argument("--scope", required=True,
                    choices=["conversation", "project", "board", "user_preference", "artifact"])
    pa.add_argument("--subject", required=True)
    pa.add_argument("--value", required=True)
    pa.add_argument("--source-ref", required=True)
    pa.add_argument("--sensitivity", default="internal",
                    choices=["public", "internal", "confidential"])
    pa.add_argument("--inject-policy", default=None,
                    choices=["always", "on_subject_match", "never"])
    pa.add_argument("--retention-policy", default=None)
    pa.add_argument("--confidence", type=float, default=1.0)
    pa.add_argument("--approved-by", default=None)
    pa.add_argument("--redaction-status", default="not_required",
                    choices=["redacted", "not_required", "pending"])
    sub.add_parser("review")
    pp = sub.add_parser("prune")
    pp.add_argument("--apply", action="store_true")
    sub.add_parser("verify")
    args = parser.parse_args()

    cfg = _load_config(ROOT)
    store = _store(ROOT, cfg)
    if args.cmd == "add":
        try:
            result = add_memory(
                root=ROOT, scope=args.scope, subject=args.subject, value=args.value,
                source_ref=args.source_ref, sensitivity=args.sensitivity,
                inject_policy=args.inject_policy, retention_policy=args.retention_policy,
                confidence=args.confidence, approved_by=args.approved_by,
                redaction_status=args.redaction_status,
            )
        except (ValidationError, ValueError) as exc:
            # fail loud, clearly (e.g. secret-bearing value, missing source_ref)
            msg = str(exc).splitlines()[1].strip() if "\n" in str(exc) else str(exc)
            print(f"memory-add: BLOCKED\n  {msg}")
            return 1
        print(f"memory-add: {result['status'].upper()} {result['memory_id']}")
        print(f"  {result['note']}")
        return 0
    if args.cmd == "review":
        r = store.review()
        print(f"memory-review: {r['total']} records "
              f"({r['approved']} approved, {r['pending_approval']} pending, {r['stale']} stale)")
        for rec in r["records"]:
            flag = "approved" if rec["approved_by_human"] else "PENDING"
            stale = " STALE" if rec["stale"] else ""
            print(f"  [{flag}{stale}] {rec['scope']}/{rec['subject']} {rec['memory_id']} "
                  f"<- {rec['source_ref']}")
        return 0
    if args.cmd == "prune":
        r = store.prune(apply=args.apply)
        print(f"memory-prune: {r['stale_count']} stale, removed {r['removed']} (applied={r['applied']})")
        return 0
    if args.cmd == "verify":
        r = store.verify()
        print(f"memory-verify: {r['status'].upper()} ({r['record_count']} records)")
        for b in r["blockers"]:
            print(f"  BLOCKED: {b}")
        return 0 if r["status"] == "pass" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

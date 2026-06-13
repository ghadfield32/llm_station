"""
The Growth OS "improvements" board surface.

The Ledger stays authoritative; the board is a human review and navigation surface —
a projection of the experiment registry into the fields a human scans. Two rules from
the mission hold here:

  * agent-synced rows land in a non-approved state — the board never invents a human
    decision. HumanDecision/ReviewNotes/ReopenConditions are HUMAN-owned and the sync
    preserves whatever a human put there (never clobbered).
  * it works offline: the default sink is a JSON file, so the board is exportable and
    testable without AppFlowy reachable. A live AppFlowy sink upserts the same rows
    through the curator's clobber-safe action layer.

This mirrors the existing curator discipline (mission_intake: agents may draft, never
approve; packages.py: Status only on new rows; book_note: append, don't overwrite).
"""
from __future__ import annotations

import json
from pathlib import Path

from .registry import ExperimentRegistry

# The board columns (mission section 10). HUMAN_OWNED ones are never overwritten by sync.
BOARD_FIELDS = [
    "ExperimentID", "Title", "TargetType", "Target", "Hypothesis", "Status",
    "Decision", "Risk", "Baseline", "Candidate", "PrimaryMetric", "VerifierVerdict",
    "HumanDecision", "MissionID", "CanaryStatus", "RollbackStatus", "ReopenConditions",
    "Created", "LastUpdated", "ReviewNotes",
]
HUMAN_OWNED = frozenset({"HumanDecision", "ReopenConditions", "ReviewNotes"})


def experiment_to_row(exp: dict, defn: dict | None) -> dict:
    """Project one registry experiment row into a board row. Ledger-derived fields
    only — the human-owned fields default empty (a human fills them in on the board)."""
    primary = ""
    reopen = ""
    if defn:
        req = [m for m in defn.get("metrics", []) if m.get("required")]
        if req:
            primary = req[0]["name"]
        reopen = "; ".join(defn.get("post_watch", {}).get("rollback_triggers", []))
    return {
        "ExperimentID": exp["experiment_id"],
        "Title": exp.get("title", ""),
        "TargetType": exp.get("target_type", ""),
        "Target": exp.get("target_ref", ""),
        "Hypothesis": (defn or {}).get("hypothesis", ""),
        "Status": exp.get("status", ""),
        "Decision": _decision_hint(exp),
        "Risk": exp.get("risk_tier", ""),
        "Baseline": exp.get("baseline_version", ""),
        "Candidate": exp.get("candidate_version", ""),
        "PrimaryMetric": primary,
        "VerifierVerdict": exp.get("verifier_verdict") or "",
        "HumanDecision": exp.get("human_decision") or "",   # Ledger-sourced; set only by humans
        "MissionID": exp.get("mission_id") or "",
        "CanaryStatus": exp.get("canary_status") or "",
        "RollbackStatus": exp.get("rollback_status") or "",
        "ReopenConditions": reopen,                          # default; a human may override
        "Created": exp.get("created_at", ""),
        "LastUpdated": exp.get("updated_at", ""),
        "ReviewNotes": "",                                   # human-owned; never set by sync
    }


def _decision_hint(exp: dict) -> str:
    """A NON-binding navigation hint, not a decision. The human decides."""
    status = exp.get("status", "")
    if status == "Verified":
        return "awaiting human promotion"
    if status in ("Rejected", "Inconclusive", "Rolled Back"):
        return status.lower()
    if status == "Promoted":
        return "promoted"
    return ""


class BoardSink:
    """Where board rows live. Implementations must be clobber-safe on upsert."""
    def existing(self) -> dict[str, dict]:
        raise NotImplementedError

    def write(self, rows: dict[str, dict]) -> None:
        raise NotImplementedError


class FileBoardSink(BoardSink):
    """Offline JSON sink — the exportable board. Used when AppFlowy is not reachable
    and by the tests."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def existing(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {r["ExperimentID"]: r for r in data.get("rows", [])}

    def write(self, rows: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(rows.values(), key=lambda r: r.get("LastUpdated", ""), reverse=True)
        self.path.write_text(json.dumps({"rows": ordered}, indent=2), encoding="utf-8")


class GrowthOsBoardSink(BoardSink):
    """Upserts board rows into a live Growth OS / AppFlowy 'improvements' database through
    a pluggable client, clobber-safe. The client is any object with
    `list_rows(database) -> list[dict]` and `upsert(database, rows)` — in production a thin
    wrapper over the curator's AppFlowyClient (whose `upsert` already dedupes server-side by
    a stable key). Kept behind this interface so the clobber-safe logic is testable offline
    with a fake client; only the real network call needs a reachable AppFlowy."""

    def __init__(self, client, database: str = "improvements", key_field: str = "ExperimentID"):
        self.client = client
        self.database = database
        self.key_field = key_field

    def existing(self) -> dict[str, dict]:
        rows = self.client.list_rows(self.database)
        return {r[self.key_field]: r for r in rows if r.get(self.key_field)}

    def write(self, rows: dict[str, dict]) -> None:
        # one upsert per row keyed by ExperimentID; human-owned fields were already
        # preserved by ImprovementsBoard.sync's merge_clobber_safe before reaching here.
        self.client.upsert(self.database, list(rows.values()))


def merge_clobber_safe(existing: dict, incoming: dict) -> dict:
    """Agent sync rules: update Ledger-derived fields; NEVER overwrite a human-owned
    field that already holds a value."""
    merged = dict(incoming)
    for field in HUMAN_OWNED:
        prior = existing.get(field, "")
        if prior:                      # a human wrote something — keep it
            merged[field] = prior
    return merged


class ImprovementsBoard:
    def __init__(self, registry: ExperimentRegistry):
        self.reg = registry

    def rows(self) -> list[dict]:
        out = []
        for exp in self.reg.list_experiments():
            out.append(experiment_to_row(exp, self.reg.definition(exp["experiment_id"])))
        return out

    def sync(self, sink: BoardSink, *, dry_run: bool = True) -> dict:
        """Project the registry to the board, clobber-safe. dry_run reports the diff
        without writing. Agent-created entries never carry a human decision."""
        existing = sink.existing()
        new_rows: dict[str, dict] = dict(existing)
        created, updated, preserved = [], [], []
        for row in self.rows():
            eid = row["ExperimentID"]
            if eid in existing:
                merged = merge_clobber_safe(existing[eid], row)
                if any(existing[eid].get(f) for f in HUMAN_OWNED):
                    preserved.append(eid)
                new_rows[eid] = merged
                updated.append(eid)
            else:
                new_rows[eid] = row
                created.append(eid)
        if not dry_run:
            sink.write(new_rows)
        return {"created": created, "updated": updated,
                "human_fields_preserved": preserved, "dry_run": dry_run,
                "total": len(new_rows)}

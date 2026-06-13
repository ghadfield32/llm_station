"""
The observer-only charter — the structural wall around the daily scan.

The scan (and therefore the Airflow DAG that runs it) may read the Ledger/registry, read open
findings and the negative-result memory, draft Backlog cards (Proposed experiments only), and
write ONE report artifact. Nothing else. Promotion, canary, merge, deploy, secret rotation, and
arbitrary status changes are not methods on this object — accessing them raises CharterViolation.

This is the proactive-runner charter made structural: even a buggy or compromised scan task
cannot promote or merge, because the capability simply isn't reachable through the charter.
Drafting is idempotent (a re-run won't duplicate a card), satisfying the DAG's idempotency rule.
"""
from __future__ import annotations

from pathlib import Path

from ..lifecycle import ExperimentStatus
from ..registry import ExperimentRegistry
from ..schema import ExperimentDefinition

# the ONLY capabilities an observer has
_ALLOWED = frozenset({
    "read_experiments", "read_open_findings", "read_negative_results",
    "draft_backlog_card", "write_report", "capabilities",
})
# capabilities that must never be reachable through the charter
_FORBIDDEN = frozenset({
    "promote", "canary", "start_canary", "merge", "deploy", "publish", "rotate_secrets",
    "set_status", "execute", "approve", "push", "request_human_promotion", "rollback",
})

_OPEN_STATES = ("Proposed", "Baseline Ready", "Running", "Awaiting Verification")
_NEGATIVE_STATES = ("Rejected", "Inconclusive", "Rolled Back", "Expired")


class CharterViolation(RuntimeError):
    pass


class ObserverCharter:
    def __init__(self, registry: ExperimentRegistry, *,
                 report_path: str | Path = "generated/self-improvement-report.md"):
        self.reg = registry
        self.report_path = Path(report_path)

    def capabilities(self) -> list[str]:
        return sorted(_ALLOWED)

    # ---- reads --------------------------------------------------------------

    def read_experiments(self) -> list[dict]:
        return self.reg.list_experiments()

    def read_open_findings(self) -> list[dict]:
        return [e for e in self.reg.list_experiments() if e["status"] in _OPEN_STATES]

    def read_negative_results(self) -> list[dict]:
        return [e for e in self.reg.list_experiments() if e["status"] in _NEGATIVE_STATES]

    # ---- the ONLY two writes ------------------------------------------------

    def draft_backlog_card(self, definition: ExperimentDefinition) -> dict | None:
        """Register a Proposed experiment as a Backlog card. Refuses anything not Proposed;
        idempotent (re-running the scan won't duplicate a card). Returns the row or None if it
        already existed."""
        if definition.status != ExperimentStatus.PROPOSED:
            raise CharterViolation(
                f"observer may only draft Proposed cards, got {definition.status.value!r}")
        if self.reg.get(definition.experiment_id):
            return None
        return self.reg.register(definition, mission_id=None)

    def write_report(self, markdown: str) -> str:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(markdown, encoding="utf-8")
        return str(self.report_path)

    # ---- structural guard: forbidden capabilities are unreachable -----------

    def __getattr__(self, name: str):
        if name in _FORBIDDEN:
            raise CharterViolation(
                f"observer charter forbids {name!r} — promotion/canary/merge/deploy stay "
                "human-only; the scan only drafts Proposed cards and writes a report")
        raise AttributeError(name)

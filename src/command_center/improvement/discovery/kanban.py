"""
Self-improvement scan → human-gated Kanban cards.

Closes the "report on how to self-improve every day and apply those if approved" loop: the daily
scan's top-ranked findings become Backlog drafts on the first-party Self Improvement board.
They become real work only through the existing human-gated workflow. Observer-only — this
module drafts and refreshes evidence but never approves.

`draft_self_improvement_cards` is pure and takes an injected `draft_card` callable so it is fully
testable offline; `command_center_card_drafter()` binds the live first-party board provider.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .pipeline import ScanReport

_GROWTHOS_ROOT = Path(__file__).resolve().parents[4] / "growth_os"
# add_mission_card validates risk as bare L0–L4; our findings carry "L2_local_edits" etc.
_VALID_RISK = {"L0", "L1", "L2", "L3", "L4"}
DEFAULT_BOARD_ID = "self_improvement"


def _risk_code(risk_value: str) -> str:
    """Map a RiskTier value ("L2_local_edits") to add_mission_card's bare code ("L2")."""
    code = risk_value.split("_", 1)[0]
    if code not in _VALID_RISK:
        raise ValueError(f"cannot map risk {risk_value!r} to L0–L4")
    return code


def draft_self_improvement_cards(report: ScanReport, *, draft_card: Callable[..., str],
                                 top_n: int = 3, section: str = "Command Center") -> list[dict]:
    """Draft the top-N ranked findings as Backlog mission cards via the injected `draft_card`
    (the add_mission_card action). Returns one summary per card. Drafts only — never approves."""
    out: list[dict] = []
    for finding, score in report.ranked[:top_n]:
        acceptance = f"Evidence: {finding.evidence}"
        if finding.unknowns:
            acceptance += f" · Unknown: {finding.unknowns}"
        result = draft_card(
            card_id=finding.experiment_id,
            title=f"[self-improve] {finding.title}"[:120],
            section=section,
            action=finding.claim,
            acceptance=acceptance,
            risk=_risk_code(finding.suggested_risk.value),
            priority="P2",
            notes=(f"pillar={finding.pillar.value} · {report.method.upper()} score={score:.2f} "
                   f"· experiment {finding.experiment_id}"),
            pillar=finding.pillar.value,
            score=score,
            source=finding.source,
            evidence=finding.evidence,
            unknowns=finding.unknowns,
            repo_ids=list(finding.detail.get("repo_ids") or []),
            repository_reason=str(finding.detail.get("repository_reason") or (
                "Cross-system opportunity; review under All repositories before scoping work.")),
        )
        out.append({"title": finding.title, "experiment_id": finding.experiment_id,
                    "result": result})
    return out


def command_center_card_drafter(*, board_id: str | None = None) -> Callable[..., str]:
    """Bind scan output to the governed first-party Self Improvement board.

    Experiment IDs are card IDs, making retries idempotent. Existing cards have
    their evidence refreshed without emitting a second creation event.
    """
    import os
    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.kanban_sync.events import EventLog

    target = board_id or os.environ.get("SELF_IMPROVEMENT_BOARD_ID", DEFAULT_BOARD_ID)
    event_path = os.environ.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl")
    store_path = os.environ.get("KANBAN_BOARD_STORE", "generated/boards")
    provider = CommandCenterBoardProvider(
        board_id=target, event_log=EventLog(event_path), store_dir=Path(store_path))

    def drafter(**fields) -> str:
        card_id = str(fields.pop("card_id"))
        fields["experiment_id"] = card_id
        existing = any(card.get("card_id") == card_id for card in provider.list_cards())
        provider.upsert_card(card_id, fields, status=None if existing else "Backlog")
        verb = "updated" if existing else "drafted"
        return f"{verb} {card_id} on {target} in Backlog; human review required"

    return drafter


def growthos_card_drafter() -> Callable[..., str]:
    """The live `add_mission_card`, wrapped to run from the growth-os root (where its .env/config
    live) and recorded to the agent-call log. Raises loudly if growthos is not importable."""
    import os
    import sys
    root = str(_GROWTHOS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from growthos import actions  # type: ignore[import-not-found]  # runtime sibling pkg
    from growthos.observability import logged  # type: ignore[import-not-found]
    base = logged(actions.add_mission_card, "self-improve-scan")

    def drafter(**kw) -> str:
        # Compatibility for callers still selecting the retired external sink.
        for field in (
            "card_id", "pillar", "score", "source", "evidence", "unknowns",
            "repo_ids", "repository_reason",
        ):
            kw.pop(field, None)
        prev = os.getcwd()
        os.chdir(root)                 # actions read config/.env relative to cwd
        try:
            return base(**kw)
        finally:
            os.chdir(prev)
    return drafter

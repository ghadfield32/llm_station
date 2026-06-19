"""
Self-improvement scan → human-gated Kanban cards.

Closes the "report on how to self-improve every day and apply those if approved" loop: the daily
scan's top-ranked findings become DRAFT cards on the AppFlowy `mission_intake` board (Status =
Backlog). They become real work ONLY after the human drags one to Approved, which the existing
Kanban bridge turns into a gated Ledger mission. Observer-only — this drafts to Backlog and can
never approve (there is no approve verb; staging to Approved is a human drag).

`draft_self_improvement_cards` is pure and takes an injected `draft_card` callable so it is fully
testable offline; `growthos_card_drafter()` binds the live `growthos.actions.add_mission_card`
(recorded to the agent-call log) for the CLI.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .pipeline import ScanReport

_GROWTHOS_ROOT = Path(__file__).resolve().parents[4] / "appflowy_kanban" / "growth-os"
# add_mission_card validates risk as bare L0–L4; our findings carry "L2_local_edits" etc.
_VALID_RISK = {"L0", "L1", "L2", "L3", "L4"}


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
            title=f"[self-improve] {finding.title}"[:120],
            section=section,
            action=finding.claim,
            acceptance=acceptance,
            risk=_risk_code(finding.suggested_risk.value),
            priority="P2",
            notes=(f"pillar={finding.pillar.value} · {report.method.upper()} score={score:.2f} "
                   f"· experiment {finding.experiment_id}"),
        )
        out.append({"title": finding.title, "experiment_id": finding.experiment_id,
                    "result": result})
    return out


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
        prev = os.getcwd()
        os.chdir(root)                 # actions read config/.env relative to cwd
        try:
            return base(**kw)
        finally:
            os.chdir(prev)
    return drafter

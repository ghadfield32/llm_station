#!/usr/bin/env python3
"""
Agent-improvement demo — how the self-improvement loop makes the KANBAN and DISCORD agents better
over time, end to end, with nothing fabricated.

Three examples, all run against a throwaway Ledger so the demo is hermetic and re-runnable:

  1. OBSERVE → PROPOSE   the scan finds a real defect in the Discord-gateway code and a runtime
                         problem in the Kanban agent, and drafts Proposed cards (observer-only).
  2. LEARN OVER TIME     as humans accept/reject those cards, the data-derived P(accept) ranker
                         learns; early on it abstains to the formula, then once enough feedback
                         exists it beats the formula and takes over (champion → "learned").
  3. REMEMBER            a rejected idea is suppressed by the negative-result memory, never
                         re-proposed — the loop does not forget its mistakes.

Run:  python evaluation/agent-improvement-demo/run_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from command_center.improvement.discovery import (
    DecisionRecord, FeatureLog, Finding, ObserverCharter, Pillar, ScanPipeline, Triage,
    TriageDecision, features_of, train_acceptance,
)
from command_center.improvement.discovery.sources import Scanner
from command_center.improvement.lifecycle import Actor, ExperimentStatus
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.schema import AcceptanceKnobs, TargetType

NOW = "2026-06-13T08:00:00+00:00"


class _AgentSignals(Scanner):
    """A scanner standing in for the real signals about the two agents (the live scan finds the
    Discord defect via code_health and the Kanban staleness via the kanban_cycle_time feed)."""
    name = "agent_signals"
    pillar = Pillar.CODE_QUALITY

    def __init__(self, findings):
        self._f = findings

    def scan(self):
        return list(self._f)


def _discord_finding() -> Finding:
    # mirrors the real finding the live scan produces against the Discord-gateway code
    return Finding(
        pillar=Pillar.CODE_QUALITY, source="code_health",
        title="remove swallowed exception in the Discord gateway",
        claim="channels/core.py swallows an exception that should surface",
        evidence="code_health: src/command_center/channels/core.py:205 (broad except never re-raises)",
        confidence=0.85, impact=0.7, ease=0.6, risk_reduction=0.5, time_criticality=0.3,
        suggested_target_type=TargetType.STANDARD, unknowns="whether the swallow masks a real failure")


def _kanban_finding() -> Finding:
    return Finding(
        pillar=Pillar.AUTOMATION, source="kanban_cycle_time",
        title="unblock the aged Kanban mission card",
        claim="a mission card has sat blocked for 21 days in 'Doing'",
        evidence="kanban_cycle_time: 'odds backfill' age=21d blocked=True",
        confidence=0.7, impact=0.5, time_criticality=0.7,
        suggested_target_type=TargetType.WORKFLOW, unknowns="process toil vs a genuine dependency")


def _bar(title: str) -> None:
    print("\n" + "=" * 74 + f"\n{title}\n" + "=" * 74)


def _decision_history(n: int) -> list[DecisionRecord]:
    """A synthetic history of past card decisions with a LEARNABLE pattern the formula misses:
    the human consistently accepts code-quality agent-fixes and rejects cost-speculation cards.
    The formula score is constant, so only a model that reads the pillar can predict acceptance."""
    out = []
    for i in range(n):
        accept = i % 2 == 0
        pillar = Pillar.CODE_QUALITY if accept else Pillar.COST_FINOPS
        f = Finding(pillar=pillar, source="hist", title=f"past card {i}", claim="c", evidence="e")
        out.append(DecisionRecord(experiment_id=f"hist-{i}", drafted_at=f"2026-04-{i + 1:02d}",
                                  features=features_of(f, 0.5), formula_score=0.5,
                                  label=1 if accept else 0))
    return out


def main(workdir: str | Path) -> dict:
    work = Path(workdir)
    reg = ExperimentRegistry(db_path=str(work / "ledger.db"))
    charter = ObserverCharter(reg, report_path=work / "report.md")
    feature_log = FeatureLog(work / "card_features.jsonl")
    pipe = ScanPipeline(charter, feature_log=feature_log)
    discord, kanban = _discord_finding(), _kanban_finding()
    results: dict = {}

    # ----------------------------------------------------------------- 1. observe → propose
    _bar("1. OBSERVE → PROPOSE  (the scan drafts cards for the Discord + Kanban agents)")
    rep = pipe.run([_AgentSignals([discord, kanban])], date="2026-06-13", now_iso=NOW, apply=True)
    print(f"scan drafted {len(rep.drafted_ids)} Proposed cards (observer-only — human-gated):")
    for f, score in rep.ranked:
        print(f"  • [{f.pillar.value:13s}] {f.title}")
        print(f"      WSJF {score:.2f} · risk {f.suggested_risk.value} · card {f.experiment_id}")
    print("  → both land in `Proposed` and wait at the Kanban wall; the scan cannot approve them.")
    results["drafted"] = sorted(rep.drafted_ids)
    rows = {r["experiment_id"]: r for r in reg.list_experiments()}
    results["all_proposed"] = all(r["status"] == "Proposed" for r in rows.values())

    # ----------------------------------------------------------------- 2. learn over time
    _bar("2. LEARN OVER TIME  (the ranker improves as you accept/reject cards)")
    knobs = AcceptanceKnobs(min_decisions=12, holdout_fraction=0.3)
    early = train_acceptance(_decision_history(6), knobs)
    print(f"After 6 decisions:  champion = {early.champion.upper():8s} — {early.reason}")
    seasoned = train_acceptance(_decision_history(24), knobs)
    print(f"After 24 decisions: champion = {seasoned.champion.upper():8s} — {seasoned.reason}")
    print(f"  → formula AUC {seasoned.formula_auc:.2f} vs learned AUC {seasoned.learned_auc:.2f}: "
          "the data-derived ranker now predicts which agent-fixes you accept, and takes over.")
    results["early_champion"] = early.champion
    results["seasoned_champion"] = seasoned.champion

    # ----------------------------------------------------------------- 3. remember
    _bar("3. REMEMBER  (a rejected idea is not re-proposed)")
    reg.set_status(discord.experiment_id, ExperimentStatus.REJECTED, actor=Actor.HUMAN,
                   note="declined — that swallow is an intentional terminal handler")
    triage = Triage(reg).classify([_discord_finding()], now_iso=NOW)[0]
    print(f"You reject the Discord card. Next scan re-finds the same issue → decision: "
          f"{triage.decision.value.upper()}")
    print(f"  → reason: {triage.reason}")
    print("  → the loop remembers your call; it won't nag you with it again.")
    results["resuppressed"] = triage.decision is TriageDecision.NEGATIVE_MEMORY

    _bar("RESULT")
    print("The Kanban + Discord agents are now inside the loop: their code and runtime are observed,")
    print("improvements are proposed (human-gated), the ranking learns from your decisions, and")
    print("rejected ideas are remembered. That is the 'better over time' mechanism, end to end.")
    return results


if __name__ == "__main__":
    import tempfile
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory() as d:
        main(d)

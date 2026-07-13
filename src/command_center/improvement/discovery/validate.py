"""
The discovery scan's blocking validation gate (PIPELINE_STANDARDS §0.8 "N/N PASS required").

A fast, side-effect-free structural check that the scan's invariants hold: the config validates,
every pillar resolves to a real target + sources, the observer-only wall is intact, a drafted card
is bounded/Proposed/secret-free, the learned ranker carries no leakage feature, and the source
registry is coherent. `make improvement-scan-validate` runs it; a single FAIL exits non-zero, so
a broken scan never reaches a daily run.
"""
from __future__ import annotations

from .charter import CharterViolation, ObserverCharter, _ALLOWED, _FORBIDDEN
from .config import load_discovery_config
from .acceptance import FEATURE_NAMES
from .dag_support import SOURCE_REGISTRY, offline_specs
from .findings import Finding
from .pillars import PILLAR_SOURCES, PILLAR_TARGETS, Pillar, target_for
from .ranking import score
from ..schema import TargetType
from ...schemas.base import RiskTier

_LEAKAGE_TOKENS = ("status", "human_decision", "decision", "verdict", "label",
                   "accept", "reject", "promoted", "canary", "rolled")
_KNOWN_KINDS = {"code_health", "ledger", "papers", "model_registry", "dependencies",
                "kanban", "research"}


def gate_checks() -> list[tuple[str, bool, str]]:
    """Run every gate check. Returns (name, passed, detail) — no side effects, no I/O writes."""
    out: list[tuple[str, bool, str]] = []

    cfg = load_discovery_config("configs/discovery.yaml")   # raises if the YAML is invalid
    out.append(("config_validates", True,
                f"method={cfg.ranking.default_method}, max_cards={cfg.triage.max_cards}"))

    out.append(("every_pillar_maps_to_a_target",
                all(PILLAR_TARGETS.get(p) and isinstance(target_for(p), TargetType)
                    for p in Pillar),
                f"{len(list(Pillar))} pillars"))
    out.append(("every_pillar_has_sources",
                all(PILLAR_SOURCES.get(p) for p in Pillar), ""))

    # observer-only wall is structural: forbidden caps unreachable, allowed set is read/draft/report
    forbidden_unreachable = all(
        name in _FORBIDDEN and name not in ObserverCharter.__dict__
        for name in ("promote", "canary", "merge", "deploy", "set_status"))
    out.append(("charter_forbids_escalation", forbidden_unreachable,
                f"forbidden={sorted(_FORBIDDEN)[:3]}…"))
    out.append(("charter_allows_only_read_draft_report",
                _ALLOWED == {"read_experiments", "read_open_findings", "read_negative_results",
                             "draft_backlog_card", "write_report", "capabilities"},
                ""))

    # a drafted card is bounded / Proposed / secret-free / human-gated
    d = Finding(pillar=Pillar.CODE_QUALITY, source="gate", title="probe",
                claim="c", evidence="e").to_experiment_definition()
    card_ok = (d.status.value == "Proposed" and d.risk_tier in (RiskTier.L0, RiskTier.L1, RiskTier.L2)
               and d.requests_secrets is False and d.promotion.human_approval_required is True
               and d.promotion.automatic_promotion is False
               and d.budgets.max_input_tokens == 0 and d.budgets.max_cost_usd == 0)
    out.append(("drafted_card_is_bounded_proposed_secret_free", card_ok,
                f"status={d.status.value}, risk={d.risk_tier.value}"))

    # the learned ranker must carry no outcome/decision feature (leakage)
    leaks = [f for f in FEATURE_NAMES if any(tok in f.lower() for tok in _LEAKAGE_TOKENS)]
    out.append(("acceptance_features_have_no_leakage", not leaks,
                f"{len(FEATURE_NAMES)} features" if not leaks else f"LEAK: {leaks}"))

    # the source registry is coherent: known kinds, offline subset is network-free
    kinds_ok = all(s["kind"] in _KNOWN_KINDS for s in SOURCE_REGISTRY)
    offline_ok = {s["name"] for s in offline_specs()} == {"code_health", "ledger"}
    out.append(("source_registry_coherent", kinds_ok and offline_ok,
                f"{len(SOURCE_REGISTRY)} sources, offline={sorted(s['name'] for s in offline_specs())}"))

    # ranking methods: the four known resolve, an unknown is rejected (no silent fallback)
    probe = Finding(pillar=Pillar.AUTOMATION, source="g", title="r", claim="c", evidence="e")
    known_ok = all(isinstance(score(probe, m), float) for m in ("ice", "rice", "wsjf", "voi"))
    try:
        score(probe, "bogus")
        unknown_rejected = False
    except ValueError:
        unknown_rejected = True
    out.append(("ranking_methods_known_and_strict", known_ok and unknown_rejected, ""))

    # the charter truly raises on a forbidden capability (behavioural, not just structural)
    out.append(("charter_raises_on_forbidden_access", _charter_raises(), ""))
    return out


def _charter_raises() -> bool:
    import tempfile
    from pathlib import Path
    from ..registry import ExperimentRegistry
    with tempfile.TemporaryDirectory() as d:
        charter = ObserverCharter(ExperimentRegistry(db_path=str(Path(d) / "l.db")))
        try:
            charter.promote      # noqa: B018 — accessing the attribute must raise
            return False
        except CharterViolation:
            return True


def run_gate() -> bool:
    """Print every check and an N/N PASS line. Returns True iff all checks pass."""
    checks = gate_checks()
    passed = 0
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    total = len(checks)
    print(f"discovery-scan-validate: {passed}/{total} "
          + ("PASS" if passed == total else "FAIL"))
    return passed == total

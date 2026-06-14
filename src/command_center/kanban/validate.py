"""Blocking validation gate for the agent kanban surface (N/N PASS required).

Fast, side-effect-free structural checks: the config validates, the tuning learner
carries no leakage feature and honestly abstains below its floor, and every intent
verb targets a legal, non-Approved board column. A single FAIL exits non-zero so a
broken surface never ships. Mirrors discovery/validate.py.
"""
from __future__ import annotations

from ..channels.board_state import LIVE_COLUMNS, load_agent_surface_config
from .features import FEATURE_NAMES, LEAKAGE_TOKENS
from .metrics import BOARD_STATUSES, VERB_COLUMN
from .tuning import ResolutionRecord, recommend_fuzzy_ratio


def gate_checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    cfg = load_agent_surface_config()
    out.append(("config_validates", True,
                f"refresh_every_rounds={cfg.board_state.refresh_every_rounds}, "
                f"fuzzy_min_ratio={cfg.addressing.fuzzy_min_ratio}"))

    boards_known = all(b in LIVE_COLUMNS for b in cfg.board_state.boards)
    out.append(("board_names_resolve_to_columns", boards_known,
                f"boards={cfg.board_state.boards}"))

    leaks = [f for f in FEATURE_NAMES
             if any(tok in f.lower() for tok in LEAKAGE_TOKENS)]
    out.append(("tuning_features_have_no_leakage", not leaks,
                f"{len(FEATURE_NAMES)} features" if not leaks else f"leaks={leaks}"))

    # every verb targets a legal column (full status set, incl. terminal), and
    # none targets the human-only Approved
    bad = [v for v, (board, col) in VERB_COLUMN.items()
           if col not in BOARD_STATUSES.get(board, []) or col == "Approved"]
    out.append(("intent_verbs_target_legal_non_approved_columns", not bad,
                f"{len(VERB_COLUMN)} verbs" if not bad else f"bad={bad}"))

    # the learner must abstain (config value stands) when starved of data
    starved = recommend_fuzzy_ratio([], cfg.tuning, cfg.addressing.fuzzy_min_ratio)
    abstains = starved.source == "config"
    out.append(("tuning_abstains_below_floor", abstains, starved.reason))

    # and it must genuinely learn when data clearly favours a different threshold
    learned = _learns_on_separable_data(cfg)
    out.append(("tuning_learns_on_separable_data", learned,
                "challenger wins on a clean split" if learned
                else "learner failed to adopt an obviously-better threshold"))

    return out


def _learns_on_separable_data(cfg) -> bool:
    """A synthetic, perfectly-separable set where matches >= 0.8 are correct and
    below are wrong: the learner must move off a deliberately-bad config value."""
    knobs = cfg.tuning
    n = max(knobs.min_decisions, 40)
    records = []
    for i in range(n):
        ratio = 0.9 if i % 2 == 0 else 0.5
        records.append(ResolutionRecord(
            ts=f"2026-01-{i % 28 + 1:02d}T00:00:00",
            match_ratio=ratio, correct=ratio >= 0.8))
    # config 0.3 wrongly accepts the 0.5 (incorrect) matches; learner should move up
    res = recommend_fuzzy_ratio(records, knobs, current=0.3)
    return res.source == "learned" and 0.5 < res.value <= 0.9


def run_gate() -> bool:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Windows console: keep unicode intact
    checks = gate_checks()
    passed = 0
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    total = len(checks)
    print(f"kanban-surface-validate: {passed}/{total} "
          + ("PASS" if passed == total else "FAIL"))
    return passed == total

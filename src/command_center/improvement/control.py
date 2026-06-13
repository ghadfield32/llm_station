"""
Phase 6 — AI-control techniques for the autonomy frontier.

The Redwood-style "AI control" toolkit, applied to the isolated execution plane and the
verifier. None of this widens autonomy by removing the human wall; it HARDENS the reject path
(so a subverted implementer/monitor is caught) and formalizes how much evidence must be
assembled before a human is asked. Promotion and canary stay human-only, always.

  * paraphrase — a deterministic canonicalization that strips comments, zero-width tricks,
    and identity markers before the monitor/verifier reads implementer output, breaking
    collusion/steganographic channels (an adaptive attacker can subvert a naive monitor).
  * honeypots — synthetic planted-attack fixtures that confirm a monitor is actually trying;
    a monitor that misses the honeypot is itself flagged.
  * a monitor ensemble — a trusted monitor plus untrusted ones; flag on any catch (defense in
    depth) and surface trusted-vs-untrusted disagreement (a collusion signal).
  * an audit budget — surface the top-K most suspicious actions for scarce human review.
  * a graduated-autonomy gate — required evidence per risk tier before a candidate is eligible
    to reach a human. Eligibility only; the human still promotes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .jury import anonymize

_ZERO_WIDTH = "​‌‍﻿⁠"   # zero-width chars


def paraphrase(text: str) -> str:
    """Deterministic defensive canonicalization: remove comments, zero-width characters, and
    identity markers, and collapse whitespace. Destroys covert side-channels in implementer
    output while preserving the real content tokens. No model call."""
    t = re.sub(f"[{_ZERO_WIDTH}]", "", text)
    t = re.sub(r"#.*?$", " ", t, flags=re.MULTILINE)        # python / shell comments
    t = re.sub(r"//.*?$", " ", t, flags=re.MULTILINE)       # c-style comments
    t = re.sub(r"/\*.*?\*/", " ", t, flags=re.DOTALL)       # block comments
    t = anonymize(t)                                        # identity / self-reference markers
    return re.sub(r"\s+", " ", t).strip()


# ---- honeypots --------------------------------------------------------------

@dataclass
class Honeypot:
    """A planted-attack fixture. ``detector(payload)`` must return True (caught) for a working
    monitor; a honeypot the monitor misses reveals a broken/colluding monitor."""
    id: str
    kind: str            # secret_leak | fabricated_metric | sealed_leak | unauthorized_access
    payload: Any

    def caught_by(self, detector: Callable[[Any], bool]) -> bool:
        return bool(detector(self.payload))


@dataclass
class HoneypotReport:
    caught: list[str]
    missed: list[str]

    @property
    def catch_rate(self) -> float:
        total = len(self.caught) + len(self.missed)
        return len(self.caught) / total if total else 1.0

    def to_dict(self) -> dict:
        return {"caught": self.caught, "missed": self.missed, "catch_rate": self.catch_rate}


def run_honeypots(honeypots: list[Honeypot], detector: Callable[[Any], bool]) -> HoneypotReport:
    caught: list[str] = []
    missed: list[str] = []
    for h in honeypots:
        (caught if h.caught_by(detector) else missed).append(h.id)
    return HoneypotReport(caught=caught, missed=missed)


# ---- monitor ensemble (trusted + untrusted, anti-collusion) -----------------

@dataclass
class EnsembleVerdict:
    flagged: bool
    trusted_flag: bool
    untrusted_flags: dict[str, bool]
    disagreement: bool        # trusted disagrees with the untrusted majority (collusion smell)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class MonitorEnsemble:
    """A weaker TRUSTED monitor plus stronger UNTRUSTED ones. Flag on ANY catch (defense in
    depth — the untrusted monitor can't hide a real issue the trusted one sees), and surface
    disagreement between trusted and the untrusted majority as a collusion signal."""
    trusted: Callable[[Any], bool]
    untrusted: dict[str, Callable[[Any], bool]] = field(default_factory=dict)

    def assess(self, item: Any) -> EnsembleVerdict:
        t = bool(self.trusted(item))
        u = {name: bool(fn(item)) for name, fn in self.untrusted.items()}
        flagged = t or any(u.values())
        u_majority = sum(u.values()) > len(u) / 2 if u else False
        return EnsembleVerdict(flagged=flagged, trusted_flag=t, untrusted_flags=u,
                               disagreement=(t != u_majority) if u else False)


# ---- audit budget -----------------------------------------------------------

def audit_budget(actions: list, *, budget: int,
                 suspicion: Callable[[Any], float]) -> list:
    """Return the ``budget`` most-suspicious actions for human review — the scarce-attention
    allocation. Ties broken by original order (stable)."""
    if budget < 0:
        raise ValueError("audit budget must be >= 0")
    return sorted(actions, key=suspicion, reverse=True)[:budget]


# ---- graduated-autonomy gate ------------------------------------------------

_REQUIRED_EVIDENCE: dict[str, list[str]] = {
    "L0_read_only": ["deterministic_passed"],
    "L1_plan_only": ["deterministic_passed"],
    "L2_local_edits": ["deterministic_passed", "verification_pass"],
    "L3_external_write": ["deterministic_passed", "verification_pass",
                          "rollback_demonstrated", "elevated_human_review"],
    "L4_dangerous": ["deterministic_passed", "verification_pass", "rollback_demonstrated",
                     "elevated_human_review", "independent_replay"],
}


@dataclass
class AutonomyDecision:
    risk_tier: str
    eligible_for_human: bool
    missing: list[str]
    note: str = ("eligibility only — promotion and canary remain HUMAN-ONLY regardless of "
                 "how complete the evidence is")

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def autonomy_gate(risk_tier: str, evidence: dict) -> AutonomyDecision:
    """How much evidence a candidate of this risk tier must assemble before it is eligible to
    reach a human. Higher tiers demand more (rollback demonstrated, elevated review, replay).
    This NEVER promotes — it only decides whether a human should be asked."""
    if risk_tier not in _REQUIRED_EVIDENCE:
        raise ValueError(f"unknown risk tier {risk_tier!r}")
    missing = [r for r in _REQUIRED_EVIDENCE[risk_tier] if not evidence.get(r)]
    return AutonomyDecision(risk_tier=risk_tier, eligible_for_human=not missing, missing=missing)

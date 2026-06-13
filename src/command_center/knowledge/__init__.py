"""
knowledge — the Open Knowledge Format (OKF) producer.

An OBSERVER-ONLY subsystem (like the discovery scan) that reads authoritative sources — configs,
the Ledger, docs, code, DAGs — and emits a portable, Git-backed `knowledge/` bundle of OKF
concepts under the strict `growth-os-0.1` profile. Source systems produce OKF; OKF never modifies
source systems. Every concept is `authority: derived` and points at its authoritative source, so an
agent (Claude/Codex/verifier/proactive runner) can load shared, token-cheap context without
mistaking the projection for the source of truth.
"""
from __future__ import annotations

from .profile import (
    Authority, Confidence, OkfConcept, PROFILE, Sensitivity, SourceSystem, Status,
)
from .document import ConceptDocument, parse_concept, read_concept, write_concept

__all__ = [
    "OkfConcept", "Authority", "Confidence", "Sensitivity", "SourceSystem", "Status", "PROFILE",
    "ConceptDocument", "parse_concept", "read_concept", "write_concept",
]

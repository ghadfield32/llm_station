"""Evidence collectors for proactive checks.

A proactive check declares the evidence it needs (configs/proactive.yaml, each
check's `evidence:` list). This registry maps an evidence key to a function that
gathers the REAL value for a given check/target.

The contract is deliberately strict: there are NO placeholders. A check whose
declared evidence is not fully backed by registered collectors is skipped by the
runner (see app.run_check) — it never asks a judge to rule on fabricated data,
and never opens a mission off a guess. This is the difference between "we don't
know yet" (skip, honestly) and "everything looks broken" (a fake verdict that
the old `f"<{key} for {target}>"` placeholder produced).

To activate a check: register a collector for each of its evidence keys here.
The moment all of a check's keys are wired, the runner starts judging it for
real with zero other changes.
"""
from __future__ import annotations

from typing import Callable

# evidence_key -> collector(check: dict) -> JSON-serialisable evidence value.
# Empty by default: until a key is wired here, any check needing it is skipped.
COLLECTORS: dict[str, Callable[[dict], object]] = {}


def collector(key: str) -> Callable[[Callable[[dict], object]], Callable[[dict], object]]:
    """Decorator: register `fn` as the collector for evidence `key`."""
    def register(fn: Callable[[dict], object]) -> Callable[[dict], object]:
        COLLECTORS[key] = fn
        return fn
    return register


def collect_evidence(check: dict) -> tuple[dict, list[str]]:
    """Gather real evidence for a check.

    Returns (evidence, unwired):
      - evidence: only keys that have a registered collector, with real values.
      - unwired:  declared evidence keys with no collector. If this is non-empty
                  the runner skips the check rather than fabricate the missing
                  pieces — we do not judge partial/fake evidence.
    """
    evidence: dict = {}
    unwired: list[str] = []
    for key in check.get("evidence", []):
        fn = COLLECTORS.get(key)
        if fn is None:
            unwired.append(key)
        else:
            evidence[key] = fn(check)
    return evidence, unwired

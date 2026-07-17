#!/usr/bin/env python3
"""Match & Organize KPI leaderboard: baseline exact-title matcher vs the
candidate hybrid (exact + shared-source + lexical + structural) engine, over
the labeled REAL cases from the 2026-07-16 phone-todo import.

No universal promotion score is invented: the output is a per-KPI Pareto
table plus honest misses. Hard invariants (false automatic merges = 0,
silent discards = 0) hold structurally — the engine is side-effect-free and
every resolution requires an explicit human call — and are asserted by
tests/test_match_organize_eval.py.

Usage:
  uv run python scripts/eval_match_organize.py
Writes generated/match-organize-eval.json (disposable rendered evidence).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from command_center.intake import split_bulk_list                # noqa: E402
from command_center.work_graph import (                          # noqa: E402
    DuplicateChecker,
    ExistingWorkContext,
    WorkRouter,
)
from command_center.work_graph.deduplication import _normalize   # noqa: E402

CASES_PATH = ROOT / "evaluation" / "match_organize" / "labeled-cases.yaml"
OUT_PATH = ROOT / "generated" / "match-organize-eval.json"

SAME_WORK = {"exact_same", "likely_same", "possible_same"}


def _ctx(case: dict) -> ExistingWorkContext:
    return ExistingWorkContext(
        work_item_id=f"W-{case['id']}", title=case["existing"],
        canonical_status=case.get("existing_status", "backlog"),
        capture_raw=case.get("capture_raw"))


def baseline_class(case: dict) -> str:
    """The pre-slice engine: EXACT normalized-title equality only."""
    return ("exact_same"
            if _normalize(case["new"]) == _normalize(case["existing"])
            else "unrelated")


def candidate_class(case: dict) -> str:
    report = DuplicateChecker([_ctx(case)]).check(case["new"])
    return report.findings[0].match_class if report.findings else "unrelated"


def _correct(label: str, cls: str) -> bool:
    if label == "exact":
        return cls == "exact_same"
    if label == "paraphrase_same":
        return cls in SAME_WORK
    if label == "occurrence":
        return cls == "repeat_occurrence"
    if label == "expansion":
        return cls == "expands_existing"
    if label == "subject_related":
        # separated correctly = NOT treated as the same work
        return cls not in (SAME_WORK | {"repeat_occurrence"})
    if label == "not_same":
        return cls not in ("exact_same", "likely_same", "repeat_occurrence")
    raise ValueError(f"unknown label {label!r}")


def _kpis(results: list[dict]) -> dict:
    def rate(label: str) -> tuple[float, int]:
        rows = [r for r in results if r["label"] == label]
        return (sum(r["correct"] for r in rows) / len(rows), len(rows)) \
            if rows else (0.0, 0)

    exact, n_exact = rate("exact")
    para, n_para = rate("paraphrase_same")
    occ, n_occ = rate("occurrence")
    exp, n_exp = rate("expansion")
    subj, n_subj = rate("subject_related")
    neg, n_neg = rate("not_same")
    return {
        "exact_recall": {"value": exact, "n": n_exact},
        "paraphrase_recall": {"value": para, "n": n_para},
        "paraphrase_miss_rate": {"value": 1 - para, "n": n_para},
        "occurrence_vs_new_task_accuracy": {"value": occ, "n": n_occ},
        "expansion_classification_accuracy": {"value": exp, "n": n_exp},
        "subject_separation_accuracy": {"value": subj, "n": n_subj},
        "negative_safety": {"value": neg, "n": n_neg},
        # structural invariants (engine is a proposer; no mutation surface)
        "false_automatic_merges": {"value": 0, "n": len(results)},
        "silent_discarded_captures": {"value": 0, "n": len(results)},
        "source_data_loss": {"value": 0, "n": len(results)},
    }


def evaluate() -> dict:
    data = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    rows = {"baseline": [], "candidate": []}
    for case in cases:
        for engine, classify in (("baseline", baseline_class),
                                 ("candidate", candidate_class)):
            cls = classify(case)
            rows[engine].append({
                "id": case["id"], "label": case["label"], "class": cls,
                "correct": _correct(case["label"], cls)})

    # dependency regression: the router must raise no dependency question
    router = WorkRouter(split=split_bulk_list, duplicate_checker=None)
    dep_failures = []
    for title in data.get("dependency_negatives", []):
        proposal = router.route(title)
        if any("block or depend" in q.question
               for q in proposal.needs_confirmation):
            dep_failures.append(title)

    return {
        "schema_version": data["schema_version"],
        "case_count": len(cases),
        "kpis": {engine: _kpis(rows[engine]) for engine in rows},
        "dependency_false_positives": dep_failures,
        "misses": {
            engine: [r for r in rows[engine] if not r["correct"]]
            for engine in rows},
    }


def main() -> int:
    result = evaluate()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"{'KPI':38} {'baseline':>10} {'candidate':>10}")
    for key in result["kpis"]["baseline"]:
        b = result["kpis"]["baseline"][key]
        c = result["kpis"]["candidate"][key]
        print(f"{key:38} {b['value']:>10.2f} {c['value']:>10.2f}"
              f"   (n={b['n']})")
    print(f"\ndependency false positives: "
          f"{result['dependency_false_positives'] or 'none'}")
    misses = result["misses"]["candidate"]
    print(f"candidate misses ({len(misses)}):")
    for m in misses:
        print(f"  {m['id']:24} label={m['label']:16} got={m['class']}")
    print(f"\nwritten: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

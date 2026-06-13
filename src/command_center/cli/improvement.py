#!/usr/bin/env python3
"""
improvement — the operator interface for the controlled improvement loop.

One CLI over the experiment registry (ledger.db). Read-only commands always run;
write commands are DRY-RUN by default and need --apply. Human-only actions (canary,
promote) additionally need an --approver and refuse to run as an agent.

  python -m command_center.cli.improvement validate
  python -m command_center.cli.improvement list [--status STATUS]
  python -m command_center.cli.improvement register --id EXP-... [--apply]
  python -m command_center.cli.improvement baseline  --id EXP-... [--apply]
  python -m command_center.cli.improvement run       --id EXP-... [--apply]
  python -m command_center.cli.improvement verify    --id EXP-... [--verifier NAME] [--apply]
  python -m command_center.cli.improvement report    --id EXP-...
  python -m command_center.cli.improvement request-promotion --id EXP-... [--apply]
  python -m command_center.cli.improvement canary    --id EXP-... --approver NAME [--apply]
  python -m command_center.cli.improvement promote   --id EXP-... --approver NAME [--apply]
  python -m command_center.cli.improvement rollback  --id EXP-... [--apply]
  python -m command_center.cli.improvement post-watch --id EXP-... --checkpoint 1h [--regression] [--apply]
  python -m command_center.cli.improvement attention
  python -m command_center.cli.improvement board [--apply]
  python -m command_center.cli.improvement calibration
  python -m command_center.cli.improvement search --query TEXT
  python -m command_center.cli.improvement scan [--apply] [--feeds feeds.json] [--show-report]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from command_center.improvement.schema import ImprovementConfig, ExperimentDefinition
from command_center.improvement.registry import ExperimentRegistry
from command_center.improvement.runner import ExperimentRunner
from command_center.improvement.verifier import IndependentVerifier
from command_center.improvement.promotion import PromotionController
from command_center.improvement.board import ImprovementsBoard, FileBoardSink
from command_center.improvement.attention import morning_brief, attention_metrics

# the worked experiments + the per-target reference experiments; both are source of truth
CONFIGS = ["configs/improvement.yaml", "configs/improvement-targets.yaml"]
BOARD_OUT = "generated/improvements-board.json"


def _registry() -> ExperimentRegistry:
    return ExperimentRegistry()


def _all_definitions() -> list[ExperimentDefinition]:
    out: list[ExperimentDefinition] = []
    for path in CONFIGS:
        p = Path(path)
        if not p.exists():
            continue
        cfg = ImprovementConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        out.extend(cfg.experiments)
    return out


def _load_definition(experiment_id: str) -> ExperimentDefinition:
    for e in _all_definitions():
        if e.experiment_id == experiment_id:
            return e
    raise SystemExit(f"experiment {experiment_id!r} not found in {CONFIGS}")


def cmd_validate(args) -> int:
    for e in _all_definitions():
        print(f"  OK   {e.experiment_id}  ({e.target_type.value}, {e.risk_tier.value})")
    print("improvement-validate: PASS")
    return 0


def cmd_list(args) -> int:
    rows = _registry().list_experiments(status=args.status)
    if not rows:
        print("(no experiments registered)")
        return 0
    for r in rows:
        print(f"  {r['experiment_id']:34s} {r['status']:24s} "
              f"verdict={r['verifier_verdict'] or '-':12s} {r['title'][:40]}")
    return 0


def cmd_register(args) -> int:
    defn = _load_definition(args.id)
    if not args.apply:
        print(f"[dry-run] would register {defn.experiment_id} "
              f"({defn.target_type.value}); rerun with --apply")
        return 0
    reg = _registry()
    if reg.get(defn.experiment_id):
        print(f"already registered: {defn.experiment_id}")
        return 0
    reg.register(defn, mission_id=args.mission)
    print(f"registered {defn.experiment_id} (mission {args.mission or '-'}) -> Proposed")
    return 0


def cmd_baseline(args) -> int:
    if not args.apply:
        print(f"[dry-run] would capture baseline for {args.id}; rerun with --apply")
        return 0
    out = ExperimentRunner(_registry(), repo_root=".").run_baseline(args.id, reps=args.reps)
    print(f"baseline {out['run_id']}: "
          + ", ".join(f"{k}={round(v, 3)}" for k, v in out["metric_values"].items()))
    return 0


def cmd_run(args) -> int:
    if not args.apply:
        print(f"[dry-run] would run candidate for {args.id}; rerun with --apply")
        return 0
    cmp = ExperimentRunner(_registry(), repo_root=".").run_candidate(args.id, reps=args.reps)
    print(f"candidate recommendation: {cmp.recommendation} "
          f"(required_pass={cmp.all_required_pass} safety_ok={cmp.safety_ok})")
    for m in cmp.metrics:
        print(f"  {m.name:18s} base={m.baseline_value:.3f} cand={m.candidate_value:.3f} "
              f"passed={m.passed} ({m.reason})")
    return 0


def cmd_verify(args) -> int:
    if not args.apply:
        print(f"[dry-run] would run the independent verifier for {args.id}; rerun with --apply")
        return 0
    rep = IndependentVerifier(_registry(), repo_root=".").verify(
        args.id, verifier_identity=args.verifier, implementer_identity="runner")
    print(f"verdict: {rep.verdict}  ({rep.summary})")
    for c in rep.criteria:
        flag = " [SAFETY]" if c.safety else ""
        print(f"  {c.id} {c.result:14s}{flag} {c.text} :: {c.detail}")
    return 0


def cmd_report(args) -> int:
    reg = _registry()
    exp = reg.get(args.id)
    if not exp:
        raise SystemExit(f"unknown experiment {args.id!r}")
    print(json.dumps({"experiment": exp,
                      "runs": reg.runs(args.id),
                      "events": [{"kind": e["kind"], "action": e["action"]}
                                 for e in reg.events(args.id)],
                      "artifacts": [{"name": a["name"], "kind": a["kind"], "sha256": a["sha256"]}
                                    for a in reg.artifacts(args.id)],
                      "promotion_conditions": reg.promotion_conditions(args.id).__dict__},
                     indent=2, default=str))
    return 0


def cmd_request_promotion(args) -> int:
    if not args.apply:
        print(f"[dry-run] would request human promotion for {args.id}; rerun with --apply")
        return 0
    PromotionController(_registry()).request_human_promotion(args.id)
    print(f"{args.id} -> Awaiting Human Promotion (rollback demonstrated)")
    return 0


def cmd_canary(args) -> int:
    if not args.approver:
        raise SystemExit("canary is a human action — pass --approver YOUR_NAME")
    if not args.apply:
        print(f"[dry-run] {args.approver} would start canary for {args.id}; rerun with --apply")
        return 0
    plan = PromotionController(_registry()).start_canary(args.id, approver=args.approver)
    print(f"canary started by {args.approver}: {plan.active_version} -> {plan.candidate_version}")
    return 0


def cmd_promote(args) -> int:
    if not args.approver:
        raise SystemExit("promote is a human action — pass --approver YOUR_NAME")
    if not args.apply:
        print(f"[dry-run] {args.approver} would promote {args.id}; rerun with --apply")
        return 0
    PromotionController(_registry()).promote(args.id, approver=args.approver)
    print(f"{args.id} promoted by {args.approver}")
    return 0


def cmd_rollback(args) -> int:
    if not args.apply:
        print(f"[dry-run] would roll back {args.id}; rerun with --apply")
        return 0
    PromotionController(_registry()).rollback(args.id, reason=args.reason or "operator rollback")
    print(f"{args.id} rolled back")
    return 0


def cmd_post_watch(args) -> int:
    if not args.apply:
        print(f"[dry-run] would record post-watch {args.checkpoint} for {args.id}; rerun with --apply")
        return 0
    out = PromotionController(_registry()).post_watch(
        args.id, checkpoint=args.checkpoint, regression_detected=args.regression)
    print(f"post-watch {args.checkpoint}: {out['action']}")
    return 0


def cmd_attention(args) -> int:
    print(morning_brief(_registry()))
    print("\n" + json.dumps(attention_metrics(_registry()), indent=2))
    return 0


def cmd_board(args) -> int:
    sink = FileBoardSink(BOARD_OUT)
    res = ImprovementsBoard(_registry()).sync(sink, dry_run=not args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"board sync [{mode}]: created={res['created']} updated={len(res['updated'])} "
          f"human_fields_preserved={res['human_fields_preserved']}")
    if args.apply:
        print(f"wrote {BOARD_OUT}")
    return 0


def cmd_calibration(args) -> int:
    from command_center.improvement.calibration import (
        load_cases, score, reference_defensive_judge, independence_violation,
        load_predictions, score_predictions)
    cases = load_cases("data/calibration/judge-calibration.json")
    if independence_violation(cases, "defensive-coding-judge"):
        print("WARNING: calibration set fails independence (self-certified)")
    if args.predictions:
        # live-judge path: score a real judge's saved {case_id: verdict} predictions
        verdicts, confidences = load_predictions(args.predictions)
        rep = score_predictions(cases, verdicts, confidences)
        print(f"# scored from predictions file {args.predictions}")
    else:
        rep = score(cases, reference_defensive_judge)
    print(json.dumps(rep.to_dict(), indent=2))
    return 0


def cmd_search(args) -> int:
    for r in _registry().search(args.query):
        print(f"  {r['experiment_id']:34s} {r['status']:20s} {r['title'][:50]}")
    return 0


def cmd_propose(args) -> int:
    from command_center.improvement.proposals import (
        ProposalGenerator, EvidenceSignal, EvidenceSource)
    if args.signals:
        raw = json.loads(Path(args.signals).read_text(encoding="utf-8"))
        signals = [EvidenceSignal(source=EvidenceSource(s["source"]), **{
            k: v for k, v in s.items() if k != "source"}) for s in raw]
    else:
        # a small demonstration batch: one actionable signal, one duplicate, one noise
        signals = [
            EvidenceSignal(source=EvidenceSource.SLOW_RETRIEVAL,
                           target_ref="command_center.retrieval", observed=4200, threshold=2000,
                           direction="increase", occurrences=5, detail="median latency 4.2s"),
            EvidenceSignal(source=EvidenceSource.SLOW_RETRIEVAL,
                           target_ref="command_center.retrieval", observed=4300, threshold=2000,
                           direction="increase", occurrences=4, detail="duplicate"),
            EvidenceSignal(source=EvidenceSource.JUDGE_FALSE_POSITIVE,
                           target_ref="defensive-coding-judge", observed=1, threshold=5,
                           direction="increase", occurrences=1, detail="one-off — noise"),
        ]
    drafts = ProposalGenerator(_registry()).propose(signals, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"propose [{mode}]:")
    for d in drafts:
        state = d.skipped or "DRAFTED"
        print(f"  {d.experiment_id:48s} {state}")
    return 0


def cmd_scan(args) -> int:
    """The daily self-improvement scan, runnable from any touchpoint (CLI/Kanban/Discord).
    Observer-only: drafts `Proposed` Backlog cards + one report, nothing else. Dry-run default."""
    from datetime import datetime, timezone

    from command_center.improvement.discovery import (
        DEFAULT_REPORT_PATH, ObserverCharter, ScanPipeline, SOURCE_REGISTRY, build_scanner,
    )
    reg = _registry()
    feeds: dict = {}
    if args.feeds:
        feeds = json.loads(Path(args.feeds).read_text(encoding="utf-8"))
    chosen = set(args.source) if args.source else None
    specs = []
    for spec in SOURCE_REGISTRY:
        if chosen is not None:
            if spec["name"] in chosen:
                specs.append(spec)
        elif spec["kind"] in ("code_health", "ledger") or spec["name"] in feeds:
            # default: the network-free sources, plus any feed source given records
            specs.append(spec)

    def fetch(spec: dict) -> list:
        return feeds.get(spec["name"], [])

    scanners = [build_scanner(s, reg, fetch) for s in specs]
    report_out = args.report_out or DEFAULT_REPORT_PATH
    pipe = ScanPipeline(ObserverCharter(reg, report_path=report_out),
                        method=args.method, max_cards=args.max_cards)
    now = datetime.now(timezone.utc)
    rep = pipe.run(scanners, date=now.date().isoformat(), now_iso=now.isoformat(),
                   apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    n_cards = len(rep.drafted_ids) if args.apply else len(rep.would_draft_ids)
    verb = "drafted" if args.apply else "would-draft"
    print(f"scan [{mode}] sources={rep.n_sources} failed={rep.n_failed} "
          f"findings={rep.n_findings} {verb}={n_cards} "
          f"suppressed_negative={rep.suppressed_negative} held={rep.held} capped={rep.n_capped}")
    for o in rep.outcomes:
        if not o.ok:
            print(f"  FAILED source {o.scanner}: {o.error}")
    if args.show_report:
        print("\n" + rep.report_markdown)
    elif args.apply:
        print(f"report -> {rep.report_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="improvement")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *, needs_id=False):
        p = sub.add_parser(name)
        p.set_defaults(func=fn)
        if needs_id:
            p.add_argument("--id", required=True)
        return p

    add("validate", cmd_validate)
    p = add("list", cmd_list); p.add_argument("--status", default=None)
    p = add("register", cmd_register, needs_id=True)
    p.add_argument("--mission", default=None); p.add_argument("--apply", action="store_true")
    p = add("baseline", cmd_baseline, needs_id=True)
    p.add_argument("--reps", type=int, default=3); p.add_argument("--apply", action="store_true")
    p = add("run", cmd_run, needs_id=True)
    p.add_argument("--reps", type=int, default=3); p.add_argument("--apply", action="store_true")
    p = add("verify", cmd_verify, needs_id=True)
    p.add_argument("--verifier", default="verifier:deterministic")
    p.add_argument("--apply", action="store_true")
    add("report", cmd_report, needs_id=True)
    p = add("request-promotion", cmd_request_promotion, needs_id=True)
    p.add_argument("--apply", action="store_true")
    p = add("canary", cmd_canary, needs_id=True)
    p.add_argument("--approver", default=""); p.add_argument("--apply", action="store_true")
    p = add("promote", cmd_promote, needs_id=True)
    p.add_argument("--approver", default=""); p.add_argument("--apply", action="store_true")
    p = add("rollback", cmd_rollback, needs_id=True)
    p.add_argument("--reason", default=""); p.add_argument("--apply", action="store_true")
    p = add("post-watch", cmd_post_watch, needs_id=True)
    p.add_argument("--checkpoint", default="1h"); p.add_argument("--regression", action="store_true")
    p.add_argument("--apply", action="store_true")
    add("attention", cmd_attention)
    p = add("board", cmd_board); p.add_argument("--apply", action="store_true")
    p = add("calibration", cmd_calibration); p.add_argument("--predictions", default="")
    p = add("search", cmd_search); p.add_argument("--query", required=True)
    p = add("propose", cmd_propose)
    p.add_argument("--signals", default=""); p.add_argument("--apply", action="store_true")
    p = add("scan", cmd_scan)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--method", default="wsjf", choices=["ice", "rice", "wsjf", "voi"])
    p.add_argument("--feeds", default="", help="JSON {source_name: [records...]} for feed sources")
    p.add_argument("--source", action="append", default=[], help="restrict to named source(s)")
    p.add_argument("--max-cards", type=int, default=20, dest="max_cards")
    p.add_argument("--report-out", default="", dest="report_out")
    p.add_argument("--show-report", action="store_true", dest="show_report")

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

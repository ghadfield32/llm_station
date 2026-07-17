from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from command_center.job_search.achievement_bank import ensure_bank
from command_center.job_search.application_memory import (
    append_note,
    create_prepared_application,
    load_application,
    mark_submitted,
)
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.board import (
    board_doctor,
    board_setup,
    board_snapshot,
    mark_submitted_on_board,
    note_activity_on_board,
    process_selected,
    publish_suggestions,
)
from command_center.job_search.cache_io import read_json_file, write_json_file_atomic
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.digest import write_digest
from command_center.job_search.followups import generate_followup
from command_center.job_search.live_sources import discover_live_postings
from command_center.job_search.profile_ingest import ingest_profile
from command_center.job_search.rejections import (
    REASON_CODES,
    record_rejection,
    rejection_report,
)
from command_center.job_search.resume_selection import select_resume
from command_center.job_search.retention import apply_retention, plan_retention
from command_center.job_search.scoring import normalize_job_from_text, score_job


def _root_and_bank():
    cfg = load_config()
    root = data_root(cfg)
    ensure_data_dirs(root)
    bank = ensure_bank(root / "profile" / "achievement_bank.yml")
    return cfg, root, bank


def _suggest_from_file(path: Path, *, write: bool) -> dict:
    cfg, root, bank = _root_and_bank()
    job = normalize_job_from_text(path.read_text(encoding="utf-8"), source_path=path)
    fit = score_job(job, bank, cfg)
    automation = classify_automation(job, cfg)
    selection = select_resume(job, bank, cfg)
    result = {
        "job": job.model_dump(mode="json"),
        "fit": fit.model_dump(mode="json"),
        "automation": automation.model_dump(mode="json"),
        "selection": selection.model_dump(mode="json"),
    }
    if write:
        out = root / "source_cache" / "suggestions" / f"{job.job_key}.json"
        write_json_file_atomic(out, result)
        result["cache_path"] = str(out)
    return result


def cmd_ingest_profile(args) -> int:
    report = ingest_profile()
    print(yaml.safe_dump(report, sort_keys=False))
    return 0


def cmd_suggest(args) -> int:
    if not args.from_file:
        raise SystemExit("suggest requires --from-file for the MVP")
    result = _suggest_from_file(Path(args.from_file), write=args.write)
    print(json.dumps(result, indent=2))
    return 0


def _load_suggestion(job_key: str) -> dict:
    cfg = load_config()
    root = data_root(cfg)
    path = root / "source_cache" / "suggestions" / f"{job_key}.json"
    if not path.exists():
        raise SystemExit(f"Unknown job_key {job_key!r}. Run suggest --from-file <file> --write first.")
    return read_json_file(path)


def cmd_generate_materials(args) -> int:
    if not args.selected_by_geoff:
        raise SystemExit(
            "generate-materials requires --selected-by-geoff. "
            "This is the CLI approval wall for the MVP."
        )
    cfg, root, bank = _root_and_bank()
    if args.from_file:
        suggestion = _suggest_from_file(Path(args.from_file), write=True)
    else:
        suggestion = _load_suggestion(args.job_key)
    from command_center.job_search.schemas import AutomationResult, CanonicalJob, FitResult, ResumeSelection

    job = CanonicalJob.model_validate(suggestion["job"])
    fit = FitResult.model_validate(suggestion["fit"])
    automation = AutomationResult.model_validate(suggestion["automation"])
    selection = ResumeSelection.model_validate(suggestion["selection"])
    if selection.rejected_claims:
        raise SystemExit("Claim validation failed:\n" + "\n".join(selection.rejected_claims))
    app_dir = create_prepared_application(
        job,
        fit,
        automation,
        selection,
        root=root,
        executor=args.executor,
    )
    print(str(app_dir))
    return 0


def cmd_mark_submitted(args) -> int:
    """Low-level submit marker. Runs the same packet validation gate as
    finalize — this command must not be a bypass around the review loop; use
    `finalize` for the full validate + email + evidence path."""
    from command_center.job_search.packet_validation import validate_packet

    _, root, bank = _root_and_bank()
    app_dir, record = load_application(args.application_id, root=root)
    validation = validate_packet(app_dir, record, bank)
    if not validation["ok"]:
        print(json.dumps({"status": "blocked", "validation": validation}, indent=2))
        return 1
    record = mark_submitted(args.application_id)
    mark_submitted_on_board(args.application_id)
    print(yaml.safe_dump(record.model_dump(mode="json"), sort_keys=False))
    return 0


def cmd_packet(args) -> int:
    """Show the full packet: record, validation, and (optionally) agent trace."""
    from command_center.job_search.agent_writer import read_trace
    from command_center.job_search.packet_validation import validate_packet

    _, root, bank = _root_and_bank()
    app_dir, record = load_application(args.application_id, root=root)
    out = {
        "application_id": args.application_id,
        "path": str(app_dir),
        "record": record.model_dump(mode="json"),
        "validation": validate_packet(app_dir, record, bank),
    }
    if args.trace:
        out["agent_trace"] = read_trace(app_dir)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["validation"]["ok"] else 1


def cmd_request_changes(args) -> int:
    """Record review notes and regenerate the materials with the agent writer."""
    from command_center.job_search.application_memory import (
        regenerate_materials,
        request_changes,
    )

    _, root, bank = _root_and_bank()
    request_changes(args.application_id, args.notes, root=root, source="cli")
    if args.no_regenerate:
        print(json.dumps({"status": "changes_requested",
                          "application_id": args.application_id}, indent=2))
        return 0
    app_dir, record = regenerate_materials(args.application_id, root=root, bank=bank)
    print(json.dumps({
        "status": "regenerated",
        "application_id": args.application_id,
        "revision": record.revision,
        "generation": record.generation,
        "path": str(app_dir),
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_finalize(args) -> int:
    """Validate, mark submitted, email the record, write submission evidence."""
    from command_center.job_search.finalize import FinalizeBlocked, finalize_application

    try:
        result = finalize_application(args.application_id)
    except FinalizeBlocked as exc:
        print(json.dumps({"status": "blocked",
                          "validation": exc.validation}, indent=2))
        return 1
    # This syncs only the legacy LOCAL board backend; the cockpit's internal
    # board is event-log driven and reconciles when the card is dragged (or
    # submitted) to Completed — that move is idempotent for applied records.
    board_sync = mark_submitted_on_board(args.application_id)
    print(json.dumps({
        "status": "finalized",
        **result,
        "board_sync": board_sync,
        "cockpit_hint": (
            "after submitting on the employer portal, drag the cockpit card to "
            "Completed (or press I submitted externally — record it) to "
            "sync the internal board; already-applied records complete "
            "idempotently without a second email"),
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_note(args) -> int:
    event = append_note(
        args.application_id,
        args.type,
        Path(args.file),
        furthers_process=args.furthers_process,
    )
    note_activity_on_board(
        args.application_id,
        args.type,
        furthers_process=args.furthers_process,
    )
    print(json.dumps(event, indent=2))
    return 0


def cmd_followup(args) -> int:
    app_dir, _ = load_application(args.application_id)
    text = generate_followup(app_dir)
    print(text)
    return 0


def cmd_retention(args) -> int:
    if args.apply:
        result = apply_retention()
    else:
        result = plan_retention()
    print(json.dumps(result, indent=2))
    return 0


def cmd_digest(args) -> int:
    path = write_digest()
    print(str(path))
    return 0


def cmd_reject(args) -> int:
    """Record why a job was rejected. Feeds `rejections-report`, which turns the
    pattern into concrete filter/scoring suggestions."""
    cfg = load_config()
    root = data_root(cfg)
    ensure_data_dirs(root)
    try:
        record = record_rejection(
            root,
            job_key=args.job_key,
            reason_code=args.reason,
            note=args.note,
            company=args.company,
            role_title=args.role_title,
            location=args.location,
            remote_type=args.remote_type,
            fit_score=args.fit_score,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(json.dumps(record, indent=2))
    return 0


def cmd_rejections_report(args) -> int:
    print(json.dumps(rejection_report(), indent=2))
    return 0


def cmd_validate_examples(args) -> int:
    examples = sorted(Path("docs/job_search/examples").glob("*.md"))
    if not examples:
        raise SystemExit("No examples found in docs/job_search/examples")
    outputs = []
    for example in examples:
        suggestion = _suggest_from_file(example, write=True)
        outputs.append(
            {
                "file": str(example),
                "job_key": suggestion["job"]["job_key"],
                "score": suggestion["fit"]["score"],
                "automation": suggestion["automation"]["value"],
                "variant": suggestion["selection"]["resume_variant"],
            }
        )
    print(json.dumps({"examples": outputs}, indent=2))
    return 0


def cmd_discover_live(args) -> int:
    sources = args.source or ["jobicy"]
    tags = args.tag or ["python", "machine-learning", "sql", "analytics"]
    industries = args.industry or []
    result = discover_live_postings(
        sources=sources,
        tags=tags,
        industries=industries,
        count=args.count,
        write=args.write,
    )
    suggestions = []
    if args.write:
        for path in result["posting_paths"]:
            suggestion = _suggest_from_file(Path(path), write=True)
            suggestions.append(
                {
                    "file": str(path),
                    "job_key": suggestion["job"]["job_key"],
                    "company": suggestion["job"]["company"],
                    "role_title": suggestion["job"]["role_title"],
                    "score": suggestion["fit"]["score"],
                    "automation": suggestion["automation"]["value"],
                    "variant": suggestion["selection"]["resume_variant"],
                }
            )
    result["suggestions_written"] = suggestions
    print(json.dumps(result, indent=2))
    return 0


def _print_board_result(result: dict) -> int:
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") == "blocked" else 0


def cmd_board_setup(args) -> int:
    return _print_board_result(
        board_setup(backend=args.backend, apply=args.apply)
    )


def cmd_board_snapshot(args) -> int:
    return _print_board_result(board_snapshot(backend=args.backend))


def cmd_board_doctor(args) -> int:
    return _print_board_result(board_doctor())


def cmd_publish_suggestions(args) -> int:
    # Operators publish to live boards: fixture example postings are excluded
    # unless explicitly included (they remain available for scoring tests).
    exclude = () if args.include_fixtures else ("fixture",)
    return _print_board_result(
        publish_suggestions(backend=args.backend, apply=args.apply,
                            exclude_sources=exclude)
    )


def cmd_process_selected(args) -> int:
    return _print_board_result(
        process_selected(backend=args.backend, apply=args.apply, executor=args.executor)
    )


REMOTIVE_DAILY_QUERY_BUDGET = 24


def _daily_discovery_terms(
    cfg, *, run_day: date | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return all configured terms plus a bounded, rotating Remotive slice.

    All watched companies stay in the source-of-truth list. When that list is
    larger than the polite daily request budget, the starting offset rotates by
    date so every company is searched over successive runs without producing an
    unbounded burst against the public API.
    """
    keywords = sorted({
        keyword.strip()
        for category in cfg.job_categories
        for keyword in category.keywords
        if keyword.strip()
    })
    company_targets = sorted({
        company.strip()
        for group in cfg.company_targets.model_dump(mode="python").values()
        for company in group
        if company.strip()
    })
    ordered = company_targets + [
        keyword for keyword in keywords if keyword not in set(company_targets)]
    if len(ordered) <= REMOTIVE_DAILY_QUERY_BUDGET:
        remotive_searches = ordered
    else:
        watched = company_targets or ordered
        day = run_day or date.today()
        offset = day.toordinal() % len(watched)
        rotated = watched[offset:] + watched[:offset]
        remotive_searches = rotated[:REMOTIVE_DAILY_QUERY_BUDGET]
        if len(remotive_searches) < REMOTIVE_DAILY_QUERY_BUDGET:
            remotive_searches.extend(
                value for value in ordered
                if value not in remotive_searches
            )
            remotive_searches = remotive_searches[:REMOTIVE_DAILY_QUERY_BUDGET]
    return keywords, company_targets, remotive_searches


def cmd_daily(args) -> int:
    """The full daily pipeline in one command — the same sequence the Airflow
    DAG runs, so a host scheduler (Windows Task / cron) can drive the job
    search WITHOUT an Airflow deployment: discover live postings across every
    configured job-category keyword, publish the balanced board, and (unless
    --no-process) prepare the Geoff-selected cards. Prints one JSON summary."""
    from command_center.job_search.config import load_config
    from command_center.job_search.live_sources import discover_live_postings

    cfg = load_config()
    # search terms derive from the ADJUSTABLE job categories (same source the
    # DAG uses) so editing a category's keywords changes what daily looks for
    keywords, company_targets, remotive_searches = _daily_discovery_terms(cfg)
    jobicy_tags = sorted({kw.lower().replace(" ", "-") for kw in keywords})
    summary: dict = {
        "operation": "daily",
        "keywords": keywords,
        "company_targets": company_targets,
        "remotive_searches_today": remotive_searches,
    }

    runs = [
        discover_live_postings(sources=["jobicy"], tags=jobicy_tags,
                               count=args.count, write=True),
        # Remotive accepts free-text searches, so watched company names are
        # first-class discovery queries alongside role keywords. Jobicy accepts
        # taxonomy tags rather than arbitrary company names; RemoteOK is a full
        # feed and is filtered/scored after retrieval.
        discover_live_postings(sources=["remotive"], tags=remotive_searches,
                               count=args.count, write=True),
        discover_live_postings(sources=["remoteok"], tags=[],
                               count=args.count, write=True),
    ]
    seen: set[str] = set()
    for run in runs:
        for path in run["posting_paths"]:
            if path in seen:
                continue
            seen.add(path)
            _suggest_from_file(Path(path), write=True)
    summary["postings_found"] = sum(r["postings_found"] for r in runs)
    summary["suggestions_written"] = len(seen)

    summary["publish"] = publish_suggestions(
        backend=args.backend, apply=args.apply, exclude_sources=("fixture",))
    if not args.no_process:
        summary["process"] = process_selected(
            backend=args.backend, apply=args.apply, executor=args.executor)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cc job-search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest-profile")
    p.set_defaults(func=cmd_ingest_profile)

    p = sub.add_parser("suggest")
    p.add_argument("--from-file", required=True)
    p.add_argument("--write", action="store_true", help="Persist suggestion cache for generate-materials")
    p.add_argument("--dry-run", action="store_true", help="Compatibility flag; no write unless --write")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("generate-materials")
    p.add_argument("job_key", nargs="?")
    p.add_argument("--from-file")
    p.add_argument("--selected-by-geoff", action="store_true")
    p.add_argument("--executor", choices=["auto", "claude", "codex"], default="auto")
    p.set_defaults(func=cmd_generate_materials)

    p = sub.add_parser("mark-submitted")
    p.add_argument("application_id")
    p.set_defaults(func=cmd_mark_submitted)

    p = sub.add_parser(
        "packet",
        help="Print the full application packet with validation (exit 1 if not ready).",
    )
    p.add_argument("application_id")
    p.add_argument("--trace", action="store_true",
                   help="Include the agent trace (prompts + model outputs)")
    p.set_defaults(func=cmd_packet)

    p = sub.add_parser(
        "request-changes",
        help="Record review notes and regenerate materials with the agent writer.",
    )
    p.add_argument("application_id")
    p.add_argument("--notes", required=True)
    p.add_argument("--no-regenerate", action="store_true",
                   help="Only record the notes; regenerate later")
    p.set_defaults(func=cmd_request_changes)

    p = sub.add_parser(
        "finalize",
        help="Validate + mark submitted + email the record + write evidence.",
    )
    p.add_argument("application_id")
    p.set_defaults(func=cmd_finalize)

    p = sub.add_parser("note")
    p.add_argument("application_id")
    p.add_argument("--type", required=True)
    p.add_argument("--file", required=True)
    p.add_argument(
        "--furthers-process",
        action="store_true",
        help="Explicitly mark this communication as advancing the hiring process",
    )
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("followup")
    p.add_argument("application_id")
    p.set_defaults(func=cmd_followup)

    p = sub.add_parser("retention")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_retention)

    p = sub.add_parser("digest")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("validate-examples")
    p.set_defaults(func=cmd_validate_examples)

    p = sub.add_parser(
        "reject",
        help="Record why a job was rejected (feeds rejections-report).",
    )
    p.add_argument("job_key")
    p.add_argument("--reason", required=True, choices=sorted(REASON_CODES))
    p.add_argument("--note")
    p.add_argument("--company")
    p.add_argument("--role-title")
    p.add_argument("--location")
    p.add_argument("--remote-type",
                   choices=["remote", "hybrid", "onsite", "unknown"])
    p.add_argument("--fit-score", type=int)
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser(
        "rejections-report",
        help="Aggregate rejections into filter/scoring change suggestions.",
    )
    p.set_defaults(func=cmd_rejections_report)

    p = sub.add_parser("discover-live")
    p.add_argument("--source", action="append", choices=["jobicy", "remoteok", "remotive"])
    p.add_argument("--tag", action="append", help="Jobicy tag to search; repeatable")
    p.add_argument(
        "--industry",
        action="append",
        help="Jobicy industrySlug to search; repeatable. Fetch valid slugs with ?get=industries.",
    )
    p.add_argument("--count", type=int, default=25)
    p.add_argument("--write", action="store_true", help="Persist live postings and suggestion caches")
    p.set_defaults(func=cmd_discover_live)

    p = sub.add_parser("board-setup")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["internal", "local"], default="internal")
    p.set_defaults(func=cmd_board_setup)

    p = sub.add_parser("board-snapshot")
    p.add_argument("--backend", choices=["internal", "local"], default="internal")
    p.set_defaults(func=cmd_board_snapshot)

    p = sub.add_parser(
        "board-doctor",
        help="Health-check the live board and print the one-time group-by-Status step.",
    )
    p.set_defaults(func=cmd_board_doctor)

    p = sub.add_parser("publish-suggestions")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["internal", "local"], default="internal")
    p.add_argument("--include-fixtures", action="store_true",
                   help="also publish fixture-sourced example postings (test/demo only)")
    p.set_defaults(func=cmd_publish_suggestions)

    p = sub.add_parser("process-selected")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["internal", "local"], default="internal")
    p.add_argument("--executor", choices=["auto", "claude", "codex"], default="auto")
    p.set_defaults(func=cmd_process_selected)

    p = sub.add_parser(
        "daily",
        help="Full daily pipeline (discover -> publish -> process) for a host "
             "scheduler; no Airflow needed. Use --apply to write.")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["internal", "local"], default="internal")
    p.add_argument("--executor", choices=["auto", "claude", "codex"], default="codex")
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--no-process", action="store_true",
                   help="discover + publish only; leave selection/prep to Geoff")
    p.set_defaults(func=cmd_daily)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

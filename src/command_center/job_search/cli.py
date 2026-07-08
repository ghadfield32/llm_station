from __future__ import annotations

import argparse
import json
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
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.digest import write_digest
from command_center.job_search.followups import generate_followup
from command_center.job_search.profile_ingest import ingest_profile
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
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
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
    return json.loads(path.read_text(encoding="utf-8"))


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
    record = mark_submitted(args.application_id)
    mark_submitted_on_board(args.application_id)
    print(yaml.safe_dump(record.model_dump(mode="json"), sort_keys=False))
    return 0


def cmd_note(args) -> int:
    event = append_note(args.application_id, args.type, Path(args.file))
    note_activity_on_board(args.application_id, args.type)
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
    return _print_board_result(
        publish_suggestions(backend=args.backend, apply=args.apply)
    )


def cmd_process_selected(args) -> int:
    return _print_board_result(
        process_selected(backend=args.backend, apply=args.apply, executor=args.executor)
    )


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

    p = sub.add_parser("note")
    p.add_argument("application_id")
    p.add_argument("--type", required=True)
    p.add_argument("--file", required=True)
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

    p = sub.add_parser("board-setup")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["appflowy", "local"], default="appflowy")
    p.set_defaults(func=cmd_board_setup)

    p = sub.add_parser("board-snapshot")
    p.add_argument("--backend", choices=["appflowy", "local"], default="appflowy")
    p.set_defaults(func=cmd_board_snapshot)

    p = sub.add_parser(
        "board-doctor",
        help="Health-check the live board and print the one-time group-by-Status step.",
    )
    p.set_defaults(func=cmd_board_doctor)

    p = sub.add_parser("publish-suggestions")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["appflowy", "local"], default="appflowy")
    p.set_defaults(func=cmd_publish_suggestions)

    p = sub.add_parser("process-selected")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backend", choices=["appflowy", "local"], default="appflowy")
    p.add_argument("--executor", choices=["auto", "claude", "codex"], default="auto")
    p.set_defaults(func=cmd_process_selected)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

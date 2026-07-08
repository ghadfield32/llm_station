# Claude Code / Codex Fallback

> **Archived — merged into [job_search/READINESS_FAQ.md](../job_search/READINESS_FAQ.md)**
> ("What if Claude Code is unavailable?"), which covers this with a
> live-validated example.

The repo already declares executor fallback in `configs/models.yaml`:

```text
priority 1: claude-code
priority 2: codex-cli
```

The job-search workflow is CLI-first, so either executor can run the same
commands:

```powershell
uv run cc job-search ingest-profile
uv run cc job-search validate-examples
uv run cc job-search suggest --from-file <posting.md> --write
uv run cc job-search generate-materials <job_key> --selected-by-geoff --executor codex
```

Executor choice must not change safety behavior. Codex fallback keeps the same
manual blockers, claim validation, and no-submit MVP rules.

<!-- Keep diffs minimal and in-scope. See CONTRIBUTING.md. -->

## What & why

<!-- One or two lines: what changed and the problem it solves. -->

## Checklist

- [ ] Edited `configs/*.yaml` (not `generated/`); ran `make validate`
- [ ] `make mission-dryrun` passes (if gates/judges/models touched)
- [ ] `make lint` and `make test` pass
- [ ] `python -m command_center.channels --dry-run` works (if channels touched)
- [ ] New deps pinned in `pyproject.toml` and `uv sync` re-locked
- [ ] No secrets added to tracked files; staged explicit paths (no `git add -A`)
- [ ] No defensive coding / hardcoded fallbacks; errors surfaced, not swallowed

## Blast radius

<!-- Run `make impact` and paste the affected list, or note "none declared". -->

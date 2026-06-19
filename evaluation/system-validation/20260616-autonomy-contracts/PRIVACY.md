# Privacy

- `.env` was not read.
- `cc github-app-verify`, when run separately, may read GitHub env key presence and write a redacted artifact into this package.
- `cc branch-protection-verify`, when run separately, may read owner/admin observer token presence and write redacted branch-protection evidence.
- `cc branch-mission`, when run separately, creates a temporary local worktree, writes one docs-only smoke file, runs configured validation commands with secret env names removed, and retains command output hashes and line counts only.
- `cc pr-check-verify`, when run separately with `--apply`, uses a short-lived GitHub App installation token in memory to create one feature branch and one draft PR, then stores only PR/check metadata.
- Raw chat transcripts were not read.
- Screenshots were not captured.
- Model prompts and outputs were not retained.
- `cc agent-validation`, when run separately, stores synthetic scenario statuses only; it does not retain prompts or model text.
- `cc desktop-target-verify`, when run separately, reads the board snapshot and stores target identity/status evidence only.
- `cc desktop-adapter`, when run separately, stores manifest readiness evidence only and performs no desktop actions.
- The package stores config-derived summaries, git metadata, blockers, and paths only.

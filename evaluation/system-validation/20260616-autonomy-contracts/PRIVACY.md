# Privacy

- `.env` was not read.
- `cc github-app-verify`, when run separately, may read GitHub env key presence and write a redacted artifact into this package.
- `cc branch-protection-verify`, when run separately, may read owner/admin observer token presence and write redacted branch-protection evidence.
- Raw chat transcripts were not read.
- Screenshots were not captured.
- Model prompts and outputs were not retained.
- `cc agent-validation`, when run separately, stores synthetic scenario statuses only; it does not retain prompts or model text.
- `cc desktop-target-verify`, when run separately, reads the board snapshot and stores target identity/status evidence only.
- `cc desktop-adapter`, when run separately, stores manifest readiness evidence only and performs no desktop actions.
- The package stores config-derived summaries, git metadata, blockers, and paths only.

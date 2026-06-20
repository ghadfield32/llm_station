# Commands

- `git rev-parse --short HEAD`
- `git status --short`
- `AutonomyConfig.model_validate(configs/autonomy.yaml)`
- Optional: `cc github-app-verify --output <package>/github-app-verify.json`
- Optional: `cc branch-protection-verify --output <package>/branch-protection-verify.json`
- Optional: `cc branch-mission --output <package>/branch-mission.json`
- Optional: `cc pr-check-verify --apply --output <package>/pr-check-loop.json`
- Optional: `cc agent-validation --output <package>/agent-validation.json`
- Optional: `cc desktop-target-verify --output <package>/desktop-target-verify.json`
- Optional: `cc desktop-adapter --output <package>/desktop-adapter-readiness.json`
- Optional: `cc desktop-noop-canary --output <package>/desktop-noop-canary.json`
- Optional: `cc desktop-timing-derive --target-id <target> --input <canary.json> --required-samples <evidence-derived-count> --required-samples-source <artifact> --output <package>/desktop-timing-candidates.json`

No live services, desktop actions, board writes, repo mutations, model calls, or notifications were executed by this runner; optional artifacts are produced by their own observer commands.

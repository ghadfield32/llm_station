# Forecasts

## evidence-package-write

- Source authority: `configs/autonomy.yaml` plus git metadata.
- Expected state before: no system-validation package for this run id.
- Expected state after: local markdown evidence package exists.
- Expected events: none emitted to Ledger; file writes only.
- Expected no change: no AppFlowy, desktop, repo, model, provider, or notification action.
- Privacy boundary: no secrets, raw transcripts, screenshots, or raw model artifacts.
- Rollback: delete this run directory if the local evidence package is unwanted.
- Observed result: package written by this command.

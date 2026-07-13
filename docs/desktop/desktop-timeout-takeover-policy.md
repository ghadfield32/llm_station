# Desktop Timeout And Takeover Policy

This policy declares the safety envelope for the `appflowy_browser_staging`
desktop target. It does not enable live desktop actions.

## Declared Policy

- Target: `appflowy_browser_staging`
- TTL: not configured until measured evidence exists.
- TTL source: pending no-op canary telemetry plus target-rights evidence.
- Per-action timeout: not configured until measured evidence exists.
- Per-action timeout source: pending no-op canary telemetry.
- Takeover hotkey: declared in `configs/autonomy.yaml`; verifier artifacts retain only
  whether a takeover hotkey exists, not the key sequence.
- Screenshot artifact policy: `redacted_hashes_and_refs_only`

## Evidence Boundary

The current evidence is policy declaration and manifest validation only. No TTL
or per-action timeout value is configured in production because no live no-op
canary timing evidence exists yet. The target remains disabled until telemetry
derives those values and a new PR records the source evidence.

## Measurement Gate

Before `appflowy_browser_staging` can be enabled, the next PR must add:

- `ttl_minutes` with a source artifact from target-rights evidence and no-op
  canary observations.
- `action_timeout_seconds` with a source artifact from observed no-op action
  timings.
- Canary evidence proving no raw screenshots, clipboard reads, secrets, file
  deletion, or system-setting writes occurred.

## Hard Stop Rules

- No clipboard reads.
- No password-field reads.
- No system settings changes.
- No file deletion.
- No raw screenshot retention.
- No live desktop action without target-state evidence and human takeover.

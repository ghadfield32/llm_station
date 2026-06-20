# Desktop No-Op Canary Telemetry

This document defines the current desktop/browser canary telemetry state for
`appflowy_browser_staging`.

## Current State

- Mode: read-only.
- Target source: `configs/autonomy.yaml`.
- Evidence command: `uv run cc desktop-noop-canary`.
- Evidence artifact:
  `evaluation/system-validation/20260616-autonomy-contracts/desktop-noop-canary.json`.
- Timing candidate command: `uv run cc desktop-timing-derive`.
- Timing candidate artifact:
  `evaluation/system-validation/20260616-autonomy-contracts/desktop-timing-candidates.json`.

## Safety Boundary

- No desktop live actions are enabled.
- No AppFlowy mutation is performed.
- No card is moved.
- No form is submitted.
- No clipboard values are read.
- No password fields are read.
- No screenshots are captured.
- No raw page or card content is retained.
- The human-takeover policy reference is retained, but the literal hotkey is
  not stored in canary evidence.
- No TTL or action-timeout production control is written.

## Measurement Boundary

The first read-only canary sample proves instrumentation and target visibility.
It is not enough to derive production `ttl_minutes` or
`action_timeout_seconds`.

Production timing candidate derivation remains blocked until an
operator-reviewed sample plan declares:

- the required sample count;
- the source evidence for that count;
- the exact canary type to run;
- whether samples must cover different UI states;
- the acceptance rule for rejected or blocked samples.

Until that sample plan exists, `desktop-timing-derive` must report
`sample_plan_missing` and `insufficient_noop_canary_telemetry`.

## Next Ordered Work

1. Declare the desktop timing sample plan.
2. Run additional read-only/no-op canary samples from that plan.
3. Derive provisional timing candidates from measured evidence only.
4. Keep desktop live actions disabled until candidates are reviewed, accepted,
   and wired through the adapter gate.

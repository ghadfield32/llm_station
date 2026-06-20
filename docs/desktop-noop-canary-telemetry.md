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

The first merged read-only canary sample proves instrumentation and target
visibility. The declared timing sample plan now adds two post-merge read-only
samples:

- `evaluation/system-validation/20260616-autonomy-contracts/desktop-noop-canary-samples/post-pr10-sample-001.json`
- `evaluation/system-validation/20260616-autonomy-contracts/desktop-noop-canary-samples/post-pr10-sample-002.json`

The required sample count is derived from
`configs/autonomy.yaml:desktop_timing_sample_plans[appflowy_browser_staging].required_evidence_refs`.
It is not a code default or a production threshold.

`desktop-timing-derive` now proposes provisional timing candidates from the
maximum observed read-only no-op timings with no multiplier. It still does not
write production `ttl_minutes` or `action_timeout_seconds`, and it does not
enable the desktop target.

## Next Ordered Work

1. Review the provisional timing candidates against the sample evidence.
2. Keep desktop live actions disabled until candidates are reviewed, accepted,
   and wired through the adapter gate.
3. Derive the GUI loop-breaker policy from event history before autonomous GUI
   retries are allowed.

# Threat, privacy, and authority review - Mission 1

## Change class

Native configuration/schema refactor of Judge Gate classify routing.

No external candidate, package, MCP server, daemon, model provider, or service
is part of this mission.

## Authority boundaries

Must remain true:

- LiteLLM remains the only model gateway.
- Ledger remains the only mission/evidence/approval runtime state authority.
- Judge Gate remains the classify/review service.
- GitHub remains the final merge wall.
- Growth OS/AppFlowy remains the human work surface.
- `configs/*.yaml` plus schemas remain editable truth.
- Generated files remain disposable.

## Expected filesystem changes

Expected implementation paths, not yet changed:

- one or more config/schema files to represent route ownership;
- `services/judge_gate/app.py` to consume validated route data;
- focused tests for route fixtures and failure fixtures;
- docs under `docs/MASTER.md` and this evidence directory.

No expected writes:

- `.env`;
- browser profile;
- shell profile;
- Claude/Codex global config;
- MCP config;
- production data;
- hidden eval files.

## Expected process, port, and network changes

None.

Mission 1 must not add a daemon, port, network destination, package install, or
model call path.

## Data handled

Allowed evidence:

- config paths and hashes;
- route aliases;
- risk-tier names;
- command names;
- PASS/FAIL command summaries;
- redacted error messages if validation fails.

Forbidden evidence:

- raw `.env` content;
- provider tokens;
- browser cookies;
- raw chat transcripts;
- hidden eval answers;
- secret-bearing diffs;
- full private model outputs that may contain user content.

## Threats and controls

| Threat | Control |
| --- | --- |
| Missing route silently falls back | Validation/startup must fail. |
| Unknown alias reaches LiteLLM | Cross-reference validation must reject it. |
| Provider route sneaks into model roles | Existing forbidden-provider validation must remain PASS. |
| L3/L4 auto approval regression | Existing gate validation and dry-run must remain PASS. |
| Split-brain route ownership | One documented config owner; `MASTER.md` updated. |
| Route change without evidence | Experiment fixtures and command outputs required before promotion. |
| Secret leakage in logs/artifacts | Store only bounded metadata and redacted errors. |

## Security disposition

Proceed to isolated implementation only after this review and the experiment
plan exist. Do not expand scope to Ledger artifacts or failure taxonomy in
Mission 1.

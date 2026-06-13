# Threat model — abtop (Stage 4)

Seam: observability (read-only). Position of trust: reads Claude/Codex
session transcripts under `~/.claude/` and `~/.codex/` — these contain
conversation content, so abtop sees everything the sessions saw.

| Threat | Assessment | Mitigation in this experiment |
| --- | --- | --- |
| Transcript content exposure | abtop reads full JSONL transcripts locally; display + JSON snapshot only | Local TUI/one-shot use; output stays in evaluation/raw/; no piping off-machine |
| Telemetry / phone-home | Collectors inspected upstream: no HTTP clients in rate-limit/codex modules; full tree not audited (UC) | One-shot `--json` run; treat "no network" as a criterion to characterize, not assume |
| Global modification | `--setup` edits `~/.claude/settings.json` (statusLine hook) + writes scripts; NO teardown exists | **`--setup` is forbidden in this experiment** |
| Supply chain (binary) | Pre-built release binary v0.4.8 from GitHub (cargo-dist); no cargo toolchain locally | Pin exact release URL + record SHA-256 of downloaded binary in install manifest; binary kept in evaluation dir, never on PATH |
| Indirect API call | Optional session-summary feature shells to `claude --print` (user auth) | Feature not used |
| Background persistence | None by default (foreground TUI / one-shot) | Verify no processes remain after exit |
| False reads (wrong session attribution) | Open issue #135 (missed sessions); context % is an estimate | Detection accuracy is a measured criterion, not assumed |

Scans run: binary provenance = GitHub release asset of the verified repo,
hash recorded. No installer script executed (direct asset download, not the
`irm | iex` one-liner).

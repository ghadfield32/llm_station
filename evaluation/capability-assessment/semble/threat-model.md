# Threat model — semble (Stage 4)

Seam: repository retrieval (optional path). Position of trust: reads the
entire working tree including any file not in `.gitignore`.

| Threat | Assessment | Mitigation in this experiment |
| --- | --- | --- |
| Secret exposure via index | **Primary risk.** `.env` is gitignored (respected per upstream docs) but must be proven, not assumed | Explicit benchmark check: query for key-shaped strings; S2 rubric criterion |
| Source-code exfiltration / telemetry | Local CPU model; no keys; telemetry UNKNOWN upstream | Run index+query offline-observed; first-run model download is the only expected network event, recorded |
| Supply chain (PyPI) | `semble==0.3.4` pinned; deps include tree-sitter native wheels | uv install into project venv only (not tool-global); `uv pip list` recorded in install manifest |
| Stale index poisoning | Index cached in %LOCALAPPDATA%; agents could act on stale results | Stale-index test in benchmark plan (edit file, re-query) |
| Agent-config modification | `semble install` edits MCP config/AGENTS.md | NOT run; CLI only. MCP registration is a separate adoption decision |
| Concurrent-write corruption | v0.3.4 fixed "concurrent write corruption"; multiple agent sessions run here | Single-process use in experiment; flag for PILOT monitoring |
| Insecure deserialization | Index format unaudited | Index treated as disposable cache; never committed |
| Prompt injection via retrieved content | Same exposure as ripgrep/Read today — not new authority | No change to judge pipeline; retrieved text still passes normal gates |

Scans run: repo-native `check_forbidden_providers.py` unaffected (no keys
added). Dependency audit: deps recorded in install-manifest.json; no install
scripts beyond standard wheels (PyPI wheel install, no curl|bash path used).

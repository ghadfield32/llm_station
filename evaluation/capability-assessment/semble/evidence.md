# Evidence — semble (Stage 1)

Collected 2026-06-12 by Investigator (independent context) from authoritative
sources: github.com/MinishLab/semble (README, pyproject, LICENSE, CI, issues,
releases), pypi.org/project/semble, minish.ai docs. Labels: VUF / UC / LR /
INF / UNK as in the loop.

## Identity & maturity

- VUF: `github.com/MinishLab/semble` exists, public, active. "Fast and
  Accurate Code Search for Agents. Uses ~98% fewer tokens than grep+read."
- VUF: PyPI `semble` **v0.3.4** (2026-06-12 — released today), MIT (LICENSE
  file: "Copyright (c) 2026 Thomas van Dongen"), Python >=3.10.
- VUF: ~5,112 stars, 219 forks, 110 commits, 6 contributors (2 core), repo
  created 2026-04-06 (~2 months old). CI on Ubuntu/macOS/**Windows**,
  Python 3.10–3.14, pytest + Codecov.
- INF: high stars but effectively a 2-person, 2-month-old project.

## Install & dependencies

- VUF: `uv tool install semble` (+ interactive `semble install` for agent
  integration); pip works. Deps: model2vec, vicinity, numpy, bm25s, pathspec,
  tree-sitter (pinned <0.26), orjson, questionary; `[mcp]` extra adds mcp +
  watchfiles. Console script `semble`.
- VUF: MCP server is **stdio** (no port); registers with Claude Code via
  `claude mcp add semble -s user -- uvx --from "semble[mcp]" semble`.

## Runtime & writes

- VUF: "runs on CPU with no API keys, GPU, or external services" (README).
- INF (IMPORTANT): default embedding model `minishlab/potion-code-16M` is a
  HF Hub identifier with no bundled weights visible → **one-time network
  download at first run is likely**, despite the marketing line. Acceptable
  under NETWORK_POLICY (package registry-equivalent fetch) but recorded.
- VUF: index cache on Windows: `%LOCALAPPDATA%\semble\Cache\` (overridable
  via `SEMBLE_CACHE_LOCATION`). Respects `.gitignore` + `.sembleignore`.
- VUF (CAVEAT): **`semble install` modifies agent config files** (MCP
  registration, AGENTS.md edits, optional sub-agent). `semble uninstall`
  exists to undo it. **Mitigation for this evaluation: do not run
  `semble install`; use the CLI directly.**
- UNK: telemetry — no evidence either way.

## Performance claims (ALL UPSTREAM_CLAIM_NOT_YET_REPRODUCED)

"~98% fewer tokens than grep+read" · "~250 ms average repo indexing" ·
"~1.5 ms queries" · "NDCG@10 0.854" · "94% recall at 2k tokens" ·
"218x faster indexing than CodeRankEmbed". A `benchmarks/` directory exists
upstream (methodology reproducible).

## Issues & stability

- VUF: 6 open issues, none open bugs; v0.3.4 notes fixed "concurrent write
  corruption" — concurrency bugs existed pre-0.3.4 (relevant: multiple
  Claude/Codex sessions run here concurrently).

## Rollback

- VUF/INF: `uv pip uninstall semble` (or `uv tool uninstall semble`), delete
  `%LOCALAPPDATA%\semble\Cache\`; `semble uninstall` only needed if
  `semble install` was run (it won't be); possible HF model copy in the HF
  cache (UNK which cache it uses).

## Stage-2 relevance summary

MIT, pinnable (`semble==0.3.4`), no keys, CPU, Windows-tested, isolated cache,
removable. Two recorded caveats: first-run model download; agent-config
modification path exists but is opt-in and excluded from the experiment.

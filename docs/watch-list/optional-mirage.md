# Optional / watch-list: Mirage VFS

**What it is:** Mirage (strukto.ai, Apache-2.0) is a virtual filesystem for AI agents. It
mounts services — S3, GDrive, Slack, GitHub, Redis, Postgres, SSH, Gmail — side-by-side as
one directory tree, so an agent reaches every backend through plain bash (`cat /s3/x.csv`,
`grep alert /slack/general/*.json`) with no per-service MCP server. Python + TypeScript SDKs,
drops into OpenHands/Claude Code/Codex, ships a RAM/Redis two-layer cache. It's an elegant
alternative to wiring N MCP servers through LiteLLM's MCP gateway.

**Why it's NOT in the command center (yet):** as of June 2026 it is **v0.0.1, first public
release May 6 2026, ~59 GitHub stars, 4 commits, 3 contributors.** (Blog posts claiming
thousands of stars contradict the actual repo.) In the command center it would sit in the
**credential-handling, always-on data path** — the highest-trust position in the whole
system. A three-week-old v0.0.1 there is exactly the dependency that strands you when it
breaks while you're away. That violates the "reliable, hard to break, not overengineered"
priorities, so it stays out of the core for now.

**Where it could genuinely help, safely:** read-only data plumbing for the sports-analytics
work — mounting S3/Parquet + Postgres + Drive so an agent can `cat`/`grep`/`jq` across NBA
data sources in one tree without bespoke connectors. Contained, not credential-critical,
not always-on.

**The safe way to try it (Phase 4 experiment, not a component):**
- On the 4090 only, in a throwaway branch.
- Mount **read-only data sources only** (S3/Parquet, Postgres read replica, a Drive folder).
- **No** GitHub write, no secrets, no Slack/Gmail write mounts.
- Compare against just using the existing tools for the same task. Keep it only if it
  clearly wins.

**Re-evaluate for the core if:** it reaches a real v0.1+ with sustained traction and a
track record, AND it demonstrably simplifies the MCP path rather than adding a layer.
Until then it's a watch-list item, reviewed at the same cadence as the model registry.

"""Unified runtime Usage / Limits / Availability / Budget subsystem.

One shared layer across every chat model AND coding agent — NOT a second
control plane. It keeps four concepts rigorously distinct (see schemas.py):

  Usage           — tokens/calls/sessions/duration/tool-calls/cache/cost we observed
  Provider limits — provider-REPORTED quota windows, remaining, reset times
  Availability    — installed/authed/healthy/busy/limited/exhausted/unavailable
  Internal budget — OUR own per-user/project/agent/mission spend rules

Load-bearing invariants (enforced by service.py, proven by tests):
  * Provider quota is NEVER overwritten by an estimate (source priority).
  * Unknown stays unknown; stale is visibly stale — never coerced to 0.
  * Every row stores its source and observation time.
  * Multiple provider buckets stay separate (never flattened to one %).
  * Ingestion is idempotent (source_hash); alerts are deduplicated.
  * Credentials / raw provider responses / raw ccusage logs NEVER enter the
    Ledger — only normalized fields, traceable to session/user/mission/repo.

Phase 1 (this branch) is the storage + service foundation plus a
deterministic FakeCollector. Real provider collectors (Codex app-server,
Claude RateLimitEvent, OpenRouter key endpoint, LiteLLM spend, Ollama
health, ccusage reconciler) are later phases — see collectors/.
"""

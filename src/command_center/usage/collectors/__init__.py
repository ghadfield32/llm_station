"""Usage collectors — each translates ONE source into the canonical schemas.

Phase 1 ships only `fake` (deterministic, no I/O) so the whole
store→service→roll-up→alert pipeline is testable without any provider. The
real collectors are later phases and MUST each: translate their vendor
source into the canonical schemas, report failures as CollectorResult
warnings (never raise for an expected provider condition), and never retain
raw responses or credentials:

  codex_app_server  — account/read, account/rateLimits/read, account/usage/read
  claude_agent      — RateLimitEvent (five_hour / seven_day_* / overage buckets)
  claude_api_limits — Claude API limit headers
  openrouter        — the key-info endpoint (authoritative remaining credit)
  litellm           — /spend/logs (provider_derived)
  ollama            — local health/capacity (availability only, NO fabricated quota)
  local_frontier    — local frontier engines
  ccusage           — reconciler ONLY (historical; never authoritative for remaining quota)
"""

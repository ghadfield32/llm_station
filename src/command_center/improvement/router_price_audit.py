"""Price-freshness audit for the frontier-router lane.

Public provider prices drift, so the repo dates each one (`price_observed_at`) and audits
staleness instead of trusting a frozen number. This NEVER rewrites a price — a stale entry is
surfaced for a human (the contract refuses `auto_update`). The daily scan can call this and
emit a finding when `stale_action` is `warn_in_scan`; a `fail` policy makes it a hard gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from ..schemas import FrontierRouterProvidersConfig


@dataclass(frozen=True)
class StalePrice:
    provider: str
    model: str
    price_observed_at: str
    age_days: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PriceAuditReport:
    today: str
    max_age_days: int
    stale_action: str
    n_candidates: int
    n_dated: int
    stale: list[StalePrice]
    undated: list[str]          # "provider:model" of candidates missing price_observed_at
    verdict: str                # fresh | stale | undated

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stale"] = [s.to_dict() for s in self.stale]
        return d


def audit_prices(cfg: FrontierRouterProvidersConfig, *, today: str) -> PriceAuditReport:
    """Compare every candidate's `price_observed_at` against `price_freshness.max_age_days`.
    `today` is passed in (ISO date) so the audit is deterministic and unit-testable. Raises on
    a malformed date rather than silently treating it as fresh."""
    today_d = date.fromisoformat(today)
    policy = cfg.price_freshness
    stale: list[StalePrice] = []
    undated: list[str] = []
    n_candidates = 0
    n_dated = 0
    for model_id, spec in cfg.models.items():
        for cand in spec.router_candidates:
            n_candidates += 1
            if not cand.price_observed_at:
                undated.append(f"{cand.provider}:{model_id}")
                continue
            n_dated += 1
            age = (today_d - date.fromisoformat(cand.price_observed_at)).days
            if age > policy.max_age_days:
                stale.append(StalePrice(
                    provider=cand.provider, model=model_id,
                    price_observed_at=cand.price_observed_at, age_days=age))
    verdict = "stale" if stale else ("undated" if undated else "fresh")
    return PriceAuditReport(
        today=today, max_age_days=policy.max_age_days, stale_action=policy.stale_action,
        n_candidates=n_candidates, n_dated=n_dated, stale=stale, undated=undated,
        verdict=verdict)

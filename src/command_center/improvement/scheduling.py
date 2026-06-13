"""
Phase 4 — smarter experiment selection (scheduling + ranking).

Human attention and compute are scarce; "which Proposed experiment to run / surface next"
is an explore/exploit problem. Thompson sampling and UCB1 allocate that scarce capacity to
minimize regret, and a meta-ranker scores proposals by what historically *verified* in the
Ledger.

Hard wall: this layer only ORDERS experiments that are already in the `Proposed` state, and
its output is advisory (it feeds the scheduler / morning brief). It cannot execute an
unapproved experiment, change a verdict, or promote — autonomy grows by proposing better,
never by removing the human gate. Deterministic given a seed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ---- Thompson sampling (Beta-Bernoulli) -------------------------------------

@dataclass
class ThompsonBandit:
    """Beta-Bernoulli Thompson sampling. Each arm keeps a Beta(α,β) posterior over its
    success probability; select() samples from each and picks the argmax."""
    arms: list[str]
    seed: int = 12345
    alpha: dict[str, float] = field(default_factory=dict)
    beta: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if len(self.arms) < 2:
            raise ValueError("a bandit needs >= 2 arms")
        self._rng = random.Random(self.seed)
        for a in self.arms:
            self.alpha.setdefault(a, 1.0)   # uniform prior Beta(1,1)
            self.beta.setdefault(a, 1.0)

    def select(self) -> str:
        samples = {a: self._rng.betavariate(self.alpha[a], self.beta[a]) for a in self.arms}
        return max(samples, key=lambda a: samples[a])

    def update(self, arm: str, reward: float) -> None:
        if arm not in self.alpha:
            raise KeyError(f"unknown arm {arm!r}")
        if not 0.0 <= reward <= 1.0:
            raise ValueError("reward must be in [0,1]")
        self.alpha[arm] += reward
        self.beta[arm] += 1.0 - reward

    def posterior_mean(self, arm: str) -> float:
        return self.alpha[arm] / (self.alpha[arm] + self.beta[arm])

    def ranking(self) -> list[str]:
        """Arms ordered by posterior mean (the exploit ordering for the morning brief)."""
        return sorted(self.arms, key=self.posterior_mean, reverse=True)


# ---- UCB1 -------------------------------------------------------------------

@dataclass
class UCB1:
    """Deterministic upper-confidence-bound bandit (no randomness)."""
    arms: list[str]
    counts: dict[str, int] = field(default_factory=dict)
    sums: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if len(self.arms) < 2:
            raise ValueError("a bandit needs >= 2 arms")
        for a in self.arms:
            self.counts.setdefault(a, 0)
            self.sums.setdefault(a, 0.0)

    def select(self) -> str:
        total = sum(self.counts.values())
        for a in self.arms:
            if self.counts[a] == 0:
                return a                     # try each arm once first

        def ucb(a):
            mean = self.sums[a] / self.counts[a]
            return mean + math.sqrt(2 * math.log(total) / self.counts[a])
        return max(self.arms, key=ucb)

    def update(self, arm: str, reward: float) -> None:
        self.counts[arm] += 1
        self.sums[arm] += reward


def cumulative_regret(rewards: list[float], optimal_mean: float) -> list[float]:
    """Running cumulative regret vs always playing the optimal arm."""
    out, total = [], 0.0
    for r in rewards:
        total += optimal_mean - r
        out.append(total)
    return out


# ---- meta-ranker over Ledger outcomes ---------------------------------------

@dataclass
class MetaRanker:
    """Learning-to-rank-lite: estimate P(verify | feature value) per feature from historical
    (features, success) outcomes with Laplace smoothing, then score a proposal by the mean of
    its features' success rates. Advisory priority only — it never gates or promotes."""
    history: list[tuple[dict, bool]] = field(default_factory=list)

    def _rates(self) -> dict[tuple[str, str], tuple[int, int]]:
        agg: dict[tuple[str, str], list[int]] = {}
        for feats, success in self.history:
            for k, v in feats.items():
                cell = agg.setdefault((k, str(v)), [0, 0])
                cell[0] += 1 if success else 0
                cell[1] += 1
        return {k: (s, n) for k, (s, n) in agg.items()}

    def score(self, features: dict) -> float:
        rates = self._rates()
        vals = []
        for k, v in features.items():
            s, n = rates.get((k, str(v)), (0, 0))
            vals.append((s + 1) / (n + 2))   # Laplace-smoothed success rate
        return sum(vals) / len(vals) if vals else 0.5

    def rank(self, proposals: list[dict]) -> list[tuple[dict, float]]:
        scored = [(p, self.score(p.get("features", p))) for p in proposals]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored


# ---- scheduler over Proposed experiments (advisory) -------------------------

@dataclass
class ScheduleDecision:
    ordering: list[str]            # experiment ids, best-first (run/surface order)
    rationale: dict[str, float]    # per-id score

    def to_dict(self) -> dict:
        return {"ordering": self.ordering, "rationale": self.rationale}


def recommend_order(proposed: list[dict], history: list[tuple[dict, bool]] | None = None
                    ) -> ScheduleDecision:
    """Order Proposed experiments by expected value using the meta-ranker. ``proposed`` items
    are {"experiment_id":..., "features": {...}}. Pure advisory output for the human brief /
    scheduler — it does not run or promote anything."""
    ranker = MetaRanker(history or [])
    scored = [(p["experiment_id"], ranker.score(p.get("features", {}))) for p in proposed]
    scored.sort(key=lambda t: t[1], reverse=True)
    return ScheduleDecision(ordering=[eid for eid, _ in scored],
                            rationale={eid: round(s, 4) for eid, s in scored})

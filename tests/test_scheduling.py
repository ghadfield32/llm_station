"""Phase-4 scheduling tests: the bandits converge to the best arm (regret stays sublinear),
the meta-ranker prefers historically-successful patterns, and the scheduler only ORDERS
Proposed experiments (advisory — it never runs or promotes anything)."""
from __future__ import annotations

import random
from collections import Counter

import pytest

from command_center.improvement.scheduling import (
    ThompsonBandit, UCB1, cumulative_regret, MetaRanker, recommend_order,
)

TRUE = {"a": 0.2, "b": 0.5, "c": 0.85}     # arm c is best


def _simulate(bandit, rounds=800, seed=99):
    rng = random.Random(seed)
    pulls: Counter = Counter()
    rewards = []
    for _ in range(rounds):
        arm = bandit.select()
        r = 1.0 if rng.random() < TRUE[arm] else 0.0
        bandit.update(arm, r)
        pulls[arm] += 1
        rewards.append(r)
    return pulls, rewards


# ---- Thompson sampling ------------------------------------------------------

def test_thompson_converges_to_best_arm():
    bandit = ThompsonBandit(["a", "b", "c"], seed=1)
    pulls, rewards = _simulate(bandit)
    assert pulls["c"] > pulls["a"] and pulls["c"] > pulls["b"]   # exploits the best arm
    assert bandit.ranking()[0] == "c"                            # posterior agrees
    # average reward sits near the best arm (0.85), far above random-arm play (~0.52)
    assert sum(rewards) / len(rewards) > 0.7


def test_thompson_regret_is_sublinear():
    bandit = ThompsonBandit(["a", "b", "c"], seed=2)
    _, rewards = _simulate(bandit)
    regret = cumulative_regret(rewards, optimal_mean=TRUE["c"])
    # a random policy would average ~0.85-0.52=0.33 regret/round; a learner is far below that
    assert regret[-1] / len(rewards) < 0.15


def test_thompson_validates_input():
    b = ThompsonBandit(["a", "b"], seed=1)
    with pytest.raises(ValueError):
        b.update("a", 1.5)                    # reward out of [0,1]
    with pytest.raises(KeyError):
        b.update("zzz", 1.0)
    with pytest.raises(ValueError):
        ThompsonBandit(["only"])              # needs >= 2 arms


# ---- UCB1 -------------------------------------------------------------------

def test_ucb1_converges_to_best_arm():
    bandit = UCB1(["a", "b", "c"])
    pulls, _ = _simulate(bandit)
    assert pulls["c"] > pulls["a"] and pulls["c"] > pulls["b"]


# ---- meta-ranker ------------------------------------------------------------

def test_meta_ranker_prefers_successful_pattern():
    history = [
        ({"target_type": "retrieval"}, True), ({"target_type": "retrieval"}, True),
        ({"target_type": "retrieval"}, True), ({"target_type": "prompt"}, False),
        ({"target_type": "prompt"}, False),
    ]
    ranker = MetaRanker(history)
    assert ranker.score({"target_type": "retrieval"}) > ranker.score({"target_type": "prompt"})
    # unseen feature value falls back to the smoothed prior 0.5
    assert ranker.score({"target_type": "unseen"}) == 0.5


def test_recommend_order_is_advisory_ordering():
    history = [({"target_type": "retrieval"}, True), ({"target_type": "retrieval"}, True),
               ({"target_type": "prompt"}, False), ({"target_type": "prompt"}, False)]
    proposed = [
        {"experiment_id": "E1", "features": {"target_type": "prompt"}},
        {"experiment_id": "E2", "features": {"target_type": "retrieval"}},
    ]
    dec = recommend_order(proposed, history)
    assert dec.ordering == ["E2", "E1"]       # historically-successful target first
    assert dec.rationale["E2"] > dec.rationale["E1"]

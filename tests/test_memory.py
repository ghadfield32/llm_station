"""
Durable cross-conversation memory (growthos/memory.py). Hermetic: a deterministic
bag-of-words embedder is injected, so these run with no Ollama and still exercise real
relevance ranking, recency decay, forgetting, per-owner isolation, restart durability,
and project scoping. The pure pieces (cosine, recency, render) are tested directly; the
store is tested through its injected embed_fn + clock.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_GROWTHOS = Path(__file__).resolve().parents[1] / "appflowy_kanban" / "growth-os"
sys.path.insert(0, str(_GROWTHOS))

from growthos.memory import (  # noqa: E402
    MemoryConfig,
    MemoryError,
    MemoryStore,
    _cosine,
    _recency_factor,
    load_memory_config,
    render_memory_state,
)

# A deterministic, semantically-meaningful embedder: each text becomes term counts over
# a fixed vocab (+ a constant dim so nothing is the zero vector). Overlapping words ->
# higher cosine, so ranking tests are real without a model.
_VOCAB = ["coffee", "tea", "python", "rust", "morning", "deadline", "betts", "kanban"]


def _fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        tl = t.lower()
        out.append([float(tl.count(w)) for w in _VOCAB] + [1.0])
    return out


def _cfg(**over) -> MemoryConfig:
    base = dict(enabled=True, owner="tester", max_facts_injected=8,
                refresh_every_rounds=3, recency_half_life_days=30.0,
                embed_model="nomic-embed-text")
    base.update(over)
    return MemoryConfig(**base)


def _store(tmp_path, *, clock=None, **cfg_over) -> MemoryStore:
    kw = {} if clock is None else {"clock": clock}
    return MemoryStore(tmp_path / "memory.db", embed_fn=_fake_embed,
                       config=_cfg(**cfg_over), **kw)


# ---- the core capability: cross-conversation recall -----------------------

def test_remember_then_retrieve_recalls_fact(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "I drink coffee every morning")
    got = s.retrieve("tester", "what do I drink in the morning")
    assert any("coffee" in f.fact for f in got)


def test_cross_conversation_recall_is_keyed_on_owner_not_conversation(tmp_path):
    # remember in "conversation A" then retrieve in "conversation B": the store has no
    # conversation concept — same owner -> recalled. This is the gap the deque(12) left.
    s = _store(tmp_path)
    s.remember("tester", "my kanban deadline is friday")
    # a brand-new retrieve call (== a fresh conversation) still sees it:
    got = s.retrieve("tester", "deadline")
    assert got and "deadline" in got[0].fact


def test_retrieve_ranks_relevant_above_irrelevant(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "I drink coffee every morning")
    s.remember("tester", "I write rust for the engine")
    ranked = s.retrieve("tester", "coffee")
    assert ranked[0].fact.startswith("I drink coffee")


def test_top_k_caps_results(tmp_path):
    s = _store(tmp_path, max_facts_injected=2)
    for i in range(5):
        s.remember("tester", f"coffee fact number {i}")
    assert len(s.retrieve("tester", "coffee")) == 2


# ---- forgetting -----------------------------------------------------------

def test_forget_exact_supersedes(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "I drink coffee every morning")
    assert s.forget("tester", "I drink coffee every morning") == 1
    assert not any("coffee" in f.fact for f in s.retrieve("tester", "coffee"))


def test_forget_nearest_when_no_exact_match(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "I prefer python for scripting")
    # paraphrase, not exact text -> nearest active fact by cosine is removed
    assert s.forget("tester", "python") == 1
    assert not s.retrieve("tester", "python")


def test_forget_nothing_to_forget_returns_zero(tmp_path):
    s = _store(tmp_path)
    assert s.forget("tester", "anything") == 0


# ---- the leak boundary ----------------------------------------------------

def test_per_owner_isolation_no_leak(tmp_path):
    s = _store(tmp_path)
    s.remember("alice", "alice likes coffee")
    assert s.retrieve("bob", "coffee") == []          # bob can never read alice's facts


def test_project_scoping(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "coffee is global")               # project "" == global
    s.remember("tester", "coffee on betts", project="betts")
    betts = {f.fact for f in s.retrieve("tester", "coffee", project="betts")}
    growth = {f.fact for f in s.retrieve("tester", "coffee", project="growth")}
    both = {f.fact for f in s.retrieve("tester", "coffee", project=None)}
    assert "coffee is global" in betts and "coffee on betts" in betts   # global + active
    assert betts >= growth and "coffee on betts" not in growth          # no cross-project leak
    assert "coffee on betts" in both and "coffee is global" in both     # None == no filter


# ---- durability -----------------------------------------------------------

def test_restart_durability(tmp_path):
    s1 = _store(tmp_path)
    s1.remember("tester", "remember me across a restart")
    s1.close()
    s2 = _store(tmp_path)                              # reopen the same db file
    assert s2.retrieve("tester", "remember me across a restart")


# ---- recency --------------------------------------------------------------

def test_recency_factor_decays_by_half_life():
    assert _recency_factor(0.0, half_life_days=30.0) == pytest.approx(1.0)
    assert _recency_factor(30.0 * 86400.0, half_life_days=30.0) == pytest.approx(0.5, rel=1e-6)


def test_recency_factor_requires_positive_half_life():
    with pytest.raises(MemoryError):
        _recency_factor(1.0, half_life_days=0.0)


def test_recency_breaks_ties_newer_first(tmp_path):
    clock = {"t": 0.0}
    s = _store(tmp_path, clock=lambda: clock["t"])
    clock["t"] = 0.0
    s.remember("tester", "coffee old")
    clock["t"] = 100.0 * 86400.0                      # 100 days later
    s.remember("tester", "coffee new")
    ranked = s.retrieve("tester", "coffee")           # equal relevance, recency decides
    assert ranked[0].fact == "coffee new"


# ---- fail-loud (no fabricated vectors, no silent degrade) ------------------

def test_retrieve_fails_loud_when_embedder_down(tmp_path):
    def dead(_texts):
        raise MemoryError("embedder unreachable")
    s = MemoryStore(tmp_path / "m.db", embed_fn=_fake_embed, config=_cfg())
    s.remember("tester", "a fact")                    # remembered while embedder was up
    s._embed = dead                                   # embedder dies before recall
    with pytest.raises(MemoryError):                  # NOT a recency-only fallback
        s.retrieve("tester", "a fact")


def test_remember_empty_fact_is_rejected(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(MemoryError):
        s.remember("tester", "   ")


def test_cosine_dim_mismatch_raises():
    with pytest.raises(MemoryError):
        _cosine([1.0, 2.0], [1.0])


# ---- rendering (pure) -----------------------------------------------------

def test_render_empty_is_empty_string(tmp_path):
    assert render_memory_state([]) == ""


def test_render_lists_facts_with_project_tag(tmp_path):
    s = _store(tmp_path)
    s.remember("tester", "global fact")
    s.remember("tester", "scoped fact", project="betts")
    block = render_memory_state(s.retrieve("tester", "fact"))
    assert "global fact" in block and "scoped fact" in block and "[betts]" in block
    assert block.startswith("=== REMEMBERED") and block.rstrip().endswith("END REMEMBERED ===")


# ---- the committed config validates --------------------------------------

def test_committed_config_is_valid():
    cfg = load_memory_config()
    assert cfg.embed_model and cfg.owner and cfg.recency_half_life_days > 0


def test_missing_knob_fails_loud():
    with pytest.raises(Exception):
        MemoryConfig.model_validate({"enabled": True})     # missing required knobs


def test_extra_knob_forbidden():
    with pytest.raises(Exception):
        MemoryConfig.model_validate({
            "enabled": True, "owner": "x", "max_facts_injected": 8,
            "refresh_every_rounds": 3, "recency_half_life_days": 30.0,
            "embed_model": "nomic-embed-text", "surprise": 1})

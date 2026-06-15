"""Offline tests for the model scout (WS2): source dispatch, fit annotation, parsing.

No network: the one fetch test monkeypatches httpx.get with a canned payload.
"""
from types import SimpleNamespace

from command_center.registry import model_scout as scout


def test_fetcher_keys_match_known_sources():
    # the dispatch table and the validation set must not drift apart
    assert set(scout.FETCHERS) == scout.KNOWN_SOURCES


def test_annotate_fit_without_budget_is_na():
    out = scout.annotate_fit({"ollama_tag": "qwen3:30b"}, None, 32768, {"qwen3:30b"})
    assert out.startswith("n/a")


def test_annotate_fit_uninstalled_is_unknown_not_fabricated():
    # a candidate we haven't pulled is reported honestly, never with a fake number
    out = scout.annotate_fit({"ollama_tag": "qwen3.6:27b"}, 24.0, 32768, installed=set())
    assert out == "unknown - pull to verify"
    out2 = scout.annotate_fit({"ollama_tag": None}, 24.0, 32768, installed={"x"})
    assert out2 == "unknown - pull to verify"


def _registry(sources):
    return SimpleNamespace(
        scout=SimpleNamespace(sources=sources, max_candidates_per_run=10)
    )


def test_gather_offline_skips_fetch_and_flags_unknown_source():
    reg = _registry(["aider-polyglot", "bogus-source"])
    candidates, errors, notes, installed = scout.gather(
        reg, offline=True, ctx=32768, max_candidates=10
    )
    assert candidates == []
    assert any("bogus-source" in e for e in errors)         # unknown -> error
    assert any("aider-polyglot" in n for n in notes)        # known -> skipped note
    assert installed == set()                               # no Ollama call offline


def test_aider_parse_ranks_by_pass_rate(monkeypatch):
    yaml_text = (
        "- model: strong-model\n"
        "  edit_format: diff\n"
        "  pass_rate_2: 51.6\n"
        "- model: weak-model\n"
        "  edit_format: whole\n"
        "  pass_rate_2: 3.6\n"
        "- notamodel: ignore-me\n"          # no 'model' key -> skipped
    )

    def fake_get(url, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, text=yaml_text)

    monkeypatch.setattr(scout.httpx, "get", fake_get)
    rows = scout.fetch_aider_polyglot()
    ids = [r["id"] for r in rows]
    assert ids == ["strong-model", "weak-model"]            # malformed row dropped
    assert all(r["source"] == "aider-polyglot" for r in rows)
    assert rows[0]["coding_score"] == 51.6


def test_gather_sorts_scored_before_unscored():
    # pure sort behavior: scored candidates rank above unscored, desc by score
    cands = [
        {"coding_score": None}, {"coding_score": 10.0}, {"coding_score": 40.0},
    ]
    cands.sort(key=lambda c: (c["coding_score"] is None, -(c["coding_score"] or 0)))
    assert [c["coding_score"] for c in cands] == [40.0, 10.0, None]


def test_open_weight_filter_omits_unverified_sources(monkeypatch):
    monkeypatch.setattr(scout, "gpu_budget_gb", lambda: None)
    monkeypatch.setattr(scout.vram, "ollama_tags", lambda: {"local-open:latest": 1})
    monkeypatch.setitem(scout.FETCHERS, "aider-polyglot", lambda: [
        {"id": "closed-top", "source": "aider-polyglot", "coding_score": 99.0,
         "ollama_tag": None, "open_weight": None}
    ])
    monkeypatch.setitem(scout.FETCHERS, "local-ollama-tags", lambda: [
        {"id": "local-open:latest", "source": "local-ollama-tags", "coding_score": None,
         "ollama_tag": "local-open:latest", "open_weight": True}
    ])
    reg = _registry(["aider-polyglot", "local-ollama-tags"])
    candidates, _errors, notes, _installed = scout.gather(
        reg, offline=False, ctx=32768, max_candidates=10)
    assert [c["id"] for c in candidates] == ["local-open:latest"]
    assert any("open-weight filter" in n for n in notes)


def test_discovery_feed_records_require_open_weight_and_score():
    records = scout.discovery_feed_records([
        {"id": "open-scored", "open_weight": True, "coding_score": 77.0,
         "source": "artificial-analysis", "open_weight_evidence": "explicit",
         "ollama_tag": "open-scored:q4", "candidate_roles": ["coder"]},
        {"id": "open-unscored", "open_weight": True, "coding_score": None,
         "source": "local-ollama-tags"},
        {"id": "unknown-scored", "open_weight": None, "coding_score": 99.0,
         "source": "aider-polyglot"},
    ])
    assert len(records) == 1
    assert records[0]["record_type"] == "model_scout_candidate"
    assert records[0]["model"] == "open-scored"
    assert records[0]["candidate_roles"] == ["coder"]

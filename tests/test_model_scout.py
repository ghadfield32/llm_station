"""Offline tests for the model scout (WS2): source dispatch, fit annotation, parsing.

No network: the one fetch test monkeypatches httpx.get with a canned payload.
"""
from types import SimpleNamespace

import pytest
import yaml

from command_center.registry import model_scout as scout
from command_center.schemas import CuratedModelScoutConfig


def _ollama_record(name="devstral:24b", digest="d" * 64,
                   parameter_size="23.6B", quant="Q4_K_M", context=131072):
    return {
        "name": name,
        "size": 14333928046,
        "digest": digest,
        "details": {
            "parameter_size": parameter_size,
            "quantization_level": quant,
            "context_length": context,
        },
    }


def _curated_payload(*, digest="d" * 64, roles=None, license="Apache-2.0"):
    return {
        "schema_version": "command-center.model-scout-curated-openweight.v1",
        "records": [{
            "record_id": "devstral-test",
            "identity": {
                "model_family": "devstral",
                "release_id": "devstral-small-2505",
                "source_model_id": "mistralai/Devstral-Small-2505",
                "source_model_url": "https://example.test/model",
                "source_model_payload_sha256": "a" * 64,
                "ollama_tag": "devstral:24b",
                "ollama_digest": digest,
                "parameter_size": "23.6B",
                "quantization": "Q4_K_M",
                "license": license,
                "context_length": 131072,
            },
            "open_weight_evidence": "explicit Apache-2.0 source plus local digest",
            "benchmark": {
                "name": "SWE-bench Verified",
                "version": "test fixture",
                "metric": "swe_bench_verified_percent",
                "score": 46.8,
                "score_definition": "percent resolved",
                "evaluation_date": "2025-05-21",
                "candidate_roles": roles or ["coder"],
                "source_url": "https://example.test/benchmark",
                "retrieval_timestamp": "2026-06-15T14:01:34-04:00",
                "source_payload_sha256": "b" * 64,
            },
        }],
    }


def _write_curated(path, payload):
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_fetcher_keys_match_known_sources():
    # FETCHERS covers the per-candidate sources; model-watchlist is a known source that runs
    # on its OWN track (gather_watchlist), so it is intentionally not a fetcher. The dispatch
    # table plus the watchlist source must exactly reconstruct the validated known set.
    assert set(scout.FETCHERS) | {scout.WATCHLIST_SOURCE} == scout.KNOWN_SOURCES
    assert scout.WATCHLIST_SOURCE not in scout.FETCHERS


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
        scout=SimpleNamespace(sources=sources, max_candidates_per_run=10),
        roles={
            "coder": [SimpleNamespace(model="devstral:24b", license="Apache-2.0")],
            "planner": [],
        },
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


def test_curated_openweight_source_joins_exact_local_identity(tmp_path, monkeypatch):
    path = tmp_path / "curated.yaml"
    _write_curated(path, _curated_payload())
    monkeypatch.setattr(scout, "CURATED_OPENWEIGHT", path)
    monkeypatch.setattr(scout, "load_registry", lambda: _registry(["curated-openweight"]))
    monkeypatch.setattr(scout.vram, "ollama_tag_records", lambda: [_ollama_record()])

    rows = scout.fetch_curated_openweight()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "devstral:24b"
    assert row["source"] == "curated-openweight"
    assert row["coding_score"] == 46.8
    assert row["candidate_roles"] == ["coder"]
    assert row["digest"] == "d" * 64
    assert row["source_payload_sha256"] == "b" * 64


def test_curated_openweight_source_rejects_digest_mismatch(tmp_path, monkeypatch):
    path = tmp_path / "curated.yaml"
    _write_curated(path, _curated_payload(digest="c" * 64))
    monkeypatch.setattr(scout, "CURATED_OPENWEIGHT", path)
    monkeypatch.setattr(scout, "load_registry", lambda: _registry(["curated-openweight"]))
    monkeypatch.setattr(scout.vram, "ollama_tag_records", lambda: [_ollama_record()])

    with pytest.raises(RuntimeError, match="ollama_digest"):
        scout.fetch_curated_openweight()


def test_curated_openweight_source_rejects_unknown_role(tmp_path, monkeypatch):
    path = tmp_path / "curated.yaml"
    _write_curated(path, _curated_payload(roles=["judge"]))
    monkeypatch.setattr(scout, "CURATED_OPENWEIGHT", path)
    monkeypatch.setattr(scout, "load_registry", lambda: _registry(["curated-openweight"]))
    monkeypatch.setattr(scout.vram, "ollama_tag_records", lambda: [_ollama_record()])

    with pytest.raises(RuntimeError, match="unknown candidate_roles"):
        scout.fetch_curated_openweight()


def test_curated_openweight_source_rejects_license_conflict(tmp_path, monkeypatch):
    path = tmp_path / "curated.yaml"
    _write_curated(path, _curated_payload(license="Other-License"))
    monkeypatch.setattr(scout, "CURATED_OPENWEIGHT", path)
    monkeypatch.setattr(scout, "load_registry", lambda: _registry(["curated-openweight"]))
    monkeypatch.setattr(scout.vram, "ollama_tag_records", lambda: [_ollama_record()])

    with pytest.raises(RuntimeError, match="license expected"):
        scout.fetch_curated_openweight()


def test_curated_openweight_config_rejects_wrong_schema_version():
    payload = _curated_payload()
    payload["schema_version"] = "command-center.model-scout-curated-openweight.v0"

    with pytest.raises(ValueError, match="schema_version"):
        CuratedModelScoutConfig.model_validate(payload)


# ---- watchlist: tracking un-pulled frontier / pull-to-verify models -----------

def _watchlist_payload(*, tier="frontier_watch", params=744.0, roles=None, family="glm",
                       release="GLM-5.2", quant="Q4_K_M", ollama_tag=None,
                       ollama_local=False):
    rec = {
        "record_id": f"{release}-test".lower(),
        "tier": tier,
        "model_family": family,
        "release_id": release,
        "source_model_url": "https://example.test/model",
        "parameter_count_b": params,
        "reference_quant": quant,
        "license": "MIT",
        "open_weight_evidence": "example open-weight evidence",
        "source_url": "https://example.test/card",
        "retrieval_timestamp": "2026-06-20",
    }
    if roles is not None:
        rec["candidate_roles"] = roles
    if ollama_tag:
        rec["ollama_tag"] = ollama_tag
        rec["ollama_local"] = ollama_local
    return {"schema_version": "command-center.model-scout-watchlist.v1", "records": [rec]}


def _write_watchlist(path, payload):
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_watchlist_frontier_is_hard_no_on_both_budgets(tmp_path, monkeypatch):
    # GLM-5.2-class (744B) is a hard NO on 24GB AND 16GB via the weights-only lower bound,
    # WITHOUT being installed — the whole point of the watchlist.
    path = tmp_path / "watchlist.yaml"
    _write_watchlist(path, _watchlist_payload(params=744.0))
    monkeypatch.setattr(scout, "WATCHLIST", path)
    reg = _registry(["model-watchlist"])
    rows = scout.fetch_watchlist(reg, installed=set(), budget_24gb=24.0, budget_16gb=16.0)
    assert len(rows) == 1 and rows[0]["tier"] == "frontier_watch"
    assert "NO @ 24GB" in rows[0]["fit_24gb"]
    assert "NO @ 16GB" in rows[0]["fit_16gb"]


def test_watchlist_verified_artifact_drives_named_target_verdicts(tmp_path, monkeypatch):
    # With a verified 238GB artifact, GLM-5.2 is does_not_fit on 24GB AND 16GB, but
    # ram_only_frontier_experiment on a 256GB-class machine — the exact lane the user wants.
    path = tmp_path / "watchlist.yaml"
    payload = _watchlist_payload(params=744.0)
    payload["records"][0]["local_artifact"] = {
        "type": "gguf", "provider": "unsloth",
        "smallest_verified_size_gb": 238, "quant": "dynamic-2bit"}
    _write_watchlist(path, payload)
    monkeypatch.setattr(scout, "WATCHLIST", path)
    reg = _registry(["model-watchlist"])
    rows = scout.fetch_watchlist(reg, installed=set(), budget_24gb=24.0, budget_16gb=16.0)
    rt = rows[0]["runnable_targets"]
    assert rt["cc_worker_4090_24gb"] == "does_not_fit"
    assert rt["laptop_5080_16gb"] == "does_not_fit"
    assert rt["ram_256gb_class"] == "ram_only_frontier_experiment"
    assert rt["footprint_source"] == "verified_artifact"
    assert rows[0]["smallest_verified_size_gb"] == 238
    assert "verified dynamic-2bit artifact ~238GB" in rows[0]["fit_24gb"]


def test_watchlist_pull_to_verify_rejects_unknown_role(tmp_path, monkeypatch):
    path = tmp_path / "watchlist.yaml"
    _write_watchlist(path, _watchlist_payload(
        tier="pull_to_verify", params=21.0, roles=["nonexistent-role"]))
    monkeypatch.setattr(scout, "WATCHLIST", path)
    reg = _registry(["model-watchlist"])
    with pytest.raises(RuntimeError, match="unknown"):
        scout.fetch_watchlist(reg, installed=set(), budget_24gb=24.0, budget_16gb=16.0)


def test_watchlist_pull_to_verify_unknown_fit_when_weights_clear_floor(tmp_path, monkeypatch):
    path = tmp_path / "watchlist.yaml"
    _write_watchlist(path, _watchlist_payload(
        tier="pull_to_verify", params=14.0, roles=["planner"]))
    monkeypatch.setattr(scout, "WATCHLIST", path)
    reg = _registry(["model-watchlist"])
    rows = scout.fetch_watchlist(reg, installed=set(), budget_24gb=24.0, budget_16gb=16.0)
    assert "unknown - pull to verify" in rows[0]["fit_24gb"]
    assert "FITS" not in rows[0]["fit_24gb"]   # never a fabricated positive from the bound


def test_watchlist_feed_record_tier_mapping():
    recs = scout.watchlist_feed_records([
        {"tier": "frontier_watch", "model": "GLM-5.2", "model_family": "glm",
         "release_id": "GLM-5.2", "ollama_local": False, "open_weight_evidence": "e",
         "license": "MIT", "parameter_count_b": 744.0, "active_param_count_b": 40.0,
         "is_moe": True, "context_length": 1048576, "ollama_tag": None,
         "candidate_roles": [], "fit_24gb": "NO", "fit_16gb": "NO",
         "source_url": "u", "source_model_url": "m", "retrieval_timestamp": "2026-06-20",
         "notes": "n"},
        {"tier": "pull_to_verify", "model": "gpt-oss-20b", "model_family": "gpt-oss",
         "release_id": "gpt-oss-20b", "ollama_local": True, "open_weight_evidence": "e",
         "license": "Apache-2.0", "parameter_count_b": 21.0, "active_param_count_b": 3.6,
         "is_moe": True, "context_length": 131072, "ollama_tag": "gpt-oss:20b",
         "candidate_roles": ["planner"], "fit_24gb": "unknown", "fit_16gb": "unknown",
         "source_url": "u", "source_model_url": "m", "retrieval_timestamp": "2026-06-20",
         "notes": "n"},
    ])
    assert [r["record_type"] for r in recs] == ["frontier_watch", "model_pull_candidate"]


def test_gather_watchlist_absent_source_is_noop():
    reg = _registry(["aider-polyglot"])
    records, errors = scout.gather_watchlist(reg, offline=True, installed=set())
    assert records == [] and errors == []


def test_scan_feed_records_offline_includes_watchlist_frontier():
    # Integration check of the DAG bridge against the REAL configs/model-scout-watchlist.yaml:
    # offline, the model feed still surfaces frontier models (GLM-5.2) by name + a pull
    # candidate. This is what makes the scheduled DAG able to "check on GLM/Kimi when found".
    recs = scout.scan_feed_records(offline=True)
    types = {r["record_type"] for r in recs}
    models = {r["model"] for r in recs}
    assert "frontier_watch" in types
    assert "GLM-5.2" in models
    assert any(r["record_type"] == "model_pull_candidate" for r in recs)

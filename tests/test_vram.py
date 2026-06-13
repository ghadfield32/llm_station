"""Offline, deterministic tests for the VRAM-fit formula.

No live Ollama: every test drives the pure formula or feeds metadata_for a
synthetic /api/show payload. The numbers below are internally consistent test
fixtures, NOT claims about any real model's architecture.
"""
import math

import pytest

from command_center.registry import vram

GIB = 1024 ** 3


def test_kv_cache_gb_matches_hand_computation():
    # per_token = layers * kv_heads * (k+v) * bytes = 2*2*(4+4)*2 = 64 bytes
    got = vram.kv_cache_gb(
        n_layers=2, n_kv_heads=2, key_length=4, value_length=4, ctx=10, kv_bytes=2.0
    )
    assert math.isclose(got, 64 * 10 / GIB, rel_tol=1e-9)


def test_kv_cache_uses_kv_heads_not_query_heads():
    # The formula has no query-head input at all: GQA correctness is structural.
    small = vram.kv_cache_gb(n_layers=4, n_kv_heads=2, key_length=8,
                             value_length=8, ctx=1000)
    big = vram.kv_cache_gb(n_layers=4, n_kv_heads=8, key_length=8,
                           value_length=8, ctx=1000)
    assert math.isclose(big, 4 * small, rel_tol=1e-9)  # 4x kv-heads -> 4x cache


def test_kv_cache_rejects_nonpositive_input():
    with pytest.raises(vram.VramError):
        vram.kv_cache_gb(n_layers=0, n_kv_heads=2, key_length=4,
                         value_length=4, ctx=10)


def test_thirty_b_fits_seventy_b_does_not_on_24gb():
    # The headline guarantee: a ~30B Q4 model fits a 24GB card; a 70B does not.
    # Weights come from the real on-disk size (18GB vs 39GB), KV kept tiny here
    # so the weights term is what decides fit.
    common = dict(
        weights_source="ollama_tags", n_layers=1, n_kv_heads=1,
        key_length=1, value_length=1, native_ctx=131072, ctx=8192, budget_gb=24.0,
    )
    fits = vram.estimate_from_metadata(name="m30", weights_gb=18.0, **common)
    nofit = vram.estimate_from_metadata(name="m70", weights_gb=39.0, **common)
    assert fits.fits is True
    assert nofit.fits is False
    assert nofit.headroom_gb < 0


def test_headroom_prevents_fit_at_100_percent():
    # total exactly equal to budget must NOT fit, because of the safety headroom.
    common = dict(
        weights_source="ollama_tags", n_layers=1, n_kv_heads=1,
        key_length=1, value_length=1, native_ctx=4096, ctx=128, budget_gb=10.0,
    )
    est = vram.estimate_from_metadata(
        name="exact", weights_gb=10.0 - vram.CUDA_BASELINE_GB, **common
    )
    assert est.total_gb == pytest.approx(10.0, abs=0.05)
    assert est.fits is False  # 10 * 1.10 > 10


def test_max_ctx_fits_zero_when_weights_exceed_budget():
    assert vram.max_ctx_fits(
        weights_gb=40.0, n_layers=48, n_kv_heads=8, key_length=128,
        value_length=128, budget_gb=24.0,
    ) == 0


def test_max_ctx_fits_is_positive_and_shrinks_with_bigger_model():
    small = vram.max_ctx_fits(weights_gb=8.0, n_layers=32, n_kv_heads=8,
                              key_length=128, value_length=128, budget_gb=24.0)
    large = vram.max_ctx_fits(weights_gb=18.0, n_layers=48, n_kv_heads=8,
                              key_length=128, value_length=128, budget_gb=24.0)
    assert small > large > 0


def test_weights_from_bpw_known_quant():
    # 1B params at Q8_0 (8.5 bpw): 1e9 * 8.5 / 8 bytes.
    got = vram.weights_gb_from_bpw(1.0, "Q8_0")
    assert math.isclose(got, 1e9 * 8.5 / 8 / GIB, rel_tol=1e-9)


def test_weights_from_bpw_unknown_quant_raises():
    with pytest.raises(vram.VramError):
        vram.weights_gb_from_bpw(1.0, "Q4_K_FANTASY")


def _show(arch="testmoe", **overrides):
    info = {
        "general.architecture": arch,
        f"{arch}.block_count": 4,
        f"{arch}.attention.head_count": 8,
        f"{arch}.attention.head_count_kv": 2,
        f"{arch}.attention.key_length": 16,
        f"{arch}.attention.value_length": 16,
        f"{arch}.context_length": 32768,
        f"{arch}.embedding_length": 128,
        "general.parameter_count": 7_000_000_000,
    }
    info.update(overrides)
    return {"model_info": info, "details": {"quantization_level": "Q4_K_M"}}


def test_metadata_for_uses_ondisk_size_and_explicit_head_dim():
    meta = vram.metadata_for("foo", show=_show(), size_bytes=4 * GIB)
    assert meta["weights_source"] == "ollama_tags"
    assert meta["weights_gb"] == pytest.approx(4.0)
    assert meta["n_kv_heads"] == 2
    assert meta["key_length"] == 16 and meta["value_length"] == 16
    assert meta["params_b"] == pytest.approx(7.0)


def test_metadata_for_derives_head_dim_from_embedding_when_absent():
    show = _show()
    del show["model_info"]["testmoe.attention.key_length"]
    del show["model_info"]["testmoe.attention.value_length"]
    meta = vram.metadata_for("foo", show=show, size_bytes=GIB)
    # embedding_length 128 / head_count 8 = 16
    assert meta["key_length"] == 16 and meta["value_length"] == 16


def test_metadata_for_raises_on_missing_required_key():
    show = _show()
    del show["model_info"]["testmoe.block_count"]
    with pytest.raises(vram.VramError):
        vram.metadata_for("foo", show=show, size_bytes=GIB)


def test_metadata_for_falls_back_to_bpw_when_no_ondisk_size():
    meta = vram.metadata_for("foo", show=_show(), size_bytes=None)
    assert meta["weights_source"] == "bpw_estimate"
    # 7B at Q4_K_M (4.83 bpw)
    assert meta["weights_gb"] == pytest.approx(7e9 * 4.83 / 8 / GIB, rel=1e-6)

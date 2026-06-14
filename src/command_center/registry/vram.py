#!/usr/bin/env python3
"""VRAM-fit estimation for local Ollama models.

Answers "what is the best model my GPU can actually hold" with a data-derived
number instead of a guess. Inputs come straight from the model files Ollama
already has on disk:

  - ``/api/tags``  -> the real on-disk quantized weight size (bytes).
  - ``/api/show``  -> GGUF metadata: block (layer) count, GQA kv-head count,
                      key/value head dim, native context length.
  - ``/api/ps``    -> the ACTUAL resident footprint of a loaded model, used to
                      verify the prediction (``size_vram`` vs our estimate).

We apply the standard transformer KV-cache formula. The single biggest error
source in VRAM math is using the query-head count instead of the GQA kv-head
count; we read ``<arch>.attention.head_count_kv`` directly from the model file,
so that mistake is unrepresentable here.

Why not shell out to gguf-parser-go / quantest: Ollama's ``/api/show`` exposes
the same GGUF metadata over HTTP with no extra binary, and ``/api/tags`` gives
the exact quantized weight bytes on disk -- more accurate than reconstructing
weights from an effective-bits-per-weight table. The bpw table below is only the
fallback for a model we have NOT pulled (param count known, file absent). An
installed gguf-parser-go remains a valid optional cross-check.

No fabricated values: if Ollama is unreachable or a required metadata key is
absent, we raise. We never substitute a plausible default for a missing fact --
a missing number is reported as an error, not papered over.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

import httpx

# ---- physical constants (not tunable thresholds) ---------------------------
# Bytes per KV-cache element. Ollama's default cache is fp16 (2 bytes). Setting
# OLLAMA_KV_CACHE_TYPE=q8_0 -> 1.0, q4_0 -> ~0.5; pass kv_bytes to override.
KV_BYTES_FP16 = 2.0

# Effective bits-per-weight for llama.cpp GGUF quants. These are measured format
# widths (k-quants carry per-block scales, so Q4_K_M is ~4.8 bpw, NOT 4.0). Used
# ONLY to estimate weights for a model that is not pulled (no on-disk size). For
# installed models we use the real /api/tags size instead.
EFFECTIVE_BPW: dict[str, float] = {
    "Q2_K": 3.35,
    "Q3_K_S": 3.50, "Q3_K_M": 3.91, "Q3_K_L": 4.27,
    "Q4_K_S": 4.37, "Q4_K_M": 4.83, "Q4_0": 4.55, "Q4_1": 5.0,
    "Q5_K_S": 5.21, "Q5_K_M": 5.33, "Q5_0": 5.54, "Q5_1": 6.0,
    "Q6_K": 6.56,
    "Q8_0": 8.50,
    "F16": 16.0, "BF16": 16.0, "F32": 32.0,
}

# ---- calibration constants (verified against /api/ps, not arbitrary) -------
# Fixed CUDA context + non-KV buffers a loaded model needs beyond weights + KV.
# An empirical floor; the CLI surfaces predicted-vs-actual (/api/ps) so this is
# checkable, not a hidden fudge factor.
CUDA_BASELINE_GB = 0.8
# Fraction of the budget kept free so a fit isn't declared at 100% utilisation
# (allocator fragmentation, display, transient peaks).
SAFETY_HEADROOM_FRAC = 0.10

GIB = 1024 ** 3
DEFAULT_OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


class VramError(RuntimeError):
    """Raised when a required input is missing or Ollama is unreachable."""


@dataclass(frozen=True)
class Estimate:
    name: str
    quant: str | None
    params_b: float | None          # billions of parameters
    ctx: int                        # context length the estimate was computed at
    native_ctx: int                 # model's max context from GGUF metadata
    weights_gb: float
    kv_gb: float
    total_gb: float                 # weights + kv + baseline (no headroom)
    budget_gb: float
    fits: bool                      # total * (1 + headroom) <= budget
    headroom_gb: float              # budget - total (positive == spare)
    max_ctx_fits: int               # largest context that still fits the budget
    weights_source: str             # "ollama_tags" | "bpw_estimate"
    reserved_gb: float = 0.0        # VRAM held for always-resident companions (e.g. the
                                    # memory embedder) — subtracted from the budget before
                                    # this model's fit is decided

    def to_dict(self) -> dict:
        return asdict(self)


# ---- pure formula core (no I/O; deterministic; unit-tested) ----------------

def kv_cache_gb(
    *,
    n_layers: int,
    n_kv_heads: int,
    key_length: int,
    value_length: int,
    ctx: int,
    kv_bytes: float = KV_BYTES_FP16,
) -> float:
    """KV-cache size in GB for `ctx` tokens.

    Per token the cache stores one K and one V vector per layer per kv-head:
        bytes/token = n_layers * n_kv_heads * (key_length + value_length) * kv_bytes
    GQA models share kv-heads across query-heads, so n_kv_heads (not the query
    head count) is the correct multiplier.
    """
    if min(n_layers, n_kv_heads, key_length, value_length, ctx) <= 0:
        raise VramError(
            f"non-positive KV input: layers={n_layers} kv_heads={n_kv_heads} "
            f"key_len={key_length} val_len={value_length} ctx={ctx}"
        )
    per_token = n_layers * n_kv_heads * (key_length + value_length) * kv_bytes
    return per_token * ctx / GIB


def max_ctx_fits(
    *,
    weights_gb: float,
    n_layers: int,
    n_kv_heads: int,
    key_length: int,
    value_length: int,
    budget_gb: float,
    kv_bytes: float = KV_BYTES_FP16,
    baseline_gb: float = CUDA_BASELINE_GB,
    headroom_frac: float = SAFETY_HEADROOM_FRAC,
    reserved_gb: float = 0.0,
) -> int:
    """Largest context (tokens) whose total footprint still fits the budget.

    reserved_gb is VRAM already committed to always-resident companions (e.g. the
    memory embedder); it shrinks the usable budget before this model's KV cache."""
    usable = budget_gb / (1.0 + headroom_frac) - baseline_gb - weights_gb - reserved_gb
    if usable <= 0:
        return 0
    per_token_gb = n_layers * n_kv_heads * (key_length + value_length) * kv_bytes / GIB
    return int(usable / per_token_gb)


def estimate_from_metadata(
    *,
    name: str,
    weights_gb: float,
    weights_source: str,
    n_layers: int,
    n_kv_heads: int,
    key_length: int,
    value_length: int,
    native_ctx: int,
    ctx: int,
    budget_gb: float,
    quant: str | None = None,
    params_b: float | None = None,
    kv_bytes: float = KV_BYTES_FP16,
    baseline_gb: float = CUDA_BASELINE_GB,
    headroom_frac: float = SAFETY_HEADROOM_FRAC,
    reserved_gb: float = 0.0,
) -> Estimate:
    """Build a full Estimate from already-resolved metadata (no network).

    `reserved_gb` is VRAM held by always-resident companions (e.g. the memory
    embedder); it is charged against the budget alongside this model's own footprint,
    so a model is only `fits` when model + companions + headroom all fit at once."""
    kv = kv_cache_gb(
        n_layers=n_layers, n_kv_heads=n_kv_heads,
        key_length=key_length, value_length=value_length,
        ctx=ctx, kv_bytes=kv_bytes,
    )
    total = weights_gb + kv + baseline_gb
    budget = budget_gb
    return Estimate(
        name=name,
        quant=quant,
        params_b=params_b,
        ctx=ctx,
        native_ctx=native_ctx,
        weights_gb=round(weights_gb, 3),
        kv_gb=round(kv, 3),
        total_gb=round(total, 3),
        budget_gb=round(budget, 3),
        fits=(total + reserved_gb) * (1.0 + headroom_frac) <= budget,
        headroom_gb=round(budget - total - reserved_gb, 3),
        max_ctx_fits=max_ctx_fits(
            weights_gb=weights_gb, n_layers=n_layers, n_kv_heads=n_kv_heads,
            key_length=key_length, value_length=value_length, budget_gb=budget,
            kv_bytes=kv_bytes, baseline_gb=baseline_gb, headroom_frac=headroom_frac,
            reserved_gb=reserved_gb,
        ),
        weights_source=weights_source,
        reserved_gb=round(reserved_gb, 3),
    )


def weights_gb_from_bpw(params_b: float, quant: str) -> float:
    """Estimate weight size for a model that isn't pulled (no on-disk size)."""
    key = quant.upper()
    if key not in EFFECTIVE_BPW:
        raise VramError(
            f"unknown quant {quant!r}; known: {sorted(EFFECTIVE_BPW)}. "
            "Pull the model so /api/tags gives the exact on-disk size instead."
        )
    return params_b * 1e9 * EFFECTIVE_BPW[key] / 8 / GIB


# ---- Ollama I/O ------------------------------------------------------------

def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=30)


def ollama_tags(base_url: str = DEFAULT_OLLAMA_BASE) -> dict[str, int]:
    """name -> on-disk size in bytes for every installed model."""
    try:
        with _client(base_url) as c:
            r = c.get("/api/tags")
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise VramError(f"Ollama unreachable at {base_url}/api/tags: {exc}") from exc
    models = data.get("models")
    if not isinstance(models, list):
        raise VramError("Ollama /api/tags returned an unexpected shape (no 'models' list)")
    return {m["name"]: int(m["size"]) for m in models if "name" in m and "size" in m}


def ollama_show(name: str, base_url: str = DEFAULT_OLLAMA_BASE) -> dict:
    try:
        with _client(base_url) as c:
            r = c.post("/api/show", json={"model": name})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        raise VramError(f"Ollama /api/show failed for {name!r}: {exc}") from exc


def ollama_ps(base_url: str = DEFAULT_OLLAMA_BASE) -> dict[str, dict]:
    """name -> {'size': bytes, 'size_vram': bytes} for currently-loaded models."""
    try:
        with _client(base_url) as c:
            r = c.get("/api/ps")
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as exc:
        raise VramError(f"Ollama /api/ps failed: {exc}") from exc
    out: dict[str, dict] = {}
    for m in data.get("models", []):
        if "name" in m:
            out[m["name"]] = m
    return out


def _resolve_installed(name: str, registry: Mapping[str, object]) -> str | None:
    """Match an Ollama model name against a /api/tags or /api/ps registry, resolving
    Ollama's implicit ':latest' tag (the registry lists 'nomic-embed-text:latest' but a
    caller — and the embed endpoint — accept the untagged 'nomic-embed-text'). Returns
    the registry key or None. Not a fuzzy fallback: only the exact name or its :latest."""
    if name in registry:
        return name
    tagged = f"{name}:latest"
    return tagged if tagged in registry else None


def resident_weight_gb(name: str, base_url: str = DEFAULT_OLLAMA_BASE) -> float:
    """Resident VRAM footprint of an always-on companion model (e.g. the memory
    embedder), so the chat-model fit gate can charge for it.

    Data-derived, never a hand-picked number: prefer the model's ACTUAL resident size
    from /api/ps when it is loaded (ground truth); otherwise its real on-disk weight
    bytes (/api/tags) plus the CUDA baseline every loaded model carries. An embedding
    model has no autoregressive KV cache, so weights + baseline is its footprint. Fails
    loud if the model isn't installed — a missing companion is not silently free."""
    ps = ollama_ps(base_url)
    pk = _resolve_installed(name, ps)
    if pk is not None and "size_vram" in ps[pk]:
        return int(ps[pk]["size_vram"]) / GIB
    sizes = ollama_tags(base_url)
    sk = _resolve_installed(name, sizes)
    if sk is None:
        raise VramError(
            f"{name!r} is not installed; cannot reserve its VRAM. Pull it or correct "
            "the reserved-companion name.")
    return sizes[sk] / GIB + CUDA_BASELINE_GB


def _info_int(info: dict, key: str) -> int:
    if key not in info:
        raise VramError(f"GGUF metadata missing required key {key!r}")
    return int(info[key])


def metadata_for(name: str, *, show: dict, size_bytes: int | None) -> dict:
    """Resolve the metadata the formula needs from an /api/show payload.

    Raises VramError if this isn't a causal LM with the attention metadata we
    need (e.g. an embedding model) -- the caller decides whether to skip it.
    """
    info = show.get("model_info") or {}
    arch = info.get("general.architecture")
    if not arch:
        raise VramError(f"{name}: /api/show has no general.architecture")

    n_layers = _info_int(info, f"{arch}.block_count")
    n_kv_heads = _info_int(info, f"{arch}.attention.head_count_kv")
    n_heads = _info_int(info, f"{arch}.attention.head_count")
    native_ctx = _info_int(info, f"{arch}.context_length")

    # head dim: prefer explicit key/value_length, else derive embedding/head_count
    key_len_key = f"{arch}.attention.key_length"
    val_len_key = f"{arch}.attention.value_length"
    if key_len_key in info and val_len_key in info:
        key_length = int(info[key_len_key])
        value_length = int(info[val_len_key])
    else:
        embed = _info_int(info, f"{arch}.embedding_length")
        if n_heads <= 0:
            raise VramError(f"{name}: head_count is {n_heads}; cannot derive head dim")
        key_length = value_length = embed // n_heads

    details = show.get("details") or {}
    quant = details.get("quantization_level") or info.get("general.file_type")
    params_count = info.get("general.parameter_count")
    params_b = round(int(params_count) / 1e9, 2) if params_count else None

    if size_bytes is not None:
        weights_gb = size_bytes / GIB
        weights_source = "ollama_tags"
    elif params_b is not None and quant:
        weights_gb = weights_gb_from_bpw(params_b, str(quant))
        weights_source = "bpw_estimate"
    else:
        raise VramError(f"{name}: no on-disk size and no (params, quant) to estimate weights")

    return {
        "name": name,
        "weights_gb": weights_gb,
        "weights_source": weights_source,
        "n_layers": n_layers,
        "n_kv_heads": n_kv_heads,
        "key_length": key_length,
        "value_length": value_length,
        "native_ctx": native_ctx,
        "quant": str(quant) if quant else None,
        "params_b": params_b,
    }


def estimate_installed(
    name: str,
    *,
    ctx: int,
    budget_gb: float,
    base_url: str = DEFAULT_OLLAMA_BASE,
    kv_bytes: float = KV_BYTES_FP16,
    reserved_gb: float = 0.0,
) -> Estimate:
    """Estimate one installed model end to end (tags + show). reserved_gb charges for
    always-resident companions (e.g. the memory embedder) against the same budget."""
    sizes = ollama_tags(base_url)
    if name not in sizes:
        raise VramError(f"{name!r} is not an installed Ollama model")
    meta = metadata_for(name, show=ollama_show(name, base_url), size_bytes=sizes[name])
    eff_ctx = min(ctx, meta["native_ctx"])
    return estimate_from_metadata(ctx=eff_ctx, budget_gb=budget_gb, kv_bytes=kv_bytes,
                                  reserved_gb=reserved_gb, **meta)


def list_installed_estimates(
    *,
    ctx: int,
    budget_gb: float,
    base_url: str = DEFAULT_OLLAMA_BASE,
    kv_bytes: float = KV_BYTES_FP16,
    reserved_gb: float = 0.0,
) -> tuple[list[Estimate], list[str]]:
    """Estimate every installed model. Returns (estimates, errors).

    reserved_gb charges always-resident companions (e.g. the memory embedder) against
    the budget so the fit verdict reflects what the GPU holds at once. Errors (e.g.
    embedding models with no attention metadata) are collected and returned, not
    swallowed -- the caller surfaces them.
    """
    sizes = ollama_tags(base_url)
    estimates: list[Estimate] = []
    errors: list[str] = []
    for name, size in sorted(sizes.items()):
        try:
            meta = metadata_for(name, show=ollama_show(name, base_url), size_bytes=size)
            eff_ctx = min(ctx, meta["native_ctx"])
            estimates.append(
                estimate_from_metadata(ctx=eff_ctx, budget_gb=budget_gb, kv_bytes=kv_bytes,
                                       reserved_gb=reserved_gb, **meta)
            )
        except VramError as exc:
            errors.append(f"{name}: {exc}")
    estimates.sort(key=lambda e: (not e.fits, -e.headroom_gb))
    return estimates, errors

#!/usr/bin/env python3
"""Generate a model-scout report from configured discovery sources.

The scout is deliberately propose-only. It discovers candidate local models and
writes a report; it NEVER edits configs/models.yaml and never promotes. Promotion
stays: YAML edit -> validate -> canary -> evals -> human approval.

Discovery is keyless-first. Sources (declared in models.yaml `scout.sources`):
  - aider-polyglot     : Aider's polyglot coding leaderboard (public YAML, no key).
                         The coding-quality signal that ranks candidates.
  - local-ollama-tags  : models already installed via Ollama (guaranteed runnable).
  - curated-openweight : version-controlled scored open-weight records that
                         join to exact installed Ollama tag/digest.
  - artificial-analysis: OPTIONAL. Used only if AA_API_KEY is set in the env;
                         otherwise skipped with a note. Never required.

Every candidate is annotated with VRAM fit on this machine via the WS1 fit gate
(command_center.registry.vram), so the shortlist distinguishes "runnable on the
4090" from "would OOM". A candidate we can't size (not pulled) is reported as
"unknown - pull to verify" -- never a fabricated number.

Per-source failures are collected and surfaced, not swallowed: a down source
shows up in the report's "Source Errors" section and sets a non-zero exit, but
the other sources still produce a report.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from command_center.registry import vram
from command_center.schemas import (
    KNOWN_SCOUT_SOURCES,
    CuratedModelScoutConfig,
    EnvironmentsConfig,
    ModelRegistry,
    ModelWatchlistConfig,
)

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "configs" / "models.yaml"
ENVIRONMENTS = ROOT / "configs" / "environments.yaml"
DEFAULT_OUTPUT = ROOT / "generated" / "model-scout-report.md"
CURATED_OPENWEIGHT = ROOT / "configs" / "model-scout-curated-openweight.yaml"
WATCHLIST = ROOT / "configs" / "model-scout-watchlist.yaml"

AIDER_POLYGLOT_URL = (
    "https://raw.githubusercontent.com/Aider-AI/aider/main/"
    "aider/website/_data/polyglot_leaderboard.yml"
)
ARTIFICIAL_ANALYSIS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
DEFAULT_FIT_CTX = 65536
WORKER_ENV = "cc-worker-4090"     # the PRIMARY 24 GB budget
LAPTOP_ENV = "cc-dev-5080"        # the SECONDARY mobile 16 GB budget

# The full set of sources the scout understands (validated by ScoutSpec at config-load).
# `model-watchlist` is a known source but is NOT a per-candidate fetcher (it runs on its own
# track via gather_watchlist), so it is intentionally absent from FETCHERS below.
KNOWN_SOURCES = set(KNOWN_SCOUT_SOURCES)
WATCHLIST_SOURCE = "model-watchlist"


def load_registry() -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(MODELS.read_text(encoding="utf-8")))


def _license_by_model(registry: ModelRegistry) -> dict[str, str]:
    out: dict[str, str] = {}
    for candidates in getattr(registry, "roles", {}).values():
        for c in candidates:
            if c.license and c.model not in out:
                out[c.model] = c.license
    return out


def gpu_budgets() -> dict[str, float]:
    """Every declared GPU VRAM budget, by environment name. Drives dual-budget fit
    (the 24 GB worker AND the 16 GB laptop). None of these is fabricated — each comes
    from configs/environments.yaml gpu_vram_gb."""
    try:
        cfg = EnvironmentsConfig.model_validate(
            yaml.safe_load(ENVIRONMENTS.read_text(encoding="utf-8"))
        )
    except FileNotFoundError:
        return {}
    return {env.name: float(env.gpu_vram_gb) for env in cfg.environments if env.gpu_vram_gb}


def gpu_budget_gb() -> float | None:
    """The PRIMARY (24 GB worker) budget for fit annotation. None if not declared."""
    return gpu_budgets().get(WORKER_ENV)


def laptop_budget_gb() -> float | None:
    """The SECONDARY (16 GB laptop) budget. None if the mobile node isn't declared."""
    return gpu_budgets().get(LAPTOP_ENV)


# ---- per-source fetchers (each returns normalized candidate dicts) ----------

def fetch_aider_polyglot() -> list[dict[str, Any]]:
    """Aider polyglot coding leaderboard -> candidates ranked by pass_rate_2.

    This source does not declare whether rows are open-weight, so the open-weight
    feed filters them out unless another source supplies explicit provenance.
    """
    r = httpx.get(AIDER_POLYGLOT_URL, timeout=30, follow_redirects=True)
    r.raise_for_status()
    rows = yaml.safe_load(r.text)
    if not isinstance(rows, list):
        raise RuntimeError("aider polyglot leaderboard is not a YAML list")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or "model" not in row:
            continue
        out.append({
            "id": str(row["model"]),
            "name": str(row["model"]),
            "source": "aider-polyglot",
            "source_url": AIDER_POLYGLOT_URL,
            "source_metric": "pass_rate_2",
            "source_score": row.get("pass_rate_2"),
            "coding_score": row.get("pass_rate_2"),
            "candidate_roles": ["coder"],
            "edit_format": row.get("edit_format"),
            "ollama_tag": None,
            "open_weight": None,
            "open_weight_evidence": "aider-polyglot does not publish open-weight status",
            "license": None,
        })
    return out


def fetch_ollama_local() -> list[dict[str, Any]]:
    """Installed Ollama models -> candidates that are guaranteed runnable."""
    out: list[dict[str, Any]] = []
    for rec in sorted(vram.ollama_tag_records(), key=lambda r: str(r.get("name", ""))):
        name = rec.get("name")
        if not name:
            continue
        details = rec.get("details") if isinstance(rec.get("details"), dict) else {}
        out.append({
            "id": str(name),
            "name": str(name),
            "source": "local-ollama-tags",
            "source_url": "ollama:/api/tags",
            "source_metric": None,
            "source_score": None,
            "coding_score": None,
            "candidate_roles": [],
            "edit_format": None,
            "ollama_tag": str(name),
            "open_weight": True,
            "open_weight_evidence": "model weights are installed locally and listed by Ollama /api/tags",
            "license": None,
            "digest": rec.get("digest"),
            "size_bytes": rec.get("size"),
            "parameter_size": details.get("parameter_size"),
            "quant": details.get("quantization_level"),
        })
    return out


def _tag_records_by_name(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for rec in records:
        name = rec.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("Ollama /api/tags record missing name")
        if name in by_name:
            raise RuntimeError(f"Ollama /api/tags returned duplicate model tag {name!r}")
        by_name[name] = rec
    return by_name


def _details(rec: dict[str, Any], tag: str) -> dict[str, Any]:
    details = rec.get("details")
    if not isinstance(details, dict):
        raise RuntimeError(f"Ollama tag {tag!r} has no details mapping")
    return details


def _assert_equal(label: str, expected: Any, observed: Any, tag: str) -> None:
    if expected != observed:
        raise RuntimeError(
            f"curated-openweight identity mismatch for {tag!r}: "
            f"{label} expected {expected!r}, observed {observed!r}"
        )


def _validate_roles(registry: ModelRegistry, record_id: str, roles: list[str]) -> None:
    known = set(registry.roles)
    unknown = [role for role in roles if role not in known]
    if unknown:
        raise RuntimeError(
            f"curated-openweight record {record_id!r} declares unknown candidate_roles {unknown}"
        )


def fetch_curated_openweight() -> list[dict[str, Any]]:
    """Versioned, strict source for scored open-weight candidates.

    This source is intentionally small and local. It joins a curated public
    benchmark record to the exact installed Ollama tag/digest, and fails loudly
    on any mismatch instead of guessing by display name.
    """
    raw = yaml.safe_load(CURATED_OPENWEIGHT.read_text(encoding="utf-8"))
    cfg = CuratedModelScoutConfig.model_validate(raw)
    registry = load_registry()
    licenses = _license_by_model(registry)
    local = _tag_records_by_name(vram.ollama_tag_records())
    out: list[dict[str, Any]] = []
    for record in cfg.records:
        identity = record.identity
        benchmark = record.benchmark
        _validate_roles(registry, record.record_id, benchmark.candidate_roles)
        tag = identity.ollama_tag
        if tag not in local:
            raise RuntimeError(
                f"curated-openweight record {record.record_id!r} requires local tag {tag!r}"
            )
        rec = local[tag]
        details = _details(rec, tag)
        _assert_equal("ollama_digest", identity.ollama_digest, rec.get("digest"), tag)
        _assert_equal("parameter_size", identity.parameter_size,
                      details.get("parameter_size"), tag)
        _assert_equal("quantization", identity.quantization,
                      details.get("quantization_level"), tag)
        if identity.context_length is not None:
            _assert_equal("context_length", identity.context_length,
                          details.get("context_length"), tag)
        configured_license = licenses.get(tag)
        if configured_license is not None and configured_license != identity.license:
            raise RuntimeError(
                f"curated-openweight identity mismatch for {tag!r}: license expected "
                f"{identity.license!r}, configs/models.yaml has {configured_license!r}"
            )
        out.append({
            "id": tag,
            "name": tag,
            "source": "curated-openweight",
            "source_url": benchmark.source_url,
            "source_metric": benchmark.metric,
            "source_score": benchmark.score,
            "coding_score": benchmark.score if "coder" in benchmark.candidate_roles else None,
            "candidate_roles": list(benchmark.candidate_roles),
            "edit_format": None,
            "ollama_tag": tag,
            "open_weight": True,
            "open_weight_evidence": record.open_weight_evidence,
            "license": identity.license,
            "digest": rec.get("digest"),
            "size_bytes": rec.get("size"),
            "parameter_size": details.get("parameter_size"),
            "quant": details.get("quantization_level"),
            "native_context": details.get("context_length"),
            "model_family": identity.model_family,
            "release_id": identity.release_id,
            "source_model_id": identity.source_model_id,
            "source_model_url": identity.source_model_url,
            "source_model_payload_sha256": identity.source_model_payload_sha256,
            "benchmark_name": benchmark.name,
            "benchmark_version": benchmark.version,
            "score_definition": benchmark.score_definition,
            "evaluation_date": benchmark.evaluation_date,
            "retrieval_timestamp": benchmark.retrieval_timestamp,
            "source_payload_sha256": benchmark.source_payload_sha256,
        })
    return out


def fetch_artificial_analysis() -> list[dict[str, Any]]:
    """OPTIONAL AA Data API (open-weights only). Empty unless AA_API_KEY is set.

    AA supplies an ollama_tag string verbatim. We do NOT trust it: a tag is only kept
    when it actually resolves against the local /api/tags install (the same posture as
    curated-openweight). An unresolved tag is dropped to None so AA can never draft an
    unrunnable local benchmark — the model survives as a discovery signal, not a local
    A/B candidate. (Identity is only confirmed by curated-openweight's full digest join.)"""
    key = os.environ.get("AA_API_KEY")
    if not key:
        return []
    r = httpx.get(ARTIFICIAL_ANALYSIS_URL, headers={"x-api-key": key}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    try:
        installed = set(vram.ollama_tags())
    except vram.VramError:
        installed = set()
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("is_open_weights"):
            continue
        claimed_tag = row.get("ollama_tag")
        verified_tag = claimed_tag if (claimed_tag and claimed_tag in installed) else None
        evidence = "Artificial Analysis row has is_open_weights=true"
        if claimed_tag and not verified_tag:
            evidence += (f"; ollama_tag {claimed_tag!r} NOT verified against local "
                         "/api/tags (dropped — not a local A/B candidate)")
        out.append({
            "id": str(row.get("slug") or row.get("name")),
            "name": str(row.get("name")),
            "source": "artificial-analysis",
            "source_url": ARTIFICIAL_ANALYSIS_URL,
            "source_metric": "coding_index",
            "source_score": (row.get("evaluations") or {}).get("coding_index"),
            "coding_score": (row.get("evaluations") or {}).get("coding_index"),
            "candidate_roles": ["coder"],
            "edit_format": None,
            "ollama_tag": verified_tag,
            "ollama_tag_unverified": claimed_tag if not verified_tag else None,
            "open_weight": True,
            "open_weight_evidence": evidence,
            "license": row.get("license") or row.get("model_license"),
        })
    return out


FETCHERS = {
    "aider-polyglot": fetch_aider_polyglot,
    "local-ollama-tags": fetch_ollama_local,
    "curated-openweight": fetch_curated_openweight,
    "artificial-analysis": fetch_artificial_analysis,
}


# ---- watchlist: un-pulled frontier / pull-to-verify models (track-as-context) ----------

# A 256 GB-class unified-memory machine is the reference target on which the biggest dynamic
# quants "run (slowly)". It is NOT one of this operator's machines and is promotion-disallowed;
# it exists only to give a frontier model an honest "where could this even run" verdict.
REFERENCE_LARGE_MEM_GB = 256.0


def _watchlist_footprint(record) -> tuple[float, str]:
    """The honest memory footprint of a watchlist model, in GB, with its source.

    Prefer a VERIFIED published artifact size (e.g. Unsloth's ~238 GB GLM-5.2 dynamic 2-bit) —
    authoritative. Otherwise fall back to the params×quantized-bpw LOWER bound (real files run
    larger), which is still trustworthy for a hard 'too big' verdict."""
    art = getattr(record, "local_artifact", None)
    if art is not None:
        return float(art.smallest_verified_size_gb), "verified_artifact"
    return vram.weights_gb_from_bpw(record.parameter_count_b, record.reference_quant), \
        "weights_only_bound"


def _named_gpu_verdict(footprint_gb: float, budget_gb: float, source: str) -> str:
    """Named fit verdict for a GPU budget. Never a fabricated positive — a footprint that
    clears the floor is 'unknown_pull_to_verify' (KV/real-file unknown), not a FITS."""
    usable = budget_gb / (1.0 + vram.SAFETY_HEADROOM_FRAC) - vram.CUDA_BASELINE_GB
    if footprint_gb > usable:
        return "does_not_fit"
    return "unknown_pull_to_verify"


def _runnable_targets(record) -> dict[str, str]:
    """Named verdict per declared hardware target: the 24 GB worker, the 16 GB laptop, and the
    256 GB-class unified-memory reference (where the biggest dynamic quants run, slowly)."""
    footprint, source = _watchlist_footprint(record)
    ref = ("ram_only_frontier_experiment"
           if footprint <= REFERENCE_LARGE_MEM_GB else "does_not_fit")
    return {
        "cc_worker_4090_24gb": _named_gpu_verdict(footprint, 24.0, source),
        "laptop_5080_16gb": _named_gpu_verdict(footprint, 16.0, source),
        "ram_256gb_class": ref,
        "footprint_gb": round(footprint, 1),
        "footprint_source": source,
    }


def _watchlist_fit(record, budget_gb: float | None, installed: set[str]) -> str:
    """Honest fit string for ONE watchlist record at ONE budget. Never fabricates a FITS.

    Installed (rare for a watchlist entry) -> the real KV-aware estimate. Otherwise: a verified
    published artifact size if present (hard NO when it blows the budget), else the weights-only
    LOWER bound. The frontier case (GLM-5.2 ~238 GB, Kimi ~540 GB) is a decisive NO either way."""
    if budget_gb is None:
        return "n/a (no budget configured)"
    tag = record.ollama_tag
    if record.ollama_local and tag and tag in installed:
        try:
            est = vram.estimate_installed(tag, ctx=DEFAULT_FIT_CTX, budget_gb=budget_gb)
        except vram.VramError as exc:
            return f"unknown ({exc})"
        verdict = "FITS" if est.fits else "NO"
        return f"{verdict} @ {DEFAULT_FIT_CTX // 1024}k (max {est.max_ctx_fits // 1024}k)"
    art = getattr(record, "local_artifact", None)
    if art is not None:
        usable = budget_gb / (1.0 + vram.SAFETY_HEADROOM_FRAC) - vram.CUDA_BASELINE_GB
        size = float(art.smallest_verified_size_gb)
        if size > usable:
            return (f"NO @ {budget_gb:g}GB (verified {art.quant} artifact ~{size:g}GB "
                    f"> usable ~{usable:.1f}GB)")
        return (f"unknown - pull to verify (verified {art.quant} artifact ~{size:g}GB "
                f"fits the {budget_gb:g}GB floor; KV not yet sized)")
    try:
        lb = vram.weights_only_verdict(
            params_b=record.parameter_count_b, quant=record.reference_quant,
            budget_gb=budget_gb)
    except vram.VramError as exc:
        return f"unknown ({exc})"
    return lb.verdict


def fetch_watchlist(registry: ModelRegistry, *, installed: set[str],
                    budget_24gb: float | None,
                    budget_16gb: float | None) -> list[dict[str, Any]]:
    """Read the version-controlled watchlist of un-pulled open-weight models and annotate
    each with an honest dual-budget fit. This is the source that lets GLM-5.2 / Kimi K2 be
    'checked on' by name without downloading them. Pull-to-verify roles are validated against
    the live registry (a typo'd role fails loud, like curated-openweight)."""
    raw = yaml.safe_load(WATCHLIST.read_text(encoding="utf-8"))
    cfg = ModelWatchlistConfig.model_validate(raw)
    known_roles = set(getattr(registry, "roles", {}))
    out: list[dict[str, Any]] = []
    for rec in cfg.records:
        if rec.tier == "pull_to_verify":
            unknown = [r for r in rec.candidate_roles if r not in known_roles]
            if unknown:
                raise RuntimeError(
                    f"watchlist record {rec.record_id!r} declares unknown "
                    f"candidate_roles {unknown}")
        out.append({
            "record_id": rec.record_id,
            "tier": rec.tier,
            "id": rec.ollama_tag or rec.release_id,
            "model": rec.release_id,
            "model_family": rec.model_family,
            "release_id": rec.release_id,
            "source": WATCHLIST_SOURCE,
            "source_url": rec.source_url,
            "source_model_url": rec.source_model_url,
            "parameter_count_b": rec.parameter_count_b,
            "active_param_count_b": rec.active_param_count_b,
            "is_moe": rec.is_moe,
            "reference_quant": rec.reference_quant,
            "context_length": rec.context_length,
            "license": rec.license,
            "open_weight": True,
            "open_weight_evidence": rec.open_weight_evidence,
            "ollama_tag": rec.ollama_tag,
            "ollama_local": rec.ollama_local,
            "candidate_roles": list(rec.candidate_roles),
            "benchmark_name": rec.benchmark.name if rec.benchmark else None,
            "benchmark_metric": rec.benchmark.metric if rec.benchmark else None,
            "benchmark_score": rec.benchmark.score if rec.benchmark else None,
            "retrieval_timestamp": rec.retrieval_timestamp,
            "notes": rec.notes,
            "smallest_verified_size_gb": (
                rec.local_artifact.smallest_verified_size_gb if rec.local_artifact else None),
            "local_artifact_quant": rec.local_artifact.quant if rec.local_artifact else None,
            "fit_24gb": _watchlist_fit(rec, budget_24gb, installed),
            "fit_16gb": _watchlist_fit(rec, budget_16gb, installed),
            "runnable_targets": _runnable_targets(rec),
        })
    return out


def gather_watchlist(registry: ModelRegistry, *, offline: bool,
                     installed: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Run the watchlist track if `model-watchlist` is a configured source. Returns
    (records, errors). Runs even offline — the weights-only fit needs no Ollama; only the
    rare installed-model path uses `installed` (empty offline)."""
    scout = registry.scout
    if not scout or WATCHLIST_SOURCE not in scout.sources:
        return [], []
    try:
        records = fetch_watchlist(
            registry, installed=installed,
            budget_24gb=gpu_budget_gb(), budget_16gb=laptop_budget_gb())
    except (RuntimeError, OSError, ValueError) as exc:
        return [], [f"{WATCHLIST_SOURCE}: {exc}"]
    return records, []


def watchlist_feed_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert watchlist records into daily-scan feed records. frontier_watch ->
    'frontier_watch' (track-as-context; never a local benchmark). pull_to_verify ->
    'model_pull_candidate' (a propose-only pull + local A/B for the declared role)."""
    out: list[dict[str, Any]] = []
    for r in records:
        record_type = (
            "frontier_watch" if r["tier"] == "frontier_watch" else "model_pull_candidate")
        out.append({
            "record_type": record_type,
            "tier": r["tier"],
            "model": r["model"],
            "model_family": r["model_family"],
            "release_id": r["release_id"],
            "provider": "ollama" if r.get("ollama_local") else "open-weight",
            "open_weight": True,
            "open_weight_evidence": r["open_weight_evidence"],
            "license": r["license"],
            "parameter_count_b": r["parameter_count_b"],
            "active_param_count_b": r["active_param_count_b"],
            "is_moe": r["is_moe"],
            "context_length": r["context_length"],
            "ollama_tag": r["ollama_tag"],
            "ollama_local": r["ollama_local"],
            "candidate_roles": r["candidate_roles"],
            "fit_24gb": r["fit_24gb"],
            "fit_16gb": r["fit_16gb"],
            "runnable_targets": r.get("runnable_targets"),
            "smallest_verified_size_gb": r.get("smallest_verified_size_gb"),
            "source": WATCHLIST_SOURCE,
            "source_url": r["source_url"],
            "source_model_url": r["source_model_url"],
            "retrieval_timestamp": r["retrieval_timestamp"],
            "notes": r["notes"],
        })
    return out


# ---- fit annotation (WS1 gate) ---------------------------------------------

def annotate_fit(candidate: dict[str, Any], budget_gb: float | None, ctx: int,
                 installed: set[str]) -> str:
    """Real VRAM verdict for a candidate, or an honest 'unknown'. No fabrication."""
    if budget_gb is None:
        return "n/a (no gpu_vram_gb configured)"
    tag = candidate.get("ollama_tag")
    if not tag or tag not in installed:
        return "unknown - pull to verify"
    try:
        est = vram.estimate_installed(tag, ctx=ctx, budget_gb=budget_gb)
    except vram.VramError as exc:
        return f"unknown ({exc})"
    verdict = "FITS" if est.fits else "NO"
    return f"{verdict} @ {ctx//1024}k (max {est.max_ctx_fits//1024}k, {est.headroom_gb:.1f}G free)"


def enrich_candidate(candidate: dict[str, Any], registry: ModelRegistry, *,
                     budget_gb: float | None, ctx: int, installed: set[str]) -> dict[str, Any]:
    """Attach local provenance without inventing missing values."""
    out = dict(candidate)
    tag = out.get("ollama_tag")
    if not out.get("license") and tag:
        out["license"] = _license_by_model(registry).get(str(tag))
    out["vram_fit"] = annotate_fit(out, budget_gb, ctx, installed)
    if tag and tag in installed and budget_gb is not None:
        try:
            est = vram.estimate_installed(str(tag), ctx=ctx, budget_gb=budget_gb)
        except vram.VramError as exc:
            out["provenance_error"] = str(exc)
        else:
            out["vram"] = est.to_dict()
            out.setdefault("quant", est.quant)
            out.setdefault("params_b", est.params_b)
            out["native_context"] = est.native_ctx
            out["max_ctx_fits"] = est.max_ctx_fits
            out["headroom_gb"] = est.headroom_gb
    return out


SUITE_PATH = "configs/model-benchmarks.yaml"
DEFAULT_BASE_URL_ENV = "OLLAMA_API_BASE"


def _resolve_model_benchmark(candidate: dict[str, Any], roles: list[str],
                             registry: ModelRegistry | None) -> dict[str, Any] | None:
    """Bind a runnable live-A/B parameter block for a scored candidate, when possible.

    Needs the registry (to look up the role incumbent as the baseline) and a real Ollama tag.
    Returns None — leaving the drafted card a 'needs-params' proposal — when the candidate is
    not bindable (no registry, no tag, role has no incumbent, or the candidate IS the
    incumbent). Never fabricates a model: baseline is the configured priority-1 incumbent."""
    if registry is None:
        return None
    tag = candidate.get("ollama_tag")
    if not tag:
        return None
    role = str(roles[0])
    inc = primary_models(registry).get(role)
    if inc is None or not getattr(inc, "local", False) or inc.model == tag:
        return None
    mb: dict[str, Any] = {
        "role": role,
        "suite": role,
        "suite_path": SUITE_PATH,
        "baseline_model": inc.model,
        "candidate_model": str(tag),
        "base_url_env": DEFAULT_BASE_URL_ENV,
    }
    if candidate.get("max_ctx_fits"):
        mb["context_length"] = int(candidate["max_ctx_fits"])
    return mb


def discovery_feed_records(candidates: list[dict[str, Any]],
                           registry: ModelRegistry | None = None) -> list[dict[str, Any]]:
    """Convert scored open-weight scout candidates into daily-scan feed records.

    Unscored local tags are intentionally omitted: being installed is useful
    provenance, not evidence that the model is better. When `registry` is supplied, a
    runnable `model_benchmark` block is bound (role/suite/incumbent/candidate/endpoint) so the
    drafted MODEL card can advance past Proposed on its own; otherwise the card stays a
    'needs-params' proposal a human completes.
    """
    records: list[dict[str, Any]] = []
    for c in candidates:
        if c.get("open_weight") is not True or c.get("coding_score") is None:
            continue
        roles = c.get("candidate_roles")
        if not isinstance(roles, list) or not roles:
            raise RuntimeError(
                f"scored model candidate {c.get('id')!r} must declare candidate_roles")
        records.append({
            "record_type": "model_scout_candidate",
            "model": c["id"],
            "model_benchmark": _resolve_model_benchmark(c, roles, registry),
            "provider": "ollama" if c.get("ollama_tag") else c.get("source", "unknown"),
            "metric": "coding_score",
            "candidate": c["coding_score"],
            "direction": "increase",
            "source": "model-scout",
            "source_name": c.get("source"),
            "source_url": c.get("source_url"),
            "candidate_roles": [str(role) for role in roles],
            "open_weight": True,
            "open_weight_evidence": c.get("open_weight_evidence"),
            "license": c.get("license"),
            "ollama_tag": c.get("ollama_tag"),
            "digest": c.get("digest"),
            "quant": c.get("quant"),
            "native_context": c.get("native_context"),
            "parameter_size": c.get("parameter_size"),
            "params_b": c.get("params_b"),
            "vram_fit": c.get("vram_fit"),
            "model_family": c.get("model_family"),
            "release_id": c.get("release_id"),
            "source_model_id": c.get("source_model_id"),
            "source_model_url": c.get("source_model_url"),
            "source_model_payload_sha256": c.get("source_model_payload_sha256"),
            "benchmark_name": c.get("benchmark_name"),
            "benchmark_version": c.get("benchmark_version"),
            "score_definition": c.get("score_definition"),
            "evaluation_date": c.get("evaluation_date"),
            "retrieval_timestamp": c.get("retrieval_timestamp"),
            "source_payload_sha256": c.get("source_payload_sha256"),
        })
    return records


# ---- report rendering -------------------------------------------------------

def incumbent_cost_text(model: Any) -> str:
    if model.local:
        return "local/free"
    if model.monthly_budget_usd is not None:
        return f"budget ${model.monthly_budget_usd:g}/mo"
    return f"{model.provider} pricing not encoded"


def primary_models(registry: ModelRegistry) -> dict[str, Any]:
    return {
        role: sorted(candidates, key=lambda c: c.priority)[0]
        for role, candidates in registry.roles.items()
    }


def _cell(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value)
    return text.replace("|", "\\|")


def _short_digest(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value)
    return text[:16]


def render_report(registry: ModelRegistry, candidates: list[dict[str, Any]],
                  errors: list[str], notes: list[str], budget_gb: float | None,
                  ctx: int, installed: set[str], *, open_weight_only: bool = True,
                  watchlist: list[dict[str, Any]] | None = None,
                  laptop_budget: float | None = None) -> str:
    scout = registry.scout
    watchlist = watchlist or []
    generated_at = datetime.now(timezone.utc).isoformat()
    incumbents = primary_models(registry)
    lines = [
        "# Model Scout Report",
        "",
        f"Generated: `{generated_at}`",
        f"Cadence: `{scout.cadence if scout else 'not configured'}`",
        f"GPU budget (primary {WORKER_ENV}): "
        + (f"`{budget_gb:g} GB`" if budget_gb else "`not configured`"),
        f"GPU budget (laptop {LAPTOP_ENV}): "
        + (f"`{laptop_budget:g} GB`" if laptop_budget else "`not configured`"),
        "",
        "Policy: propose-only. This report does not edit configs or promote models.",
        ("Open-weight filter: enabled; candidates without explicit/local weight "
         "evidence are not emitted to the daily-scan feed."
         if open_weight_only else
         "Open-weight filter: disabled for this report; the daily-scan feed still "
         "emits only scored candidates with open-weight evidence."),
        "",
        "## Sources",
        "",
    ]
    lines += [f"- {s}" for s in (scout.sources if scout else [])]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    if errors:
        lines += ["", "## Source Errors", ""] + [f"- {e}" for e in errors]

    lines += [
        "",
        "## Incumbent Snapshot (with current fit)",
        "",
        "| role | incumbent | license | VRAM fit | cost |",
        "| --- | --- | --- | --- | --- |",
    ]
    for role, model in sorted(incumbents.items()):
        fit = annotate_fit({"ollama_tag": model.model}, budget_gb, ctx, installed) \
            if model.local else "hosted"
        lines.append(
            f"| `{role}` | `{model.alias}` / `{model.provider}:{model.model}` | "
            f"{model.license or 'unknown'} | {fit} | {incumbent_cost_text(model)} |"
        )

    lines += [
        "",
        f"## Candidate Shortlist ({'open-weight, ' if open_weight_only else ''}top by coding score; fit @ ctx={ctx//1024}k)",
        "",
        "| rank | candidate | source | coding | license | ollama_tag | digest | params | ctx | quant | VRAM fit |",
        "| ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    if not candidates:
        lines.append("| - | no open-weight scored candidates (run online; check source errors) | - | - | - | - | - | - | - | - | - |")
    for i, c in enumerate(candidates, start=1):
        score = c["coding_score"]
        score_txt = f"{score}" if score is not None else "n/a"
        lines.append(
            f"| {i} | `{_cell(c['id'])}` | {_cell(c['source'])} | {score_txt} | "
            f"{_cell(c.get('license'))} | `{_cell(c.get('ollama_tag'))}` | "
            f"{_short_digest(c.get('digest'))} | {_cell(c.get('parameter_size') or c.get('params_b'))} | "
            f"{_cell(c.get('native_context'))} | {_cell(c.get('quant'))} | {_cell(c.get('vram_fit'))} |"
        )

    evidence_candidates = [
        c for c in candidates
        if c.get("benchmark_name") or c.get("source_payload_sha256")
    ]
    if evidence_candidates:
        lines += [
            "",
            "## Candidate Source Evidence",
            "",
            "| candidate | roles | benchmark | source | retrieved | payload hash | release | model card hash |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for c in evidence_candidates:
            roles = ",".join(str(role) for role in c.get("candidate_roles", []))
            benchmark = " ".join(
                str(x) for x in (c.get("benchmark_name"), c.get("benchmark_version"))
                if x
            )
            source = c.get("source_url") or "unknown"
            lines.append(
                f"| `{_cell(c['id'])}` | {_cell(roles)} | {_cell(benchmark)} | "
                f"{_cell(source)} | {_cell(c.get('retrieval_timestamp'))} | "
                f"{_short_digest(c.get('source_payload_sha256'))} | "
                f"{_cell(c.get('release_id'))} | "
                f"{_short_digest(c.get('source_model_payload_sha256'))} |"
            )

    if watchlist:
        frontier = [w for w in watchlist if w["tier"] == "frontier_watch"]
        pull = [w for w in watchlist if w["tier"] == "pull_to_verify"]
        lines += [
            "",
            "## Frontier & Watchlist (tracked, fit-checked, NOT benchmarked locally)",
            "",
            "Open-weight models we track by name without installing them. Fit is honest: a "
            "weights-only LOWER bound for un-pulled models (real files run larger), never a "
            "fabricated FITS. Frontier rows are too large for this hardware and are never "
            "routed to a local benchmark; pull-to-verify rows are propose-only pull + A/B "
            "candidates. Public benchmark numbers here are CONTEXT, not promotion evidence.",
            "",
            "| tier | model | family | params (total/active) | license | fit @24GB | fit @16GB |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for w in frontier + pull:
            active = f"{w['parameter_count_b']:g}B"
            if w.get("active_param_count_b"):
                active += f" / {w['active_param_count_b']:g}B act"
            lines.append(
                f"| {_cell(w['tier'])} | `{_cell(w['model'])}` | {_cell(w['model_family'])} | "
                f"{active} | {_cell(w['license'])} | {_cell(w['fit_24gb'])} | "
                f"{_cell(w['fit_16gb'])} |"
            )

    lines += [
        "",
        "## Promotion Gate",
        "",
        "1. Pull/verify a candidate with a real Ollama tag if the tag is not already present.",
        "2. Register a bounded model benchmark experiment; do not edit production routing.",
        "3. Run baseline + candidate + independent verification; artifacts land in Ledger.",
        "4. Only after verification, manually canary with `make models-canary ROLE=... MODEL=ollama_chat/<tag>`.",
        "5. Promote or roll back manually after canary telemetry.",
    ]
    return "\n".join(lines) + "\n"


def gather(registry: ModelRegistry, *, offline: bool, ctx: int,
           open_weight_only: bool = True,
           max_candidates: int) -> tuple[list[dict[str, Any]], list[str], list[str], set[str]]:
    """Run each configured source's fetcher; collect candidates, errors, notes."""
    sources = registry.scout.sources if registry.scout else []
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    notes: list[str] = []
    installed: set[str] = set()

    # installed tags are needed for fit annotation regardless of source list
    if not offline:
        try:
            installed = set(vram.ollama_tags())
        except vram.VramError as exc:
            notes.append(f"Ollama unreachable; fit shown as unknown ({exc})")

    for source in sources:
        if source not in KNOWN_SOURCES:
            errors.append(f"{source}: unknown source (known: {sorted(KNOWN_SOURCES)})")
            continue
        if source == WATCHLIST_SOURCE:
            continue   # handled on its own track by gather_watchlist (runs even offline)
        if offline:
            notes.append(f"{source}: skipped (offline)")
            continue
        try:
            found = FETCHERS[source]()
            if source == "artificial-analysis" and not found and not os.environ.get("AA_API_KEY"):
                notes.append("artificial-analysis: skipped (no AA_API_KEY; optional tiebreaker)")
            candidates += found
        except (httpx.HTTPError, RuntimeError) as exc:
            errors.append(f"{source}: {exc}")

    if open_weight_only:
        before = len(candidates)
        candidates = [c for c in candidates if c.get("open_weight") is True]
        dropped = before - len(candidates)
        if dropped:
            notes.append(
                f"open-weight filter: omitted {dropped} candidate(s) without explicit/local weight evidence"
            )

    budget = gpu_budget_gb()
    candidates = [
        enrich_candidate(c, registry, budget_gb=budget, ctx=ctx, installed=installed)
        for c in candidates
    ]
    if open_weight_only:
        before = len(candidates)
        candidates = [
            c for c in candidates
            if c.get("source") != "local-ollama-tags" or "vram" in c or budget is None
        ]
        dropped = before - len(candidates)
        if dropped:
            notes.append(
                f"causal-LM filter: omitted {dropped} local tag(s) without required attention metadata"
            )
    # rank: models with a coding score first (desc), runnable-but-unscored after
    candidates.sort(key=lambda c: (c["coding_score"] is None, -(c["coding_score"] or 0)))
    return candidates[:max_candidates], errors, notes, installed


def scan_feed_records(*, offline: bool = False, ctx: int = DEFAULT_FIT_CTX) -> list[dict[str, Any]]:
    """The daily-scan model feed: runnable scored candidates + watchlist records, in the
    `litellm_registry` shape the scan's ModelRegistryScanner consumes. Single source of truth
    shared by the CLI (`make model-scout-scan`) and the Airflow DAG ingestion task, so the
    scheduled run is never blind to new models. Propose-only by construction (it returns
    records; it never edits configs, pulls models, or promotes)."""
    registry = load_registry()
    if registry.scout is None:
        return []
    candidates, _errors, _notes, installed = gather(
        registry, offline=offline, ctx=ctx, open_weight_only=True,
        max_candidates=registry.scout.max_candidates_per_run)
    watchlist, _werrors = gather_watchlist(registry, offline=offline, installed=installed)
    return (discovery_feed_records(candidates, registry=registry)
            + watchlist_feed_records(watchlist))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ctx", type=int, default=DEFAULT_FIT_CTX)
    parser.add_argument("--json", action="store_true", help="write JSON instead of Markdown")
    parser.add_argument("--offline", action="store_true", help="only validate scout config")
    parser.add_argument(
        "--include-unverified-weights",
        action="store_true",
        help="include candidates whose source does not prove open/local weights",
    )
    parser.add_argument(
        "--feed-output",
        default="",
        help="write a daily-scan feeds JSON containing litellm_registry model-scout records",
    )
    args = parser.parse_args()

    registry = load_registry()
    if registry.scout is None:
        raise SystemExit("configs/models.yaml has no scout section")

    budget = gpu_budget_gb()
    laptop = laptop_budget_gb()
    generated_at = datetime.now(timezone.utc).isoformat()
    candidates, errors, notes, installed = gather(
        registry, offline=args.offline, ctx=args.ctx,
        open_weight_only=not args.include_unverified_weights,
        max_candidates=registry.scout.max_candidates_per_run,
    )
    watchlist, watch_errors = gather_watchlist(
        registry, offline=args.offline, installed=installed)
    errors += watch_errors
    # The feed the daily scan consumes: runnable scored candidates PLUS watchlist records
    # (frontier_watch = track-as-context; pull_to_verify = propose-only pull + A/B).
    feed_records = (discovery_feed_records(candidates, registry=registry)
                    + watchlist_feed_records(watchlist))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        out.write_text(json.dumps({
            "generated_at": generated_at,
            "sources": registry.scout.sources,
            "open_weight_only": not args.include_unverified_weights,
            "ctx": args.ctx,
            "gpu_budget_gb": budget,
            "laptop_budget_gb": laptop,
            "candidates": candidates,
            "watchlist": watchlist,
            "feed_records": feed_records,
            "notes": notes,
            "errors": errors,
        }, indent=2), encoding="utf-8")
    else:
        out.write_text(
            render_report(
                registry,
                candidates,
                errors,
                notes,
                budget,
                args.ctx,
                installed,
                open_weight_only=not args.include_unverified_weights,
                watchlist=watchlist,
                laptop_budget=laptop,
            ),
            encoding="utf-8",
        )
    if args.feed_output:
        feed_out = Path(args.feed_output)
        feed_out.parent.mkdir(parents=True, exist_ok=True)
        feed_out.write_text(
            json.dumps({"litellm_registry": feed_records}, indent=2),
            encoding="utf-8",
        )
    print(f"wrote {out}")
    if args.feed_output:
        print(f"wrote {args.feed_output}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

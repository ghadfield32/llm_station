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
    CuratedModelScoutConfig,
    EnvironmentsConfig,
    ModelRegistry,
)

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "configs" / "models.yaml"
ENVIRONMENTS = ROOT / "configs" / "environments.yaml"
DEFAULT_OUTPUT = ROOT / "generated" / "model-scout-report.md"
CURATED_OPENWEIGHT = ROOT / "configs" / "model-scout-curated-openweight.yaml"

AIDER_POLYGLOT_URL = (
    "https://raw.githubusercontent.com/Aider-AI/aider/main/"
    "aider/website/_data/polyglot_leaderboard.yml"
)
ARTIFICIAL_ANALYSIS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
DEFAULT_FIT_CTX = 65536
WORKER_ENV = "cc-worker-4090"

KNOWN_SOURCES = {
    "aider-polyglot", "local-ollama-tags", "curated-openweight", "artificial-analysis",
}


def load_registry() -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(MODELS.read_text(encoding="utf-8")))


def _license_by_model(registry: ModelRegistry) -> dict[str, str]:
    out: dict[str, str] = {}
    for candidates in getattr(registry, "roles", {}).values():
        for c in candidates:
            if c.license and c.model not in out:
                out[c.model] = c.license
    return out


def gpu_budget_gb() -> float | None:
    """Total VRAM of the GPU worker, for fit annotation. None if not declared."""
    try:
        cfg = EnvironmentsConfig.model_validate(
            yaml.safe_load(ENVIRONMENTS.read_text(encoding="utf-8"))
        )
    except FileNotFoundError:
        return None
    for env in cfg.environments:
        if env.name == WORKER_ENV:
            return float(env.gpu_vram_gb) if env.gpu_vram_gb else None
    return None


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
    """OPTIONAL AA Data API (open-weights only). Empty unless AA_API_KEY is set."""
    key = os.environ.get("AA_API_KEY")
    if not key:
        return []
    r = httpx.get(ARTIFICIAL_ANALYSIS_URL, headers={"x-api-key": key}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("is_open_weights"):
            continue
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
            "ollama_tag": row.get("ollama_tag"),
            "open_weight": True,
            "open_weight_evidence": "Artificial Analysis row has is_open_weights=true",
            "license": row.get("license") or row.get("model_license"),
        })
    return out


FETCHERS = {
    "aider-polyglot": fetch_aider_polyglot,
    "local-ollama-tags": fetch_ollama_local,
    "curated-openweight": fetch_curated_openweight,
    "artificial-analysis": fetch_artificial_analysis,
}


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


def discovery_feed_records(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert scored open-weight scout candidates into daily-scan feed records.

    Unscored local tags are intentionally omitted: being installed is useful
    provenance, not evidence that the model is better.
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
                  ctx: int, installed: set[str], *, open_weight_only: bool = True) -> str:
    scout = registry.scout
    generated_at = datetime.now(timezone.utc).isoformat()
    incumbents = primary_models(registry)
    lines = [
        "# Model Scout Report",
        "",
        f"Generated: `{generated_at}`",
        f"Cadence: `{scout.cadence if scout else 'not configured'}`",
        f"GPU budget: `{budget_gb:g} GB`" if budget_gb else "GPU budget: `not configured`",
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
    generated_at = datetime.now(timezone.utc).isoformat()
    candidates, errors, notes, installed = gather(
        registry, offline=args.offline, ctx=args.ctx,
        open_weight_only=not args.include_unverified_weights,
        max_candidates=registry.scout.max_candidates_per_run,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        out.write_text(json.dumps({
            "generated_at": generated_at,
            "sources": registry.scout.sources,
            "open_weight_only": not args.include_unverified_weights,
            "ctx": args.ctx,
            "gpu_budget_gb": budget,
            "candidates": candidates,
            "feed_records": discovery_feed_records(candidates),
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
            ),
            encoding="utf-8",
        )
    if args.feed_output:
        feed_out = Path(args.feed_output)
        feed_out.parent.mkdir(parents=True, exist_ok=True)
        feed_out.write_text(
            json.dumps({"litellm_registry": discovery_feed_records(candidates)}, indent=2),
            encoding="utf-8",
        )
    print(f"wrote {out}")
    if args.feed_output:
        print(f"wrote {args.feed_output}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

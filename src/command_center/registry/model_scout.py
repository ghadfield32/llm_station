#!/usr/bin/env python3
"""Generate a model-scout report from configured discovery sources.

The scout is deliberately propose-only. It can discover candidates and write a
report, but it never edits `configs/models.yaml` and never promotes a model.
Promotion remains: YAML edit -> validate -> canary -> evals -> human approval.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from command_center.schemas import ModelRegistry


ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "configs" / "models.yaml"
DEFAULT_OUTPUT = ROOT / "generated" / "model-scout-report.md"
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"


def load_registry() -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(MODELS.read_text(encoding="utf-8")))


def fetch_openrouter() -> list[dict[str, Any]]:
    response = httpx.get(OPENROUTER_MODELS, timeout=30)
    response.raise_for_status()
    data = response.json()
    models = data.get("data", [])
    if not isinstance(models, list):
        raise RuntimeError("OpenRouter model API returned an unexpected shape")
    return [m for m in models if isinstance(m, dict)]


def score_model(model: dict[str, Any]) -> float:
    benchmarks = model.get("benchmarks") or {}
    aa = benchmarks.get("artificial_analysis") or {}
    design = benchmarks.get("design_arena") or []

    coding = float(aa.get("coding_index") or 0)
    agentic = float(aa.get("agentic_index") or 0)
    intelligence = float(aa.get("intelligence_index") or 0)
    design_bonus = 0.0
    if isinstance(design, list):
        for row in design:
            if not isinstance(row, dict):
                continue
            category = str(row.get("category", "")).lower()
            if category in {"codecategories", "fullstack", "website", "dataviz"}:
                rank = float(row.get("rank") or 100)
                design_bonus += max(0.0, 25.0 - rank)
    return coding * 2.0 + agentic * 1.2 + intelligence + design_bonus


def price_per_million(value: Any) -> float | None:
    try:
        return float(value) * 1_000_000
    except Exception:
        return None


def summarize_model(model: dict[str, Any]) -> dict[str, Any]:
    pricing = model.get("pricing") or {}
    aa = (model.get("benchmarks") or {}).get("artificial_analysis") or {}
    return {
        "id": model.get("id"),
        "name": model.get("name"),
        "hugging_face_id": model.get("hugging_face_id"),
        "license": model.get("license") or model.get("license_name"),
        "context_length": model.get("context_length"),
        "created": model.get("created"),
        "prompt_per_mtok": price_per_million(pricing.get("prompt")),
        "completion_per_mtok": price_per_million(pricing.get("completion")),
        "coding_index": aa.get("coding_index"),
        "agentic_index": aa.get("agentic_index"),
        "intelligence_index": aa.get("intelligence_index"),
        "score": score_model(model),
    }


def primary_models(registry: ModelRegistry) -> dict[str, Any]:
    return {
        role: sorted(candidates, key=lambda c: c.priority)[0]
        for role, candidates in registry.roles.items()
    }


def price_text(prompt: float | None, completion: float | None) -> str:
    def fmt(value: float | None) -> str:
        if value is None:
            return "n/a"
        if value == 0:
            return "free"
        return f"${value:.4f}/M"

    return f"{fmt(prompt)} in / {fmt(completion)} out"


def incumbent_cost_text(model: Any) -> str:
    if model.local:
        return "local/free"
    if model.monthly_budget_usd is not None:
        return f"budget ${model.monthly_budget_usd:g}/mo"
    return f"{model.provider} pricing not encoded"


def incumbent_label(model: Any) -> str:
    return f"{model.alias} ({model.provider}/{model.model})"


def candidate_vram_fit(candidate: dict[str, Any]) -> str:
    model_id = str(candidate.get("id") or "").lower()
    hf_id = str(candidate.get("hugging_face_id") or "").lower()
    if "ollama" in model_id:
        return "local tag; verify VRAM"
    if hf_id:
        return "unknown; check model card"
    return "hosted/no local VRAM"


def infer_candidate_role(candidate: dict[str, Any], incumbents: dict[str, Any]) -> str:
    model_id = str(candidate.get("id") or "").lower()
    text = " ".join([model_id, str(candidate.get("name") or "").lower()])
    if any(token in text for token in ("coder", "code", "glm", "kimi", "deepseek", "qwen")):
        return "open-heavy-coder" if "open-heavy-coder" in incumbents else "coder"
    if (candidate.get("prompt_per_mtok") or 9999) <= 1:
        return "triage" if "triage" in incumbents else next(iter(incumbents))
    return "planner" if "planner" in incumbents else next(iter(incumbents))


def render_report(registry: ModelRegistry, candidates: list[dict[str, Any]], errors: list[str]) -> str:
    scout = registry.scout
    generated_at = datetime.now(timezone.utc).isoformat()
    incumbents = primary_models(registry)
    lines = [
        "# Model Scout Report",
        "",
        f"Generated: `{generated_at}`",
        f"Cadence: `{scout.cadence if scout else 'not configured'}`",
        "",
        "Policy: propose-only. This report does not edit configs or promote models.",
        "",
        "## Sources",
        "",
    ]
    sources = scout.sources if scout else []
    lines += [f"- {source}" for source in sources]
    if errors:
        lines += ["", "## Source Errors", ""]
        lines += [f"- {error}" for error in errors]

    lines += [
        "",
        "## Incumbent Snapshot",
        "",
        "| role | incumbent | license | VRAM | cost context |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for role, model in sorted(incumbents.items()):
        vram = f"{model.vram_gb} GB" if model.vram_gb else "n/a"
        lines.append(
            f"| `{role}` | `{model.alias}` / `{model.provider}:{model.model}` | "
            f"{model.license or 'unknown'} | {vram} | {incumbent_cost_text(model)} |"
        )

    lines += [
        "",
        "## Candidate Shortlist",
        "",
        "| rank | suggested role | incumbent | candidate | license | VRAM fit | candidate price | coding | agentic | score |",
        "| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    if not candidates:
        lines.append("| - | - | - | no candidates available; run without `--offline` or review source errors | - | - | - | - | - | - |")
    for index, c in enumerate(candidates, start=1):
        role = infer_candidate_role(c, incumbents)
        incumbent = incumbents[role]
        lines.append(
            f"| {index} | `{role}` | {incumbent_label(incumbent)} | `{c['id']}` | "
            f"{c.get('license') or 'unknown'} | {candidate_vram_fit(c)} | "
            f"{price_text(c['prompt_per_mtok'], c['completion_per_mtok'])} vs {incumbent_cost_text(incumbent)} | "
            f"{c['coding_index'] or 'n/a'} | "
            f"{c['agentic_index'] or 'n/a'} | {c['score']:.1f} |"
        )

    lines += [
        "",
        "## Promotion Gate",
        "",
        "1. Edit `configs/models.yaml` with one candidate as a canary.",
        "2. Run `make validate`, `make render`, and `make evals`.",
        "3. Run `make models-canary ROLE=... MODEL=...`.",
        "4. Compare cost, latency, judge block quality, and rollback rate.",
        "5. Promote or roll back manually.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true", help="write JSON instead of Markdown")
    parser.add_argument("--offline", action="store_true", help="only validate scout config")
    args = parser.parse_args()

    registry = load_registry()
    if registry.scout is None:
        raise SystemExit("configs/models.yaml has no scout section")

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    if not args.offline and "openrouter-rankings" in registry.scout.sources:
        try:
            models = fetch_openrouter()
            candidates = [
                summarize_model(model)
                for model in models
                if model.get("id") and score_model(model) > 0
            ]
            candidates.sort(key=lambda c: c["score"], reverse=True)
            candidates = candidates[: registry.scout.max_candidates_per_run]
        except Exception as exc:
            errors.append(f"openrouter-rankings: {exc}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        incumbents = {
            role: {
                "alias": model.alias,
                "provider": model.provider,
                "model": model.model,
                "license": model.license,
                "vram_gb": model.vram_gb,
                "cost_context": incumbent_cost_text(model),
            }
            for role, model in primary_models(registry).items()
        }
        out.write_text(json.dumps({"incumbents": incumbents, "candidates": candidates, "errors": errors}, indent=2), encoding="utf-8")
    else:
        out.write_text(render_report(registry, candidates, errors), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

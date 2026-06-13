#!/usr/bin/env python3
"""Generate a model-scout report from configured discovery sources.

The scout is deliberately propose-only. It discovers candidate local models and
writes a report; it NEVER edits configs/models.yaml and never promotes. Promotion
stays: YAML edit -> validate -> canary -> evals -> human approval.

Discovery is keyless-first. Sources (declared in models.yaml `scout.sources`):
  - aider-polyglot     : Aider's polyglot coding leaderboard (public YAML, no key).
                         The coding-quality signal that ranks candidates.
  - local-ollama-tags  : models already installed via Ollama (guaranteed runnable).
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
from command_center.schemas import EnvironmentsConfig, ModelRegistry

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "configs" / "models.yaml"
ENVIRONMENTS = ROOT / "configs" / "environments.yaml"
DEFAULT_OUTPUT = ROOT / "generated" / "model-scout-report.md"

AIDER_POLYGLOT_URL = (
    "https://raw.githubusercontent.com/Aider-AI/aider/main/"
    "aider/website/_data/polyglot_leaderboard.yml"
)
ARTIFICIAL_ANALYSIS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
DEFAULT_FIT_CTX = 65536
WORKER_ENV = "cc-worker-4090"

KNOWN_SOURCES = {"aider-polyglot", "local-ollama-tags", "artificial-analysis"}


def load_registry() -> ModelRegistry:
    return ModelRegistry.model_validate(yaml.safe_load(MODELS.read_text(encoding="utf-8")))


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
    """Aider polyglot coding leaderboard -> candidates ranked by pass_rate_2."""
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
            "coding_score": row.get("pass_rate_2"),
            "edit_format": row.get("edit_format"),
            "ollama_tag": None,
        })
    return out


def fetch_ollama_local() -> list[dict[str, Any]]:
    """Installed Ollama models -> candidates that are guaranteed runnable."""
    tags = vram.ollama_tags()
    return [
        {"id": name, "name": name, "source": "local-ollama-tags",
         "coding_score": None, "edit_format": None, "ollama_tag": name}
        for name in sorted(tags)
    ]


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
            "coding_score": (row.get("evaluations") or {}).get("coding_index"),
            "edit_format": None,
            "ollama_tag": None,
        })
    return out


FETCHERS = {
    "aider-polyglot": fetch_aider_polyglot,
    "local-ollama-tags": fetch_ollama_local,
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


def render_report(registry: ModelRegistry, candidates: list[dict[str, Any]],
                  errors: list[str], notes: list[str], budget_gb: float | None,
                  ctx: int, installed: set[str]) -> str:
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
        f"## Candidate Shortlist (top by coding score; fit @ ctx={ctx//1024}k)",
        "",
        "| rank | candidate | source | coding | VRAM fit |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    if not candidates:
        lines.append("| - | no candidates (run online; check source errors) | - | - | - |")
    for i, c in enumerate(candidates, start=1):
        score = c["coding_score"]
        score_txt = f"{score}" if score is not None else "n/a"
        fit = annotate_fit(c, budget_gb, ctx, installed)
        lines.append(
            f"| {i} | `{c['id']}` | {c['source']} | {score_txt} | {fit} |"
        )

    lines += [
        "",
        "## Promotion Gate",
        "",
        "1. Pull a fitting candidate and add it to `configs/models.yaml` as a canary.",
        "2. `make validate && make evals`.",
        "3. `make models-canary ROLE=... MODEL=ollama_chat/<tag>`.",
        "4. Compare evals, latency, judge-block quality, rollback rate.",
        "5. Promote or roll back manually (human-only).",
    ]
    return "\n".join(lines) + "\n"


def gather(registry: ModelRegistry, *, offline: bool, ctx: int,
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

    # rank: models with a coding score first (desc), runnable-but-unscored after
    candidates.sort(key=lambda c: (c["coding_score"] is None, -(c["coding_score"] or 0)))
    return candidates[:max_candidates], errors, notes, installed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ctx", type=int, default=DEFAULT_FIT_CTX)
    parser.add_argument("--json", action="store_true", help="write JSON instead of Markdown")
    parser.add_argument("--offline", action="store_true", help="only validate scout config")
    args = parser.parse_args()

    registry = load_registry()
    if registry.scout is None:
        raise SystemExit("configs/models.yaml has no scout section")

    budget = gpu_budget_gb()
    candidates, errors, notes, installed = gather(
        registry, offline=args.offline, ctx=args.ctx,
        max_candidates=registry.scout.max_candidates_per_run,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        out.write_text(json.dumps({
            "sources": registry.scout.sources,
            "gpu_budget_gb": budget,
            "candidates": candidates,
            "notes": notes,
            "errors": errors,
        }, indent=2), encoding="utf-8")
    else:
        out.write_text(
            render_report(registry, candidates, errors, notes, budget, args.ctx, installed),
            encoding="utf-8",
        )
    print(f"wrote {out}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

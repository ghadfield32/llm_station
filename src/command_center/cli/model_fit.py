#!/usr/bin/env python3
"""model_fit — which local models actually fit this machine's GPU, and how much context.

Turns "what's the best model" into a data-derived number: reads the real weight
size (Ollama /api/tags) and GGUF metadata (/api/show) for every installed model,
applies the GQA-aware KV-cache formula (command_center.registry.vram), and prints
which models fit the GPU budget at a target context — plus the largest context
each could still hold. The budget comes from configs/environments.yaml
(the GPU worker's gpu_vram_gb), not a hardcoded 24.

Run from the repo root:  python -m command_center.cli.model_fit [--ctx N] [--json]
Ground-truth check: any currently-loaded model's actual resident VRAM (/api/ps)
is shown next to the estimate so the prediction stays honest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from command_center.registry import vram
from command_center.schemas import EnvironmentsConfig

ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENTS = ROOT / "configs" / "environments.yaml"
DEFAULT_ENV = "cc-worker-4090"
DEFAULT_CTX = 65536          # the >=64k working context the agent stack assumes
GIB = 1024 ** 3


def budget_from_env(env_name: str) -> float:
    """Read gpu_vram_gb for the named environment. Fail loud if absent."""
    cfg = EnvironmentsConfig.model_validate(
        yaml.safe_load(ENVIRONMENTS.read_text(encoding="utf-8"))
    )
    by_name = {e.name: e for e in cfg.environments}
    if env_name not in by_name:
        raise SystemExit(
            f"environment {env_name!r} not in configs/environments.yaml "
            f"(have: {sorted(by_name)})"
        )
    env = by_name[env_name]
    if env.gpu_vram_gb is None:
        raise SystemExit(
            f"environment {env_name!r} has no gpu_vram_gb; set it in "
            "configs/environments.yaml or pass --vram-gb"
        )
    return float(env.gpu_vram_gb)


def render_table(estimates: list[vram.Estimate], loaded: dict[str, dict]) -> str:
    header = (
        f"{'model':<26} {'params':>7} {'quant':<8} {'weights':>8} "
        f"{'kv':>7} {'total':>7} {'fit':>4} {'max_ctx_fits':>13}  actual"
    )
    lines = [header, "-" * len(header)]
    for e in estimates:
        params = f"{e.params_b}B" if e.params_b else "?"
        actual = ""
        if e.name in loaded and "size_vram" in loaded[e.name]:
            actual = f"{loaded[e.name]['size_vram'] / GIB:.1f}GB live"
        lines.append(
            f"{e.name:<26} {params:>7} {(e.quant or '?'):<8} "
            f"{e.weights_gb:>7.1f}G {e.kv_gb:>6.1f}G {e.total_gb:>6.1f}G "
            f"{('YES' if e.fits else 'NO'):>4} {e.max_ctx_fits:>13,}  {actual}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ctx", type=int, default=DEFAULT_CTX,
                        help=f"context length to size against (default {DEFAULT_CTX})")
    parser.add_argument("--model", help="check one installed model instead of all")
    parser.add_argument("--env", default=DEFAULT_ENV,
                        help=f"environment whose gpu_vram_gb is the budget (default {DEFAULT_ENV})")
    parser.add_argument("--vram-gb", type=float,
                        help="override the budget (GB) instead of reading environments.yaml")
    parser.add_argument("--kv-bytes", type=float, default=vram.KV_BYTES_FP16,
                        help="bytes per KV element (fp16=2, q8_0 cache=1, q4_0=0.5)")
    parser.add_argument("--base-url", default=vram.DEFAULT_OLLAMA_BASE,
                        help="Ollama base URL")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()

    budget = args.vram_gb if args.vram_gb is not None else budget_from_env(args.env)

    try:
        if args.model:
            estimates = [vram.estimate_installed(
                args.model, ctx=args.ctx, budget_gb=budget,
                base_url=args.base_url, kv_bytes=args.kv_bytes,
            )]
            errors: list[str] = []
        else:
            estimates, errors = vram.list_installed_estimates(
                ctx=args.ctx, budget_gb=budget,
                base_url=args.base_url, kv_bytes=args.kv_bytes,
            )
        loaded = vram.ollama_ps(args.base_url)
    except vram.VramError as exc:
        raise SystemExit(f"model-fit: {exc}")

    if args.json:
        print(json.dumps({
            "budget_gb": budget,
            "ctx": args.ctx,
            "estimates": [e.to_dict() for e in estimates],
            "skipped": errors,
        }, indent=2))
        return 0

    print(f"GPU budget: {budget:g} GB  |  sizing at ctx={args.ctx:,}  "
          f"(kv={args.kv_bytes:g}B/elem)\n")
    print(render_table(estimates, loaded))
    if errors:
        # Skips (e.g. embedding models with no attention KV) are expected, not
        # failures — surfaced for transparency, but they don't fail the run.
        print("\nskipped (not a sizable causal LM, or missing metadata):")
        for e in errors:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""enrich — one-line "why this matters / what to use it for" annotations on
newly kept papers/repos/signals, written into each row's `Suggested` field.

Deliberately scoped so context never becomes noise:
- runs ONLY on items that survived scoring + dedupe this cycle (the hourly
  delta is a handful of items after day one — efficient by construction)
- one short annotation per item (<=35 words, enforced in the prompt and
  truncated at the boundary), grounded in the registered projects
- local model only (the brief's model via Ollama); if Ollama is down the
  cycle proceeds unenriched with a LOUD warning — curation never blocks on
  an LLM, and nothing fabricates an annotation

Module tree / stages:
  stage 1  project_context()   config/projects.yaml names + the interest
                               profile -> grounding for the prompt
  stage 2  suggest()           per fresh item: title+summary -> Ollama chat
                               -> "helps <project>: <how> / use for <what>"
                               (or 'general interest') -> item.extra["suggested"]

Wired in curate.py between rank_and_trim and the write step.
"""
from __future__ import annotations

import logging
import re

import httpx

from .config import load_projects
from .models import CuratedItem

log = logging.getLogger("growthos.enrich")

MAX_WORDS = 35


def project_context() -> str:
    names = [p.name for p in load_projects().projects]
    return (
        f"Geoff's active projects: {', '.join(names)}. betts_basketball = NBA "
        "forecasting (Bayesian models, player tracking CV, odds pipelines, "
        "Airflow DAGs). llm_station = local-LLM agent infrastructure "
        "(Ollama/LiteLLM, local knowledge boards, mission gating).")


def suggest(items: list[CuratedItem], base_url: str, model: str) -> int:
    """Annotate items in place; returns how many got annotations."""
    if not items:
        return 0
    if not base_url:
        log.warning("enrich skipped: OLLAMA_BASE_URL is empty")
        return 0
    ctx = project_context()
    done = 0
    with httpx.Client(timeout=180) as http:
        for it in items:
            prompt = (
                f"{ctx}\n\nItem ({it.kind}): {it.title}\n"
                f"Summary: {it.summary[:500]}\n\n"
                f"In ONE sentence of at most {MAX_WORDS} words: is this useful "
                "for one of the projects, and what specifically would it be "
                "used for? If it fits neither, say what it's generally good "
                "for. No preamble, no hedging.")
            try:
                r = http.post(f"{base_url.rstrip('/')}/api/chat",
                              json={"model": model, "stream": False,
                                    "messages": [{"role": "user",
                                                  "content": prompt}]})
                r.raise_for_status()
                text = re.sub(r"<think>.*?</think>", "",
                              r.json()["message"]["content"], flags=re.S).strip()
            except httpx.HTTPError as exc:
                log.warning("enrich stopped at %r: %s (remaining items "
                            "unenriched this cycle)", it.title[:40], exc)
                return done
            words = text.split()
            it.extra["suggested"] = " ".join(words[:MAX_WORDS + 10])
            done += 1
    return done

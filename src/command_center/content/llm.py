"""Thin LiteLLM client for the content engine. Routes through the local model
roles (qwen3:30b etc.) exactly like services/judge_gate/judgectl.py, so calls
are budgeted and logged. Strips qwen3 <think> reasoning blocks."""
from __future__ import annotations

import json
import re

import httpx

_THINK = re.compile(r"<think>.*?</think>", re.S)


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/v1/chat/completions"


def chat(base_url: str, key: str, role: str, system: str, user: str,
         temperature: float = 0.4, max_tokens: int = 1000, timeout: int = 240) -> str:
    """One completion through a LiteLLM role. Raises loudly on any failure."""
    r = httpx.post(_endpoint(base_url),
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": role,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}],
                         "temperature": temperature, "max_tokens": max_tokens},
                   timeout=timeout)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    return _THINK.sub("", txt).strip()


def chat_json(base_url: str, key: str, role: str, system: str, user: str,
              **kw) -> dict:
    """A completion expected to be JSON. Strips code fences; raises if it isn't
    valid JSON (no silent fallback - a malformed judge/draft is a real failure)."""
    txt = chat(base_url, key, role, system, user, **kw)
    txt = txt.replace("```json", "").replace("```", "").strip()
    # tolerate leading/trailing prose around the JSON object
    start, end = txt.find("{"), txt.rfind("}")
    if start != -1 and end != -1:
        txt = txt[start:end + 1]
    return json.loads(txt)

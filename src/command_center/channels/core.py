"""Transport-agnostic gateway core.

One more *transport*, not a new authority: messages route through LiteLLM (the
single model gateway, local open-source models first) to the same verified
growthos action layer every other surface uses. The core is structurally unable
to approve mission cards (actions.set_status refuses; approval stays a human drag).

Module tree / flow (linear, shared by every channel adapter):
  stage 1  load_tool_layer()   growthos.actions -> OpenAI tool schemas (memoized;
                               same dispatch table the AppFlowy assistant uses)
  stage 2  GatewayConfig       repo .env + channel overrides (LiteLLM base/key/model)
  stage 3  run_turn()          LiteLLM /chat/completions tool-call loop (<= max_rounds),
                               errors surfaced to the caller, never swallowed
  stage 4  (adapter)           the transport chunks/sends the returned string

The two deterministic guards from the original Discord gateway are preserved
verbatim (and asserted by growth-os/scripts/selftest.py): the repeat-call breaker
("already called this with identical") and the forced final answer once the tool
budget is exhausted ("Tool budget exhausted").
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Hashable

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]   # src/command_center/channels/ -> repo root
GROWTHOS_ROOT = REPO_ROOT / "appflowy_kanban" / "growth-os"
ENV_PATH = REPO_ROOT / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def env() -> dict[str, str]:
    """Repo .env merged under the live process environment (process wins)."""
    return {**read_env_file(ENV_PATH), **os.environ}


@lru_cache(maxsize=1)
def load_tool_layer() -> tuple[list[dict], dict[str, Callable[..., Any]]]:
    """Import the growthos action layer once and expose it as OpenAI tool schemas
    plus a name->callable dispatch table. growthos settings read .env + config/
    from the growth-os root, so we put it on sys.path and chdir there (the gateway
    process's only job is to serve channels). Memoized: safe to call per adapter."""
    sys.path.insert(0, str(GROWTHOS_ROOT))
    os.chdir(GROWTHOS_ROOT)
    from growthos.assistant import TOOL_FNS, _schema_for  # noqa: E402
    tools = [_schema_for(f) for f in TOOL_FNS]
    dispatch = {f.__name__: f for f in TOOL_FNS}
    return tools, dispatch


def build_system(surface: str) -> str:
    """The rules of the wall, identical across surfaces; only the surface name varies."""
    return f"""You are the Growth OS gateway on {surface}. Today is {date.today().isoformat()}.
You manage the user's AppFlowy workspace via tools: todos kanban, paper/repo/
signal triage, the betts_basketball DAG board, packages/guidelines watchers,
the library (275-book Lineage curriculum), lessons, notes, and mission cards.

Rules of the wall, non-negotiable:
- You may DRAFT mission cards (add_mission_card -> Backlog) and stage/block/
  reject them. You CANNOT approve cards and must never claim you can; the
  human drags cards to Approved on the board, which dispatches gated Ledger
  missions (open-source local models do routine work; Claude Code/Codex are
  engaged through those gated missions for bigger things).
- All engineering work follows the command-center standards (no defensive
  coding, data-derived decisions, minimal diffs); you do not execute repo
  changes yourself - you draft cards that become gated missions.
Be concise; chat messages are short. Convert relative dates to ISO."""


@dataclass
class GatewayConfig:
    """Per-channel runtime config. Transport tokens/allowlists are NOT here — each
    adapter reads those from its own env names. This is just the model wiring."""
    surface: str                                  # display name, e.g. "Discord"
    model: str                                    # a models.yaml role alias
    litellm_base: str
    litellm_key: str
    max_history: int = 12
    max_rounds: int = 6

    @classmethod
    def build(cls, *, surface: str, model: str,
              max_history: int = 12, max_rounds: int = 6) -> "GatewayConfig":
        e = env()
        return cls(
            surface=surface,
            model=model,
            litellm_base=e.get("LITELLM_BASE_URL", "http://localhost:4000/v1").rstrip("/"),
            # the proxy enforces auth; a virtual key wins, else the master key
            litellm_key=e.get("LITELLM_API_KEY") or e.get("LITELLM_MASTER_KEY", ""),
            max_history=max_history,
            max_rounds=max_rounds,
        )


class GatewayCore:
    """The LiteLLM tool-call loop, shared by every transport. Construct one per
    channel; call run_turn() with a stable conversation id (channel id, chat id,
    phone number) and the user's text."""

    def __init__(self, cfg: GatewayConfig):
        self.cfg = cfg
        self.system = build_system(cfg.surface)
        self.tools, self.dispatch = load_tool_layer()
        self.histories: dict[Hashable, deque] = defaultdict(
            lambda: deque(maxlen=cfg.max_history))
        self.http = httpx.AsyncClient(timeout=300)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _completion(self, messages: list, with_tools: bool) -> dict:
        headers = {"Authorization": f"Bearer {self.cfg.litellm_key}"} \
            if self.cfg.litellm_key else {}
        body: dict[str, Any] = {"model": self.cfg.model, "messages": messages}
        if with_tools:
            body["tools"] = self.tools
        r = await self.http.post(
            f"{self.cfg.litellm_base}/chat/completions",
            headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]

    async def run_turn(self, conversation_id: Hashable, user_text: str) -> str:
        history = self.histories[conversation_id]
        history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self.system}, *history]
        seen_calls: set[tuple[str, str]] = set()
        for _ in range(self.cfg.max_rounds):
            try:
                msg = await self._completion(messages, with_tools=True)
            except httpx.HTTPError as exc:   # surfaced, never swallowed
                return f"LiteLLM gateway error: {exc}"
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                content = (msg.get("content") or "").strip()
                history.append({"role": "assistant", "content": content})
                return content or "(no response)"
            for call in calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                key = (name, raw_args)
                if key in seen_calls:        # deterministic loop-breaker
                    result = ("you already called this with identical "
                              "arguments and have its result above; the data "
                              "has not changed. Stop calling tools and answer "
                              "the user now with what you have.")
                else:
                    seen_calls.add(key)
                    try:
                        result = self.dispatch[name](**json.loads(raw_args))
                    except Exception as exc:  # tool errors go back to the model
                        result = f"error: {exc}"
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result, default=str)})
        # round cap reached: force a text answer from gathered context
        messages.append({"role": "user", "content":
                         "Tool budget exhausted. Answer my original question "
                         "now using only the tool results above; say plainly "
                         "if something could not be determined."})
        try:
            msg = await self._completion(messages, with_tools=False)
        except httpx.HTTPError as exc:
            return f"LiteLLM gateway error: {exc}"
        content = (msg.get("content") or "").strip()
        history.append({"role": "assistant", "content": content})
        return content or "(no answer after tool budget)"

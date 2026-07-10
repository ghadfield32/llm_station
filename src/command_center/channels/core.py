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

import asyncio
import json
import os
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Hashable

import httpx

from .board_state import collect_board_state, load_agent_surface_config
from .transcript import TurnRecorder
from .transcript import current_conversation as transcript_conversation

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


@lru_cache(maxsize=8)
def load_tool_layer(surface: str = "discord") -> tuple[list[dict], dict[str, Callable[..., Any]]]:
    """Import the growthos action layer once and expose it as OpenAI tool schemas
    plus a name->callable dispatch table. growthos settings read .env + config/
    from the growth-os root, so we put it on sys.path and chdir there (the gateway
    process's only job is to serve channels). Memoized per surface so each channel's
    calls are recorded under ITS OWN surface in the agent-call log (the chain is
    observable per surface — Discord vs the in-app console vs SMS)."""
    sys.path.insert(0, str(GROWTHOS_ROOT))
    os.chdir(GROWTHOS_ROOT)
    from growthos.assistant import TOOL_FNS, _schema_for  # noqa: E402
    from growthos.observability import logged  # noqa: E402
    tools = [_schema_for(f) for f in TOOL_FNS]
    dispatch = {f.__name__: logged(f, surface) for f in TOOL_FNS}
    return tools, dispatch


def _resolve_primary_board(env_map: dict[str, str]) -> str | None:
    """The board governed events are tagged with. Explicit env wins; otherwise the
    sole registered board. Returns None when ambiguous (multiple boards) so the
    caller can fail loudly rather than guess."""
    if env_map.get("KANBAN_PRIMARY_BOARD_ID"):
        return env_map["KANBAN_PRIMARY_BOARD_ID"]
    import yaml
    from command_center.schemas import KanbanBoardsConfig
    path = REPO_ROOT / "configs" / "kanban_boards.yaml"
    cfg = KanbanBoardsConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8")))
    return cfg.boards[0].board_id if len(cfg.boards) == 1 else None


def kanban_emission_status(env_map: dict[str, str]) -> dict[str, Any]:
    """Whether governed kanban writes emit events (the STANDARD sync path), which
    board they tag, and why. Emission is ON BY DEFAULT; it is suppressed only by an
    explicit opt-out or when no single board can be resolved.

    States:
      - KANBAN_EMIT_EVENTS=0            -> off (explicit opt-out)
      - board resolvable               -> on (KANBAN_PRIMARY_BOARD_ID or sole board)
      - KANBAN_EMIT_EVENTS=1, no board  -> caller raises (explicit on, unsatisfiable)
      - default, multiple boards        -> off + reason (set KANBAN_PRIMARY_BOARD_ID)
    """
    flag = env_map.get("KANBAN_EMIT_EVENTS")
    if flag == "0":
        return {"active": False, "board_id": None,
                "reason": "disabled by KANBAN_EMIT_EVENTS=0"}
    board_id = _resolve_primary_board(env_map)
    if board_id:
        return {"active": True, "board_id": board_id,
                "reason": f"emitting governed kanban writes to board {board_id!r}"}
    if flag == "1":
        return {"active": False, "board_id": None, "explicit_unsatisfiable": True,
                "reason": "KANBAN_EMIT_EVENTS=1 but no board resolved; set "
                          "KANBAN_PRIMARY_BOARD_ID or register exactly one board"}
    return {"active": False, "board_id": None,
            "reason": "multiple boards registered; set KANBAN_PRIMARY_BOARD_ID to "
                      "activate live-sync emission"}


def _wire_kanban_events(dispatch: dict[str, Callable[..., Any]],
                        surface: str) -> dict[str, Callable[..., Any]]:
    """Wrap governed verbs so every governed kanban write emits one event — the
    standard sync path. On by default; opt out with KANBAN_EMIT_EVENTS=0."""
    env_map = env()
    st = kanban_emission_status(env_map)
    if not st["active"]:
        # an EXPLICIT opt-in that can't be satisfied fails loudly; the default
        # (no flag) just stays inactive with the reason surfaced via `cc setup`.
        if st.get("explicit_unsatisfiable"):
            raise RuntimeError(st["reason"])
        return dispatch
    from command_center.kanban_sync import EventLog, wrap_governed_dispatch
    raw = env_map.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl")
    path = Path(raw)
    log = EventLog(path if path.is_absolute() else REPO_ROOT / path)
    return wrap_governed_dispatch(dispatch, surface=surface,
                                  board_id=st["board_id"], log=log)


def build_system(surface: str) -> str:
    """The operator brief + the rules of the wall, identical across surfaces (only
    the surface name varies). It enumerates every capability tier on purpose: a
    model only uses the abilities its prompt tells it it has, so under-describing
    the tool layer is why a capable bot acts helpless."""
    return f"""You are the Growth OS gateway on {surface}. Today is {date.today().isoformat()}.
You operate the user's AppFlowy workspace and drive work on the betts_basketball
and command-center repos through a verified tool layer. The live board is injected
each turn — don't call list_* just to see what's already shown. What you can do:

1. BOARDS — read and adjust by INTENT (the harness owns row keys; address rows by
   their title): add_todo/update_todo, start_todo/finish_todo/block_todo;
   add_mission_card + stage_card/block_card/reject_card; update_dag; move_item to
   triage papers/repos/signals/library/lessons; annotate_item to append Notes;
   set_item_field to change real schema/grouping fields (Section, Area, Priority,
   Risk, Due, Tags, Pillar, Format, Module, Action, Acceptance, Owners, etc.);
   remove_item_field_value to remove one exact value from grouped text fields;
   add_book/book_note, add_lesson, add_note. search + list_inbox/list_todos/
   list_cards/list_dags find rows. Use Status verbs/move_item for columns. You
   cannot change AppFlowy view layout/group-by/visual formatting through this REST
   tool path; say so plainly or draft a verified API mission.
2. RESEARCH — understand, don't just list: read_item(database, title) returns a
   paper's/repo's/book's FULL detail (abstract, summary, score, "suggested for",
   url). Use it to actually explain or triage an item; search first if you lack the
   exact title.
3. AWARENESS — project_status("betts_basketball") (DAG counts + broken-DAG errors +
   pending package updates + open cards/todos in one call), dag_health (LIVE
   Airflow, not the board), network_health (every hop ok/error), mission_status(id),
   latest_brief.
4. REPO WORK — you DRIVE it, executors complete it. To get real code/DAG/repo work
   done on betts_basketball or command-center: add_mission_card(title, section,
   action, acceptance, risk, repo, target). It lands in Backlog; tell the user to
   drag it to Approved, which dispatches a GATED Ledger mission an executor (Claude
   Code/Codex) completes in an isolated worktree behind the judges. Track it with
   mission_status. Write a concrete Action and a measurable Acceptance so the
   executor and judges have a clear target. Sections: DAGs, Betts Basketball,
   Command Center (code/repo work) and Learning (plans). Risk L0-L4 (a section
   default applies if you omit it); L3/L4 also need a signed Ledger approval.

The wall (structural, enforced in code — not just policy): you DRAFT and MONITOR;
you can NEVER approve a card or merge a PR, and must not claim you can. Approval is
the human's drag to Approved; merge is the human's PR review. Engineering follows
the command-center standards (no defensive coding, data-derived decisions, minimal
diffs) — you express that by drafting good cards, never by editing repos yourself.
Be concise (chat messages are short). Convert relative dates to ISO."""


def _clean(text: str) -> str:
    """Strip a thinking model's <think>...</think> reasoning from the final
    answer — the user gets the answer, not the scratchpad. Parity with
    growthos.assistant._clean so every surface treats model output the same."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


# Markers a parsed tool call would NEVER contain (they live in tool_calls, not
# content). If they appear in content while tool_calls is empty, the model tried
# to call a tool and the serving path failed to parse it (e.g. qwen3-coder's
# native Ollama parser dropping a call that the model prefixed with prose). This
# is a fail-loud tripwire, not a parser: we refuse to forward the markup and name
# the cause, rather than silently showing the user `<function=..>` XML. With the
# template-parsed `chat` role it never fires; it catches a regression (a channel
# pointed back at a model whose tool calls don't parse).
_TOOL_CALL_MARKERS = ("<tool_call>", "<function=", "<parameter=", "<tool_response>")


def _leaked_tool_call(content: str) -> bool:
    return any(m in content for m in _TOOL_CALL_MARKERS)


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
    # Max model turns this gateway runs at once. Sized to the GPU tier's real
    # parallelism (Ollama serves OLLAMA_NUM_PARALLEL at a time; beyond that
    # requests just queue and thrash). Excess turns wait on a semaphore rather
    # than pile onto Ollama. Not a threshold to tune blindly — it mirrors the
    # backend's actual concurrency (env GATEWAY_MAX_CONCURRENCY, else
    # OLLAMA_NUM_PARALLEL, else 1 = Ollama's own default).
    max_concurrency: int = 1

    @classmethod
    def build(cls, *, surface: str, model: str,
              max_history: int = 12, max_rounds: int = 6) -> "GatewayConfig":
        e = env()
        concurrency = e.get("GATEWAY_MAX_CONCURRENCY") or e.get("OLLAMA_NUM_PARALLEL") or "1"
        return cls(
            surface=surface,
            model=model,
            litellm_base=e.get("LITELLM_BASE_URL", "http://localhost:4000/v1").rstrip("/"),
            # the proxy enforces auth; a virtual key wins, else the master key
            litellm_key=e.get("LITELLM_API_KEY") or e.get("LITELLM_MASTER_KEY", ""),
            max_history=max_history,
            max_rounds=max_rounds,
            max_concurrency=max(1, int(concurrency)),
        )


class GatewayCore:
    """The LiteLLM tool-call loop, shared by every transport. Construct one per
    channel; call run_turn() with a stable conversation id (channel id, chat id,
    phone number) and the user's text."""

    def __init__(self, cfg: GatewayConfig):
        self.cfg = cfg
        self.system = build_system(cfg.surface)
        self.tools, self.dispatch = load_tool_layer(cfg.surface)
        # Live kanban sync: funnel every governed card/todo verb (this surface
        # included) through the kanban event log so the internal UI + AppFlowy
        # project from one source. Opt-in: only when a deployment configures the
        # event-log path and a resolvable board (no fabricated board/surface).
        self.dispatch = _wire_kanban_events(self.dispatch, cfg.surface)
        # The harness owns board state: load the (validated) re-injection knobs once
        # and re-state the live board to the model each turn so it never has to call
        # list_* to remember what's on the board (see board_state.py).
        self.board_knobs = load_agent_surface_config().board_state
        # Durable cross-conversation memory: the same harness-owned-state pattern as the
        # board, but for facts the user told us. Loaded once (growthos is importable here —
        # load_tool_layer above pulled it in); re-injected each turn via _memory_messages.
        from growthos.memory import load_memory_config
        self.memory_cfg = load_memory_config()
        self.histories: dict[Hashable, deque] = defaultdict(
            lambda: deque(maxlen=cfg.max_history))
        self.http = httpx.AsyncClient(timeout=300)
        # Busy rules: one in-flight turn per conversation (a shared history
        # deque can't be mutated by two turns at once), and a global cap so we
        # never push more concurrent calls at the GPU than it actually serves.
        self._slots = asyncio.Semaphore(cfg.max_concurrency)
        self._inflight: set[Hashable] = set()

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _completion(self, messages: list, with_tools: bool) -> dict:
        headers = {"Authorization": f"Bearer {self.cfg.litellm_key}"} \
            if self.cfg.litellm_key else {}
        body: dict[str, Any] = {"model": self.cfg.model, "messages": messages}
        if with_tools:
            body["tools"] = self.tools
        # Same join key as the flight recorder: LiteLLM groups requests that
        # share a litellm_session_id into one Session Logs view, so the proxy's
        # spend-log net and our transcripts index by the same conversation id.
        conversation = transcript_conversation.get()
        if conversation:
            body["litellm_session_id"] = f"{self.cfg.surface}:{conversation}"
        r = await self.http.post(
            f"{self.cfg.litellm_base}/chat/completions",
            headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        # Token counts ride ON the message (popped by the caller before the
        # message joins history) — a shared self.last_usage would misattribute
        # usage across concurrent turns.
        msg["_usage"] = data.get("usage")
        return msg

    def _leak_diagnostic(self, content: str) -> str | None:
        """Fail-loud guard shared by BOTH loops: raw tool-call markup a serving
        path failed to parse must never reach a user surface (see
        _TOOL_CALL_MARKERS). Returns the operator-facing diagnostic, or None
        when the content is clean."""
        if not _leaked_tool_call(content):
            return None
        print(f"[gateway] UNPARSED TOOL CALL from model role "
              f"{self.cfg.model!r}; head: {content[:300]!r}",
              file=sys.stderr)
        return (f"gateway misconfiguration: model role {self.cfg.model!r} "
                f"emitted a tool call the serving path did not parse. This "
                f"channel needs a tool-robust model role — see "
                f"configs/models.yaml `chat:`.")

    async def run_turn(self, conversation_id: Hashable, user_text: str) -> str:
        """Busy rules wrap the model loop:
        - one turn per conversation: a second message while the first is still
          running gets a clear 'still working' reply instead of corrupting the
          shared history or doubling GPU load.
        - global slots: turns beyond max_concurrency wait their turn rather
          than pile onto the GPU. The caller's typing indicator covers the wait.
        Neither swallows anything — failures inside still surface verbatim."""
        if conversation_id in self._inflight:
            return ("still working on your previous message - one moment, then "
                    "resend if I haven't answered.")
        self._inflight.add(conversation_id)
        try:
            async with self._slots:
                return await self._run_turn(conversation_id, user_text)
        finally:
            self._inflight.discard(conversation_id)

    def _board_message(self) -> dict:
        """A system-role block of the live board, regenerated per call (never stored
        in history). collect_board_state is per-source fail-loud — it returns ERROR
        lines, never an empty/stale block."""
        return {"role": "system", "content": collect_board_state(self.board_knobs)}

    def _memory_messages(self, query: str) -> list[dict]:
        """Durable cross-conversation memory relevant to `query`, re-injected like the
        board (never stored in history). Empty list when memory is disabled or there is
        nothing to recall, so no empty block is added. collect_memory_state is fail-loud:
        it renders an ERROR line, never raises into the turn."""
        from growthos.memory import collect_memory_state
        block = collect_memory_state(query, self.memory_cfg)
        return [{"role": "system", "content": block}] if block else []

    async def run_turn_events(self, conversation_id: Hashable, user_text: str):
        """Same loop + busy rules as run_turn, but an async generator that YIELDS
        each step as it happens — for the live 'watch the LLM work' view. Events:
        {type: round} · {type: tool, name, args} · {type: tool_result, name, result}
        · {type: final, content}. History is updated identically, so streaming and
        non-streaming turns share one conversation."""
        if conversation_id in self._inflight:
            yield {"type": "final",
                   "content": "still working on your previous message — one moment."}
            return
        self._inflight.add(conversation_id)
        # Flight recorder: full-fidelity turn capture at the only seam where the
        # untruncated story exists (SSE events below stay truncated). Fail-open.
        rec = TurnRecorder(surface=self.cfg.surface, model=self.cfg.model,
                           conversation_id=conversation_id, user_text=user_text)
        try:
            async with self._slots:
                history = self.histories[conversation_id]
                history.append({"role": "user", "content": user_text})
                messages = [{"role": "system", "content": self.system}]
                if self.board_knobs.enabled:
                    messages.append(self._board_message())
                    rec.context("board_state")
                mem = self._memory_messages(user_text)
                messages += mem
                if mem:
                    rec.context("growthos_memory")
                messages += list(history)
                seen: set[tuple[str, str]] = set()
                refresh = self.board_knobs.refresh_every_rounds
                for round_idx in range(self.cfg.max_rounds):
                    yield {"type": "round", "n": round_idx + 1}
                    rec.event("round", n=round_idx + 1)
                    try:
                        msg = await self._completion(messages, with_tools=True)
                    except (httpx.HTTPError, KeyError, IndexError,
                            ValueError) as exc:
                        # HTTP failure or a malformed 200 (bad JSON / missing
                        # choices) — surface an error frame, never a dead stream
                        rec.final(f"LiteLLM gateway error: {exc!r}")
                        yield {"type": "final", "content": f"LiteLLM gateway error: {exc!r}"}
                        return
                    rec.usage(msg.pop("_usage", None))
                    messages.append(msg)
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        content = _clean(msg.get("content") or "")
                        diag = self._leak_diagnostic(content)
                        if diag:
                            history.append({"role": "assistant", "content": diag})
                            rec.final(diag)
                            yield {"type": "final", "content": diag}
                            return
                        history.append({"role": "assistant", "content": content})
                        rec.final(content)
                        yield {"type": "final", "content": content or "(no response)"}
                        return
                    for call in calls:
                        name = call["function"]["name"]
                        raw = call["function"].get("arguments") or "{}"
                        rec.tool(name, raw)
                        yield {"type": "tool", "name": name, "args": raw[:200]}
                        if (name, raw) in seen:
                            result = "(repeat suppressed — identical call already made)"
                        else:
                            seen.add((name, raw))
                            try:
                                result = self.dispatch[name](**json.loads(raw))
                            except Exception as exc:
                                result = f"error: {exc}"
                        rec.tool_result(name, result)
                        yield {"type": "tool_result", "name": name,
                               "result": str(result)[:300]}
                        messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": json.dumps(result, default=str)})
                    if self.board_knobs.enabled and refresh and (round_idx + 1) % refresh == 0:
                        messages.append(self._board_message())
                        rec.context("board_state_refresh")
                    mem_refresh = self.memory_cfg.refresh_every_rounds
                    if mem_refresh and (round_idx + 1) % mem_refresh == 0:
                        messages += self._memory_messages(user_text)
                        rec.context("growthos_memory_refresh")
                messages.append({"role": "user", "content":
                                 "Tool budget exhausted. Answer now using the tool "
                                 "results above; say plainly what couldn't be done."})
                try:
                    msg = await self._completion(messages, with_tools=False)
                except (httpx.HTTPError, KeyError, IndexError,
                        ValueError) as exc:
                    rec.final(f"LiteLLM gateway error: {exc!r}")
                    yield {"type": "final", "content": f"LiteLLM gateway error: {exc!r}"}
                    return
                rec.usage(msg.pop("_usage", None))
                content = _clean(msg.get("content") or "")
                content = self._leak_diagnostic(content) or content
                history.append({"role": "assistant", "content": content})
                rec.final(content or "(no answer after budget)")
                yield {"type": "final", "content": content or "(no answer after budget)"}
        finally:
            rec.flush()
            self._inflight.discard(conversation_id)

    async def _run_turn(self, conversation_id: Hashable, user_text: str) -> str:
        rec = TurnRecorder(surface=self.cfg.surface, model=self.cfg.model,
                           conversation_id=conversation_id, user_text=user_text)
        try:
            return await self._run_turn_recorded(conversation_id, user_text, rec)
        finally:
            rec.flush()

    async def _run_turn_recorded(self, conversation_id: Hashable, user_text: str,
                                 rec: "TurnRecorder") -> str:
        history = self.histories[conversation_id]
        history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self.system}]
        if self.board_knobs.enabled:        # harness re-injects the single source of truth
            messages.append(self._board_message())
            rec.context("board_state")
        _mem = self._memory_messages(user_text)
        messages += _mem
        if _mem:
            rec.context("growthos_memory")
        messages += list(history)
        seen_calls: set[tuple[str, str]] = set()
        refresh = self.board_knobs.refresh_every_rounds
        for round_idx in range(self.cfg.max_rounds):
            rec.event("round", n=round_idx + 1)
            try:
                msg = await self._completion(messages, with_tools=True)
            except (httpx.HTTPError, KeyError, IndexError,
                    ValueError) as exc:   # surfaced, never swallowed
                rec.final(f"LiteLLM gateway error: {exc!r}")
                return f"LiteLLM gateway error: {exc!r}"
            rec.usage(msg.pop("_usage", None))
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                content = _clean(msg.get("content") or "")
                diag = self._leak_diagnostic(content)
                if diag:
                    history.append({"role": "assistant", "content": diag})
                    rec.final(diag)
                    return diag
                history.append({"role": "assistant", "content": content})
                rec.final(content or "(no response)")
                return content or "(no response)"
            for call in calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                rec.tool(name, raw_args)
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
                rec.tool_result(name, result)
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result, default=str)})
            # re-state the board after mutations so later rounds act on fresh state
            if self.board_knobs.enabled and refresh and (round_idx + 1) % refresh == 0:
                messages.append(self._board_message())
                rec.context("board_state_refresh")
            # re-surface durable memory on its own cadence (keeps it in-window on deep turns)
            mem_refresh = self.memory_cfg.refresh_every_rounds
            if mem_refresh and (round_idx + 1) % mem_refresh == 0:
                messages += self._memory_messages(user_text)
                rec.context("growthos_memory_refresh")
        # round cap reached: force a text answer from gathered context
        messages.append({"role": "user", "content":
                         "Tool budget exhausted. Answer my original question "
                         "now using only the tool results above; say plainly "
                         "if something could not be determined."})
        try:
            msg = await self._completion(messages, with_tools=False)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            rec.final(f"LiteLLM gateway error: {exc!r}")
            return f"LiteLLM gateway error: {exc!r}"
        rec.usage(msg.pop("_usage", None))
        content = _clean(msg.get("content") or "")
        content = self._leak_diagnostic(content) or content
        history.append({"role": "assistant", "content": content})
        rec.final(content or "(no answer after tool budget)")
        return content or "(no answer after tool budget)"

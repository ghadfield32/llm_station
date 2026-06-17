"""Local-LLM assistant: chat with your Ollama model and let it manage the
Growth OS workspace (todos kanban, paper/repo triage, DAG board, lessons,
books, notes) through the same verified actions the MCP server uses.

Usage:
  python -m growthos.assistant                      # interactive chat
  python -m growthos.assistant "add a todo: ..."    # one-shot command

Model comes from GROWTHOS_ASSISTANT_MODEL (.env), default qwen3:8b.
llama3-groq-tool-use:70b is a stronger (slower) option for complex asks.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import date

import httpx

from . import actions
from . import memory            # durable cross-conversation memory verbs
from .config import load_settings

TOOL_FNS = [
    actions.list_todos, actions.add_todo, actions.update_todo,
    actions.start_todo, actions.finish_todo, actions.block_todo,
    actions.list_inbox, actions.search, actions.move_item, actions.read_item,
    actions.annotate_item, actions.set_item_field, actions.remove_item_field_value,
    actions.list_dags, actions.update_dag, actions.dag_health,
    actions.add_mission_card, actions.list_cards, actions.mission_status,
    actions.stage_card, actions.block_card, actions.reject_card,
    actions.project_status, actions.network_health,
    actions.add_lesson, actions.add_book, actions.add_note, actions.book_note,
    actions.latest_brief,
    memory.remember, memory.forget,
]

SYSTEM = f"""You are the Growth OS assistant. Today is {date.today().isoformat()}.
You manage the user's AppFlowy workspace via tools:
- todos: kanban of tasks. Statuses: Backlog, Todo, In Progress, Blocked, Done.
  Areas: Betts Basketball, DAGs, Growth OS, Learning, Life. Priorities P0-P3.
- papers/repos/signals: auto-curated research inboxes; triage with move_item, and
  read one item's full abstract/summary/score with read_item to actually explain it.
- dags: the betts_basketball Airflow DAG board (Active/Paused/Manual/Broken/Retired).
- mission_intake: approval-gated work cards. Draft cards to Backlog only; the
  user moves cards to Approved before the bridge opens Ledger missions.
  Sections: DAGs, Learning, Betts Basketball, Command Center. Priorities P0-P3.
- kanban row editing: annotate_item appends Notes without clobbering; set_item_field
  changes real schema fields such as Section, Area, Priority, Risk, Due, Tags,
  Pillar, Format, Module, Action, Acceptance, Owners; remove_item_field_value removes
  one exact value from grouped text fields like Tags/Topics/Owners without clearing
  the field. Use move_item/dedicated verbs for Status. You cannot change AppFlowy
  board view layout/group-by/visual formatting through the current REST tool path;
  if asked, state that plainly or draft a card to add a verified view-layout API later.
- lessons/library/notes: spaced-repetition lessons, the book list, free notes.
- memory: a REMEMBERED block of durable facts is given to you each turn (preferences,
  decisions, names, ongoing context) — read and use it; no tool is needed to see it. When
  the user tells you something durable about themselves or their work, or asks you to
  remember it, call remember(fact) so you recall it in future conversations; call
  forget(fact) when it changes. Simply sharing a fact about themselves or their work is
  NOT a request to create, stage, or change a board card or todo — remember it and reply;
  touch the board only when the user actually asks for work. Save only stable facts worth
  keeping — never transient chatter, secrets, or credentials.
Be concise. Use tools rather than guessing workspace state. When the user gives
a date like "friday", convert it to ISO YYYY-MM-DD before calling a tool."""


def _schema_for(fn) -> dict:
    """Build an Ollama tool schema from a function signature + docstring."""
    sig = inspect.signature(fn)
    props, required = {}, []
    for name, p in sig.parameters.items():
        ptype = "integer" if p.annotation is int else \
            "number" if p.annotation is float else "string"
        props[name] = {"type": ptype}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "function", "function": {
        "name": fn.__name__,
        "description": (fn.__doc__ or fn.__name__).strip().split("\n\n")[0],
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}


TOOLS = [_schema_for(f) for f in TOOL_FNS]
# every tool call (this local-assistant surface) is recorded to the centralized agent-call log
from .observability import logged  # noqa: E402
DISPATCH = {f.__name__: logged(f, "assistant") for f in TOOL_FNS}


def _chat(client: httpx.Client, base: str, model: str,
          messages: list[dict], with_tools: bool) -> dict:
    body = {"model": model, "messages": messages, "stream": False}
    if with_tools:
        body["tools"] = TOOLS
    r = client.post(f"{base}/api/chat", timeout=300, json=body)
    r.raise_for_status()
    return r.json()["message"]


def _clean(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


_BOARD_PREFIX = "=== BOARD STATE"


def _board_message() -> dict:
    """A system-role block of the live board, regenerated per call. Fail-loud lives
    in collect_board_state (ERROR lines, never an empty/stale block)."""
    from command_center.channels.board_state import collect_board_state
    return {"role": "system", "content": collect_board_state(_board_knobs())}


def _board_knobs():
    from command_center.channels.board_state import load_agent_surface_config
    return load_agent_surface_config().board_state


def _inject_board_state(messages: list[dict]) -> int:
    """Re-state the live board as a single source of truth: drop any prior board
    block, insert the current one right after the system prompt, and return the
    refresh cadence. The harness owns this state so the model never calls list_*
    just to remember what's on the board."""
    knobs = _board_knobs()
    messages[:] = [m for m in messages
                   if not str(m.get("content", "")).startswith(_BOARD_PREFIX)]
    if not knobs.enabled:
        return 0
    messages.insert(1, _board_message())
    return knobs.refresh_every_rounds


def run_turn(client: httpx.Client, base: str, model: str,
             messages: list[dict], max_rounds: int = 6) -> str:
    seen: set[tuple[str, str]] = set()
    refresh = _inject_board_state(messages)
    for round_idx in range(max_rounds):
        msg = _chat(client, base, model, messages, with_tools=True)
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            return _clean(msg.get("content", ""))
        for call in calls:
            fn_name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            key = (fn_name, json.dumps(args, sort_keys=True, default=str))
            if key in seen:                    # deterministic loop-breaker
                result = ("you already called this with identical arguments; "
                          "the result has not changed. Stop calling tools and "
                          "answer the user now with what you have.")
            else:
                seen.add(key)
                try:
                    result = DISPATCH[fn_name](**args)
                except Exception as exc:       # surface errors to the model
                    result = f"error: {exc}"
            print(f"  [tool] {fn_name}({json.dumps(args, default=str)[:120]})")
            messages.append({"role": "tool", "tool_name": fn_name,
                             "content": json.dumps(result, default=str)})
        # re-state the board after mutations so later rounds act on fresh state
        if refresh and (round_idx + 1) % refresh == 0:
            messages.append(_board_message())
    # round cap reached: force a text answer from gathered context
    messages.append({"role": "user", "content":
                     "Tool budget exhausted. Answer my original question now "
                     "using only the tool results above; say plainly if "
                     "something could not be determined."})
    msg = _chat(client, base, model, messages, with_tools=False)
    return _clean(msg.get("content", "")) or "(no answer after tool budget)"


def main() -> None:
    st = load_settings()
    base = (st.ollama_base_url or "http://localhost:11434").rstrip("/")
    model = st.growthos_assistant_model
    messages = [{"role": "system", "content": SYSTEM}]
    client = httpx.Client(timeout=300)

    if len(sys.argv) > 1:                      # one-shot
        messages.append({"role": "user", "content": " ".join(sys.argv[1:])})
        print(run_turn(client, base, model, messages))
        return

    print(f"Growth OS assistant ({model}) - 'quit' to exit")
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("quit", "exit", "q"):
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        print("\n" + run_turn(client, base, model, messages))


if __name__ == "__main__":
    main()

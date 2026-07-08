# Memory wiring patch — APPLIED 2026-06-14 (live-validated 8/8 through the real gateway)

> **Archived — one-time patch record, applied.** The top summary below still
> matches live code (`src/command_center/channels/core.py`'s `_memory_messages`).
> The bulk of the file (the staged Edit 1/Edit 2 sketch) is superseded and
> kept only for the record. GPU-budget note (§4): the embedder reserves
> ~1.1 GB, doesn't flip model-fit verdicts, and a 30B-Q4 model stays
> context-bound (~29k ctx on 24GB with the embedder resident).
>
> **Status: applied.** The agent-surface session quiesced (core.py/assistant.py untouched
> for ~30 min) and this wiring was applied + validated live (§3). This document is now the
> record of what was wired and how it was refined; it is no longer a pending patch.

The durable-memory subsystem (`growthos/memory.py`, `config/memory.yaml`) is built, tested
(21 hermetic tests), and now wired into the live agent loop across
`src/command_center/channels/core.py` and `appflowy_kanban/growth-os/growthos/assistant.py`.

**The applied form refined the staged sketch below to mirror `board_state` exactly (root-clean,
no per-call work):**
- `memory.collect_memory_state(query, cfg)` takes the config; `core.py` loads it **once in
  `__init__`** (`self.memory_cfg = load_memory_config()`, right after `load_tool_layer` puts
  growthos on the path) — the same "load knobs once" pattern as `self.board_knobs`.
- the injector is `_memory_messages(query) -> list[dict]` (list, so injection is a one-line
  `messages += self._memory_messages(user_text)` — mirrors `messages += list(history)`).
- memory re-injects mid-loop on **its own cadence** (`memory_cfg.refresh_every_rounds`),
  guarded against a 0 cadence exactly like the board's `refresh and …` — not piggybacked on
  the board's enable flag, so memory works even if the board is disabled.

The exact edits below are kept for the record; the snippets show the intent, the applied code
is the refined form above.

---

## Edit 1 — `growthos/assistant.py`: register the two verbs

The agent gains `remember` / `forget` exactly like any other tool: add the functions to
`TOOL_FNS` (the list `_schema_for` turns into Ollama tool schemas) and tell the model the
verbs exist.

**(a) import** — after the existing `from . import actions` (line ~22):

```python
from . import actions
from . import memory            # NEW: durable cross-conversation memory verbs
```

**(b) `TOOL_FNS`** — append `memory.remember, memory.forget` to the list (after
`actions.latest_brief,` at line ~34):

```python
    actions.latest_brief,
    memory.remember, memory.forget,   # NEW
]
```

**(c) `SYSTEM` prompt** — add one bullet so the model knows when to use them (after the
`lessons/library/notes` bullet, line ~47):

```
- memory: remember(fact) saves a durable fact about the user/their work so you recall it
  in future conversations (preferences, decisions, names); forget(fact) removes one. Use
  remember only for stable facts the user wants kept, never transient chatter.
```

`_schema_for` already handles the signatures: `remember(fact: str, project: str = "")`
→ `fact` required, `project` optional; `forget(fact: str)` → `fact` required. The
`logged(...)` wrapper in `DISPATCH`/`load_tool_layer` records both calls to the
agent-call log automatically, like every other tool.

---

## Edit 2 — `channels/core.py`: re-inject `memory_state`, mirroring `_board_message`

**(a)** add a `_memory_message` method next to `_board_message` (line ~230). It lazily
imports `collect_memory_state` (the same lazy-growthos pattern board_state uses) and
returns `None` when memory is off or there is nothing to recall, so no empty block is
added:

```python
    def _memory_message(self, query: str) -> dict | None:
        """Durable cross-conversation memory, retrieved for `query` and re-injected like
        the board (never stored in history). None when memory is disabled or empty, so no
        empty block is added. collect_memory_state is fail-loud — it renders an ERROR line,
        never raises into the turn."""
        from growthos.memory import collect_memory_state
        block = collect_memory_state(query)
        return {"role": "system", "content": block} if block else None
```

**(b)** in BOTH assembly methods (`run_turn_events` ~line 251 and `_run_turn` ~line 306),
inject memory right after the board block. The pattern to find (identical in both):

```python
        messages = [{"role": "system", "content": self.system}]
        if self.board_knobs.enabled:
            messages.append(self._board_message())
        messages += list(history)
```

becomes (memory is independent of the board, so it is NOT gated on `board_knobs.enabled`):

```python
        messages = [{"role": "system", "content": self.system}]
        if self.board_knobs.enabled:
            messages.append(self._board_message())
        if (mem := self._memory_message(user_text)):   # NEW: durable memory block
            messages.append(mem)
        messages += list(history)
```

Both methods have `user_text` in scope (it is the method parameter), so the retrieval
query is the turn's user message.

**(c, optional)** mid-loop refresh — to re-surface a fact the agent saved *during* the
turn, mirror the board's re-inject. Find (both methods, ~line 287 / ~line 334):

```python
            if self.board_knobs.enabled and refresh and (round_idx + 1) % refresh == 0:
                messages.append(self._board_message())
```

add under it:

```python
                if (mem := self._memory_message(user_text)):   # NEW
                    messages.append(mem)
```

This is optional: the start-of-turn injection in (b) is what delivers cross-conversation
recall; (c) only matters when the agent calls `remember` and then needs it back in the
same turn.

---

## 3. Post-apply verification (proves the gap is closed through the live gateway)

Run a two-conversation live check (same shape as `c:\tmp\live_multiturn.py`):

1. Conversation A: "Remember that I take my coffee black." → the agent calls `remember`.
2. A **fresh** conversation id: "How do I take my coffee? Answer from memory, no tools."
   → the agent answers "black" from the re-injected `=== REMEMBERED ===` block, with
   **no tool call** (confirm via the agent-call log: no `list_*`/lookup between).
3. "Actually I switched to oat milk — forget the black coffee note." → `forget`; a later
   fresh conversation no longer recalls it.

Expected: step 2 recalls across the conversation boundary (the deque(12) gap, now closed),
and the agent-call log shows `remember` / `forget` recorded on the channel surface.

## 4. GPU budget note (already applied, no patch needed)

Wiring memory makes the embedder always-resident. The VRAM-fit gate already accounts for
it: run `python -m command_center.cli.model_fit --reserve-model nomic-embed-text` to size
chat models against the budget *after* the embedder's real footprint (data-derived from
`/api/ps`→`/api/tags`, not a hardcoded number). Live, the embedder reserves **1.1 GB**
(0.3 GB weights + the CUDA baseline) — small enough that it flips no fit verdict; a 30B-Q4's
fit stays context-bound (≈29k ctx on the 24 GB card with the embedder resident; NO at the
full 65k default). The point is the gate now *charges* for the embedder instead of assuming
it free.

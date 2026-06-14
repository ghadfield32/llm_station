# Agent multi-turn proof + cross-conversation memory assessment

Status: **verified live** 2026-06-13. Scope: the channel agent (`GatewayCore`) that every
channel adapter shares. This documents (1) what was proven live across multiple turns and
messages, (2) the exact memory model in code, (3) the one real gap, and (4) a tiered,
data-derived recommendation. No code was changed to produce this — it is an assessment plus a
live proof.

## 1. What the shared agent is (one brain, four mouths)

All four channel adapters are thin transports over a single core:

| Channel | `configs/channels.yaml` model | Enabled | Adapter wiring |
|---|---|---|---|
| discord | `chat` | yes | `GatewayConfig.build(surface, model=spec.model)` → `GatewayCore` → `run_turn` |
| slack | `chat` | no | same |
| telegram | `chat` | no | same |
| whatsapp | `chat` | no | same |

Each adapter only (a) authenticates its transport, (b) applies an allowlist, (c) turns an
inbound message into `core.run_turn(conversation_id, text)`, (d) chunks the reply to the
transport's size limit. The **conversation_id differs per channel/chat**, so every
channel — and every chat within a channel — gets its own history. Testing `GatewayCore`
therefore tests all four channels' logic; only the transport plumbing differs. Only Discord is
live today (Slack/Telegram/WhatsApp are disabled and have no tokens), so the live proof below
ran straight against the shared core.

## 2. Memory model, exactly as coded (`channels/core.py`)

- **Within a conversation:** `histories: dict[conversation_id, deque(maxlen=max_history)]`,
  `max_history=12`. Each turn appends the user message, builds
  `messages = [system] + [board_state block, if enabled] + list(history)`, runs the tool loop,
  and re-injects the live board every `refresh_every_rounds`.
- **Board/state memory:** `board_state.py` (agent-surface harness) regenerates the live board
  each turn as a system block. It is **never stored in history** — it is always-fresh, and it
  is the same for every conversation because it reads the one shared AppFlowy board.
- **Across conversations:** nothing is shared. Two chats (different channels, or two chats in
  one channel) have independent deques.
- **Across restarts:** nothing persists. `histories` is an in-memory dict; a gateway restart
  drops all conversation history.

So there are two distinct kinds of "memory," and they behave oppositely:

| Memory kind | Carrier | Cross-conversation? | Survives restart? |
|---|---|---|---|
| Board / work state | `board_state` re-injection over shared AppFlowy | **yes** (same board everywhere) | **yes** (AppFlowy persists) |
| Conversation (what was *said*) | per-conversation `deque(12)` | no | no |

## 3. Live proof (multi-turn, multi-message, real models, real board)

Run through `GatewayCore` (`model: chat` → LiteLLM → `qwen3:30b`), one conversation id for
T1–T5, then a fresh conversation id for the probe. Exit 0.

| Turn | Message intent | Reply | Establishes |
|---|---|---|---|
| T1 | read board (tool) | "There are 13 mission cards on the mission_intake board." | model + tool routing, board read |
| T2 | draft a card | "'review Q3 odds metrics' drafted in Command Center (L1)." | board write |
| T3 | **no tool** — recall from chat | "'review Q3 odds metrics' was drafted in the Command Center section." | **within-conversation memory** (recalled T2 with zero tool calls) |
| T4 | "stage **that** card" | "Staged 'review Q3 odds metrics' to Ready." | context resolution → `stage_card` |
| T5 | "actually reject it" | "Rejected 'review Q3 odds metrics' (test card)." | context → `reject_card`; human wall held (no approve verb exists) |
| FRESH | new conversation id: recall earlier draft | "L4 wall check: simulate dangerous deploy request [L4]" | **cross-conversation gap** — could not recall; answered from the re-injected board instead |

Post-run cleanup verified: `review-Q3 cards still in Backlog: 0`.

The fresh-conversation turn is the crux: with no conversation memory, the agent did the only
thing it could — read the re-injected `board_state` and named a card that is actually on the
board. That simultaneously **demonstrates the gap** (no conversational recall across chats) and
**shows the board already is the durable, shared memory** for work state.

## 4. Do we need to add cross-conversation memory?

Data-derived answer, by use case:

- **Board / work operations — already solved, no action.** The board is the shared state and is
  re-injected into every conversation, so "what's on the board, in what state" is remembered
  everywhere and across restarts. For a Kanban assistant this is the memory that matters, and it
  exists today.
- **Conversational continuity across chats — real gap, value depends on usage.** If users
  reference things they *said* in another chat/channel ("the card I mentioned earlier"), the
  agent cannot recall it. Whether to close this should be driven by observed need: the
  `growthos/observability.py` agent-call log already records every turn, so we can measure how
  often cross-conversation reference actually occurs before investing. Do not pre-build for a
  demand we have not yet seen.

### Recommended options, lowest cost first (none built yet)

1. **Persist conversation histories (restart-durability).** Serialize each `deque` keyed by
   `conversation_id` (e.g. JSONL), reload on start. Closes only the *restart-loss* gap; adds no
   cross-conversation sharing and no new concepts. Touches `core.py` (agent-surface territory) —
   coordinate before implementing.
2. **`memory_state` re-injection (the real cross-conversation fix), modeled on `board_state`.**
   Add a `remember(fact)` intent the agent calls to persist a durable, *curated* fact; the
   harness re-injects the most relevant facts each turn — recency/relevance-ranked, capped with
   overflow disclosed, fail-loud — exactly the `board_state` discipline. This is the natural home
   in the agent-surface harness that already owns re-injection.
   - **Data-derived, not hardcoded:** which facts surface is a recency/relevance score over the
     store, never a fixed list or threshold.
   - **No leakage:** the store is per-user and holds agent-curated facts, **not** raw
     conversation dumps; it is never shared across users, and nothing about the data pipeline is
     exposed. The agent decides what is worth remembering, the same way it decides what to draft.
3. **Semantic recall over the OKF bundle (future, only if 1–2 prove insufficient).** Embed and
   retrieve durable knowledge for knowledge-level memory. Heavier; defer until measured need.

**Recommendation:** take no urgent action — the board already provides durable,
cross-conversation *state* memory, which is the important kind here. Instrument first (the
agent-call log already exists), and if cross-chat conversational reference shows up in real use,
implement option 2 (`memory_state` re-injection) as the clean architectural fit, with option 1
as a cheap orthogonal win for restart-durability. Both keep the project's discipline: decisions
data-derived, no hardcoded thresholds, no fallbacks, no data leakage.

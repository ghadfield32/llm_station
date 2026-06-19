"""Durable, cross-conversation memory for the agent — the companion to board_state.

The proven gap (see docs/agent-multiturn-and-memory.md): within a conversation the
gateway keeps a `deque(12)`, but **across** conversations (and across a restart) the
agent remembers nothing the user *said*. The board already carries durable *work
state* (board_state re-injects it every turn); this module adds durable *conversational
memory* the same way — the harness owns the store, the model emits intent.

Design (consistent with board_state and the project's no-leakage discipline):

  - The agent persists a fact only by **explicit intent** — the `remember(fact)` /
    `forget(fact)` verbs (siblings of stage_card / reject_card). Nothing is
    auto-harvested from raw conversation, so there is no leak surface: only
    agent-curated facts are stored, never transcripts.
  - `collect_memory_state(query)` retrieves the most relevant facts for the *owner*
    and renders one system block, re-injected each turn exactly like board_state.
    It keys on a stable owner (configurable), NOT the conversation id — that is what
    makes recall cross-conversation (a fresh conversation has a new id but the same
    owner).
  - Retrieval is data-derived, not thresholded: score = cosine(query, fact) ×
    recency_decay(age). No relevance cutoff — top-k, the same shape as score.py's
    `rank_and_trim`. Embeddings are the real local `nomic-embed-text` (reused from
    score.py); if the embedder is unreachable, retrieval **fails loud** (no keyword
    fallback — memory recall must never silently degrade).
  - Per-owner keyed: a query for owner A can never read owner B's facts (the leak
    boundary holds even when multi-user owners arrive). An optional project tag scopes
    a fact to one project.

Knobs come from config/memory.yaml (MemoryConfig) — every field required, so a missing
knob fails loud instead of taking a hidden code default. The retrieval weights it
declares are the documented baseline a future learner abstains to until it beats them on
a temporal holdout (same discipline as the cadence learner) — they are config, not code
literals.

Pure where it can be (render_memory_state, _cosine, _recency_factor are I/O-free and
unit-tested); the store injects its embed function and clock, so tests are hermetic.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx
import yaml
from pydantic import BaseModel

from .config import load_settings

# memory.py lives at growth-os/growthos/memory.py; config + state dir hang off the
# growth-os root, resolved absolutely so this is robust to the gateway's chdir.
_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _ROOT / "config" / "memory.yaml"

# A batch embedder: texts -> one vector each. Injected by the store so tests need no
# network and production uses the real local model.
EmbedFn = Callable[[list[str]], list[list[float]]]


class MemoryError(RuntimeError):
    """Raised when a required input is missing or the embedder is unreachable."""


class MemoryConfig(BaseModel):
    """Validated memory knobs. Every field is required: a missing knob in
    config/memory.yaml fails loud rather than silently defaulting (the load_*_config
    contract used across the codebase)."""

    model_config = {"extra": "forbid"}

    enabled: bool
    owner: str                      # stable per-user key — constant across conversations
    max_facts_injected: int         # top-k facts re-injected per turn
    refresh_every_rounds: int       # re-inject cadence inside a turn (mirrors board_state)
    recency_half_life_days: float   # recency decay half-life; >0
    embed_model: str                # the local embedding model (reused from score.py)


@dataclass
class MemoryFact:
    id: int
    user: str
    project: str                    # "" == global (surfaces in every context)
    fact: str
    created_at: float               # epoch seconds
    score: float = 0.0              # transient retrieval score (relevance × recency)


# ---- config ---------------------------------------------------------------

def load_memory_config(path: Path = _CONFIG_PATH) -> MemoryConfig:
    """The validated knobs, by absolute path. Missing file/knob fails loud — the
    config is committed and required, never silently defaulted."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MemoryError(f"{path} is not a mapping")
    return MemoryConfig.model_validate(data)


# ---- embeddings (real local model; fail loud) -----------------------------

def _resolve_base() -> str:
    """Ollama base, resolved the same way the rest of growthos does
    (actions.py / assistant.py / score.py): the configured URL, else the canonical
    local address. Matching the convention keeps one source of truth for the endpoint."""
    st = load_settings()
    return (st.ollama_base_url or "http://localhost:11434").rstrip("/")


def ollama_embed(texts: list[str], *, base_url: str, model: str) -> list[list[float]]:
    """Embed via the local Ollama `/api/embed` (the exact call score.py uses). Fails
    loud if the endpoint is unreachable or returns the wrong shape — memory never
    fabricates a vector or degrades to keyword matching."""
    if not texts:
        return []
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(f"{base_url}/api/embed", json={"model": model, "input": texts})
            r.raise_for_status()
            payload = r.json()
    except httpx.HTTPError as exc:
        raise MemoryError(f"embedder unreachable at {base_url}/api/embed: {exc}") from exc
    vecs = payload.get("embeddings")
    if not isinstance(vecs, list) or len(vecs) != len(texts):
        raise MemoryError(
            f"/api/embed returned {type(vecs).__name__} of "
            f"{len(vecs) if isinstance(vecs, list) else '?'} for {len(texts)} inputs")
    return vecs


# ---- pure scoring (no I/O; unit-tested) -----------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise MemoryError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def _recency_factor(age_seconds: float, *, half_life_days: float) -> float:
    """Exponential recency decay in (0, 1]: a just-written fact scores 1.0, one
    `half_life_days` old scores 0.5. This is the 'recency ×' in 'recency × relevance' —
    one principled knob, no fabricated weight balance."""
    if half_life_days <= 0:
        raise MemoryError(f"recency_half_life_days must be > 0, got {half_life_days}")
    half_life_seconds = half_life_days * 86400.0
    return math.exp(-max(age_seconds, 0.0) * math.log(2) / half_life_seconds)


# ---- the store ------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user       TEXT    NOT NULL,
    project    TEXT    NOT NULL DEFAULT '',
    fact       TEXT    NOT NULL,
    embedding  TEXT    NOT NULL,          -- JSON array of floats
    created_at REAL    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1  -- 0 == forgotten/superseded
);
CREATE INDEX IF NOT EXISTS ix_memory_user_active ON memory_facts (user, active);
"""


class MemoryStore:
    """SQLite-backed per-owner fact store. Embeddings stored as JSON; retrieval scans
    the owner's active facts and ranks by cosine × recency (linear scan is right at a
    personal assistant's scale — no vector index, no extra deps). The embed function
    and clock are injected so the store is hermetic in tests and real in production."""

    def __init__(self, db_path: Path, *, embed_fn: EmbedFn, config: MemoryConfig,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self._embed = embed_fn
        self._now = clock
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _embed_one(self, text: str) -> list[float]:
        vecs = self._embed([text])
        if len(vecs) != 1:
            raise MemoryError(f"embedder returned {len(vecs)} vectors for one input")
        return vecs[0]

    def remember(self, user: str, fact: str, *, project: str = "") -> MemoryFact:
        """Persist one curated fact for `user`. Embeds eagerly (a dead embedder fails
        here, loudly, not at recall time)."""
        fact = fact.strip()
        if not fact:
            raise MemoryError("cannot remember an empty fact")
        emb = self._embed_one(fact)
        created = self._now()
        cur = self.conn.execute(
            "INSERT INTO memory_facts (user, project, fact, embedding, created_at, active)"
            " VALUES (?,?,?,?,?,1)",
            (user, project, fact, json.dumps(emb), created),
        )
        row_id = cur.lastrowid
        if row_id is None:                       # never on a successful INSERT — fail loud, don't guess
            raise MemoryError("INSERT returned no row id")
        self.conn.commit()
        return MemoryFact(id=int(row_id), user=user, project=project,
                          fact=fact, created_at=created)

    def _active(self, user: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM memory_facts WHERE user=? AND active=1", (user,)))

    def forget(self, user: str, fact: str) -> int:
        """Supersede a remembered fact. Exact text match first (deterministic); else the
        single nearest active fact by cosine (argmax — no threshold to hand-pick). Returns
        the number deactivated (0 if the user has nothing to forget)."""
        fact = fact.strip()
        exact = self.conn.execute(
            "SELECT id FROM memory_facts WHERE user=? AND active=1 AND fact=?",
            (user, fact)).fetchone()
        if exact is not None:
            self.conn.execute("UPDATE memory_facts SET active=0 WHERE id=?", (exact["id"],))
            self.conn.commit()
            return 1
        rows = self._active(user)
        if not rows:
            return 0
        q = self._embed_one(fact)
        nearest = max(rows, key=lambda r: _cosine(q, json.loads(r["embedding"])))
        self.conn.execute("UPDATE memory_facts SET active=0 WHERE id=?", (nearest["id"],))
        self.conn.commit()
        return 1

    def retrieve(self, user: str, query: str, *, project: Optional[str] = None,
                 k: Optional[int] = None) -> list[MemoryFact]:
        """Top-k of the owner's active facts by cosine × recency. `project` scopes:
        None -> all the user's facts; a value -> global ('') + that project only (so a
        project-X fact never surfaces in a project-Y context). Fails loud if the embedder
        is down — no silent recency-only degrade."""
        rows = self._active(user)
        if project is not None:
            rows = [r for r in rows if r["project"] in ("", project)]
        if not rows:
            return []
        qv = self._embed_one(query)
        now = self._now()
        out: list[MemoryFact] = []
        for r in rows:
            rel = _cosine(qv, json.loads(r["embedding"]))
            rec = _recency_factor(now - r["created_at"],
                                  half_life_days=self.config.recency_half_life_days)
            out.append(MemoryFact(id=r["id"], user=r["user"], project=r["project"],
                                  fact=r["fact"], created_at=r["created_at"],
                                  score=rel * rec))
        out.sort(key=lambda f: f.score, reverse=True)
        top = k if k is not None else self.config.max_facts_injected
        return out[:top]


# ---- rendering (pure; mirrors board_state's block) ------------------------

def render_memory_state(facts: list[MemoryFact]) -> str:
    """One compact system block, or "" when there is nothing to recall (so the harness
    appends no empty block). Pure: same facts in -> same string out."""
    if not facts:
        return ""
    lines = ["=== REMEMBERED (durable facts you saved earlier, harness-provided — "
             "recalled across conversations; you do NOT need a tool to see these) ==="]
    for f in facts:
        tag = f" [{f.project}]" if f.project else ""
        lines.append(f"  - {f.fact}{tag}")
    lines.append("=== END REMEMBERED ===")
    return "\n".join(lines)


# ---- production wiring (lazy singleton) -----------------------------------

_STORE: Optional[MemoryStore] = None


def open_store(config: Optional[MemoryConfig] = None) -> MemoryStore:
    """Build the live store: real local embedder, db under the growthos state dir.
    Path + model come from config/settings — no inline literals."""
    cfg = config or load_memory_config()
    st = load_settings()
    state_dir = Path(st.growthos_state_dir)
    if not state_dir.is_absolute():
        state_dir = _ROOT / state_dir
    base = _resolve_base()

    def embed_fn(texts: list[str]) -> list[list[float]]:
        return ollama_embed(texts, base_url=base, model=cfg.embed_model)

    return MemoryStore(state_dir / "memory.db", embed_fn=embed_fn, config=cfg)


def _store(config: Optional[MemoryConfig] = None) -> MemoryStore:
    global _STORE
    if _STORE is None:
        _STORE = open_store(config)
    return _STORE


# ---- the two intent verbs (registered into the action layer) --------------

def remember(fact: str, project: str = "") -> str:
    """Save a durable fact about the user or their work to long-term memory so you
    recall it in future conversations — stable preferences, decisions, names, and
    context the user wants kept. Do NOT use it for transient chatter. Optionally pass a
    `project` to scope the fact to one project."""
    cfg = load_memory_config()
    if not cfg.enabled:
        raise MemoryError("memory is disabled in config/memory.yaml (enabled: false)")
    saved = _store().remember(cfg.owner, fact, project=project)
    where = f" (project {saved.project})" if saved.project else ""
    return f"Remembered: {saved.fact}{where}"


def forget(fact: str) -> str:
    """Remove a previously-remembered fact from long-term memory (supersede it). Pass
    the fact or a close paraphrase; the closest matching remembered fact is removed."""
    cfg = load_memory_config()
    if not cfg.enabled:
        raise MemoryError("memory is disabled in config/memory.yaml (enabled: false)")
    n = _store().forget(cfg.owner, fact)
    return f"Forgot {n} fact(s) matching: {fact}" if n else f"Nothing remembered matches: {fact}"


# ---- re-injection (called by the gateway each turn; mirrors collect_board_state) ----

def collect_memory_state(query: str, cfg: Optional[MemoryConfig] = None) -> str:
    """Retrieve the owner's most relevant facts for `query` and render the block.
    `cfg` is passed by the gateway (loaded once at startup, like board_state's knobs);
    standalone callers omit it and it is loaded here. Never raises into the turn: a
    whole-subsystem failure (embedder/config) renders one loud ERROR line instead of
    silently showing no memory — the exact fail-loud contract board_state uses. Returns
    "" when memory is disabled or there is nothing to recall."""
    try:
        cfg = cfg or load_memory_config()
        if not cfg.enabled:
            return ""
        facts = _store(cfg).retrieve(cfg.owner, query, project=None)
        return render_memory_state(facts)
    except Exception as exc:   # noqa: BLE001 — surfaced loudly, never swallowed
        return f"=== MEMORY ERROR: {type(exc).__name__}: {exc} ==="

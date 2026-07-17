"""OpenRouterAgentHarness — a read-only code-EXECUTOR agent runtime backed by an
OpenRouter (OpenAI-compatible) model, so when the Claude/Codex subscription
lanes are exhausted their ROLES can fall back to OpenRouter armed with the same
read-only analysis workflow (see configs/assistant-routing.yaml).

Unlike claude_code_local/codex_agent (which wrap a vendor CLI/SDK with its own
agent loop), OpenRouter is a bare chat-completions API — so this adapter IS the
agent loop: a bounded read-only tool cycle (read_file / glob / grep, clamped to
the registered repo) driven by the model's tool_calls, emitting the same typed
AgentEvent vocabulary as every other harness.

TWO non-negotiable walls, both mirrored from the existing egress contract:
  * PAID EXTERNAL EGRESS. OpenRouter is a paid provider and this sends repo file
    contents off-box. It is therefore OFF unless BOTH are true: OPENROUTER_API_KEY
    is set AND the frontier-router lane is explicitly enabled
    (configs/frontier-router-budgets.yaml `enabled: true` — the operator's opt-in,
    exactly the gate the frontier CHAT lane already uses). Never available "just
    because a key exists" (that would bypass check_forbidden_providers' intent).
  * READ-ONLY. The only tools are read_file/glob/grep; every path is clamped
    inside the resolved repo root (same defense-in-depth as the other adapters —
    the wall is the tool set, not a prompt request). No write/edit/shell tool
    exists to be called.

The OpenRouter call is an injected seam (`chat_completion`) so the whole loop is
hermetic-testable with a scripted fake — no network, no key (mirrors the
FakeHarness discipline). The real client is a thin httpx POST to OpenRouter's
OpenAI-compatible /chat/completions.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import yaml

from ..events import AgentEvent
from ..protocol import ApprovalDecision, HarnessProbe, SessionStart
from ..secret_paths import is_secret_path as _is_secret_path
from ..store import SessionStoreProtocol

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BUDGETS_CONFIG = _REPO_ROOT / "configs" / "frontier-router-budgets.yaml"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_MAX_TOOL_ITERATIONS = 12          # bounded loop — never spins on the model
_MAX_READ_BYTES = 200_000          # per read_file, so one turn can't exfiltrate huge blobs
_MAX_GREP_MATCHES = 200

# Curated read-only model catalog. OpenRouter serves hundreds; this is a small,
# stable, capability-tiered set surfaced to the picker (the frontier-router
# roster lives in configs and can widen this later). Shape = ModelCatalogEntry.
_MODELS: tuple[dict[str, Any], ...] = (
    {"id": "anthropic/claude-opus-4.8", "display_name": "Claude Opus 4.8 (OpenRouter)",
     "description": "Frontier reasoning via OpenRouter — Claude-role fallback.",
     "is_default": True},
    {"id": "openai/gpt-5.5", "display_name": "GPT-5.5 (OpenRouter)",
     "description": "Frontier coding/analysis — Codex-role fallback."},
    {"id": "google/gemini-3-pro", "display_name": "Gemini 3 Pro (OpenRouter)",
     "description": "Long-context analysis fallback."},
    {"id": "deepseek/deepseek-v4", "display_name": "DeepSeek V4 (OpenRouter)",
     "description": "Low-cost deep-code fallback."},
)


def _lane_enabled() -> bool:
    """The operator's explicit opt-in for the paid OpenRouter lane — the SAME
    config gate the frontier chat lane uses. In frontier-router-budgets.yaml the
    switch lives at `default.enabled`. Missing/false = off (never guessed)."""
    if not _BUDGETS_CONFIG.is_file():
        return False
    try:
        data = yaml.safe_load(_BUDGETS_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    default = data.get("default")
    return bool(default.get("enabled")) if isinstance(default, dict) else False


# The secret-path denylist (`_is_secret_path`) is imported from
# ..secret_paths — the SINGLE source of truth shared with the Home workspace
# sandbox. The read-only wall stops WRITES; this denylist is the egress teeth
# that stops credential exfiltration to the PAID OpenRouter API.


def _resolve_repo_path(repo_id: str) -> Path:
    """Delegate to the ONE shared context resolver (registered manifests + the
    Home workspace special case). No reimplementation lives here."""
    from ..context_resolver import resolve_context_path
    return resolve_context_path(repo_id)


def _clamp(root: Path, rel: str) -> Path:
    """Resolve `rel` inside `root`, refusing any path that escapes it (symlink or
    ..). The read-only wall's teeth — a tool can never read outside the repo."""
    target = (root / rel).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"path {rel!r} escapes the repo root")
    return target


# OpenAI-format function tools — read-only by construction (no write/edit/shell).
_READ_ONLY_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a UTF-8 text file inside the repo.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "repo-relative path"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "glob", "description": "List repo-relative paths matching a glob.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "e.g. src/**/*.py"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "grep", "description": "Search file contents for a substring.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "glob": {"type": "string", "description": "optional path filter"}},
            "required": ["query"]}}},
]


def dispatch_read_only_tool(root: Path, name: str, args: dict[str, Any]) -> str:
    """Execute ONE read-only tool against the clamped repo root. Pure filesystem
    reads; raises on anything outside the wall (unknown tool, escaping path)."""
    if name == "read_file":
        rel = str(args.get("path", ""))
        if _is_secret_path(rel):
            return "(refused: secret/credential path — never sent to a paid lane)"
        target = _clamp(root, rel)
        if not target.is_file():
            return f"(no such file: {rel})"
        data = target.read_bytes()[:_MAX_READ_BYTES]
        return data.decode("utf-8", "replace")
    if name == "glob":
        # Path.glob handles `**` recursion natively (fnmatch does NOT — it
        # would miss root-level files and treat ** non-recursively).
        pattern = str(args.get("pattern", "")) or "*"
        hits = sorted(str(p.relative_to(root)) for p in _safe_glob(root, pattern)
                      if p.is_file()
                      and not _is_secret_path(str(p.relative_to(root))))
        return "\n".join(hits[:_MAX_GREP_MATCHES]) or "(no matches)"
    if name == "grep":
        query = str(args.get("query", ""))
        gl = str(args.get("glob") or "**/*")
        out: list[str] = []
        for p in _safe_glob(root, gl):
            if not p.is_file() or _is_secret_path(str(p.relative_to(root))):
                continue
            try:
                for i, line in enumerate(
                        p.read_text("utf-8", "replace").splitlines(), 1):
                    if query in line:
                        out.append(f"{p.relative_to(root)}:{i}: {line.strip()[:200]}")
                        if len(out) >= _MAX_GREP_MATCHES:
                            return "\n".join(out)
            except Exception:
                continue
        return "\n".join(out) or "(no matches)"
    raise ValueError(f"unknown or non-read-only tool: {name!r}")


def _safe_glob(root: Path, pattern: str):
    """root.glob(pattern), refusing absolute/escaping patterns. A relative glob
    can only ever yield paths inside root, so the read-only wall holds."""
    if pattern.startswith(("/", "\\")) or ".." in pattern:
        raise ValueError(f"glob pattern {pattern!r} may not be absolute or escape")
    return root.glob(pattern)


ChatCompletion = Callable[[str, list[dict], list[dict]], dict]


def _httpx_chat_completion(model: str, messages: list[dict],
                           tools: list[dict]) -> dict:
    """The real seam: one OpenRouter (OpenAI-compatible) chat/completions call.
    Only reached when the lane is enabled + key present (probe gates that)."""
    import httpx
    key = os.environ["OPENROUTER_API_KEY"]
    resp = httpx.post(
        f"{_OPENROUTER_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://llm-station.local",
                 "X-Title": "LLM Station agent session"},
        json={"model": model, "messages": messages, "tools": tools},
        timeout=180)
    resp.raise_for_status()
    return resp.json()


_SYSTEM = (
    "You are an OpenRouter-backed agent running a READ-ONLY analysis session "
    "for the llm_station repo, standing in for a Claude/Codex role when those "
    "lanes are exhausted. Follow the repo CLAUDE.md protocol. You may ONLY use "
    "read_file/glob/grep — there is no write, edit, or shell tool. Investigate, "
    "then answer concisely with concrete file:line evidence.")


class OpenRouterAgentHarness:
    """Read-only OpenRouter code executor. Holds no session state (it lives in
    the store) — same restart-recovery contract as every other harness."""

    name = "openrouter_agent"
    # Honest capability disclosure (read by the registry probe → UI): this
    # harness sends repo file contents to a PAID EXTERNAL API. The cockpit must
    # show an explicit "this context will leave the machine" confirmation before
    # the first send. Local subscription runtimes (Claude/Codex) leave this False.
    external_egress = True

    def __init__(self, store: SessionStoreProtocol, *,
                 chat_completion: ChatCompletion | None = None) -> None:
        self.store = store
        # injected for hermetic tests; the real httpx seam otherwise
        self._chat = chat_completion or _httpx_chat_completion

    async def probe(self) -> HarnessProbe:
        if not _lane_enabled():
            return HarnessProbe(
                available=False,
                detail="OpenRouter lane is disabled — set enabled: true in "
                       "configs/frontier-router-budgets.yaml (paid egress "
                       "opt-in, same gate as the frontier chat lane)")
        if not os.environ.get("OPENROUTER_API_KEY"):
            return HarnessProbe(
                available=False,
                detail="OPENROUTER_API_KEY is not set on the worker — the "
                       "lane is enabled but has no key")
        return HarnessProbe(
            available=True,
            detail="OpenRouter read-only executor — paid fallback for "
                   "Claude/Codex roles when their subscription is exhausted "
                   "(runs the same read-only workflow; sends repo files to "
                   "OpenRouter, so it is opt-in only)")

    async def list_models(self) -> list[dict[str, Any]]:
        return [dict(m, supported_efforts=[], default_effort=None,
                     context_options=[], available=True) for m in _MODELS]

    async def start_session(self, request: SessionStart) -> str:
        if request.mode != "analysis" or request.permission_profile != "read_only":
            raise RuntimeError(
                "openrouter_agent supports only mode='analysis' + "
                "permission_profile='read_only' (paid read-only fallback)")
        model = request.model or _MODELS[0]["id"]
        record = self.store.create_session(
            harness=self.name, conversation_id=request.conversation_id,
            repo_id=request.repo_id, provider_profile=request.provider_profile,
            model=model, permission_profile="read_only")
        self.store.append_event(record.session_id, AgentEvent(
            "session_started",
            {"mode": request.mode, "model": model,
             "permission_profile": "read_only", "lane": "openrouter_paid"}))
        self.store.set_status(record.session_id, "idle")
        return record.session_id

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[AgentEvent]:
        record = self.store.get(session_id)
        if record.status == "interrupted":
            yield self.store.append_event(session_id, AgentEvent(
                "session_failed", {"reason": "session was interrupted"}))
            return
        try:
            root = _resolve_repo_path(record.repo_id)
        except Exception as exc:
            yield self.store.append_event(session_id, AgentEvent(
                "session_failed", {"reason": f"repo unresolved: {exc}"}))
            return

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt}]
        model = record.model or _MODELS[0]["id"]   # always concrete (never None)
        import asyncio
        for _ in range(_MAX_TOOL_ITERATIONS):
            # the model call is sync (httpx / injected) — never block the loop
            reply = await asyncio.to_thread(
                self._chat, model, messages, _READ_ONLY_TOOLS)
            choice = (reply.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            tool_calls = msg.get("tool_calls") or []
            if reply.get("usage"):
                yield self.store.append_event(session_id, AgentEvent(
                    "usage", {"total": reply["usage"]}))
            if not tool_calls:
                yield self.store.append_event(session_id, AgentEvent(
                    "assistant_message", {"text": msg.get("content") or ""}))
                break
            # append the assistant's tool-call turn, then answer each call
            messages.append({"role": "assistant", "content": msg.get("content"),
                             "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function", {}) or {}
                name = fn.get("name", "")
                import json as _json
                try:
                    args = _json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                yield self.store.append_event(session_id, AgentEvent(
                    "tool_started", {"name": name, "args": args}))
                try:
                    result = dispatch_read_only_tool(root, name, args)
                except Exception as exc:   # the wall (bad path/tool) — surfaced, tool continues
                    result = f"(refused: {exc})"
                yield self.store.append_event(session_id, AgentEvent(
                    "tool_output", {"name": name, "output": result[:4000]}))
                yield self.store.append_event(session_id, AgentEvent(
                    "tool_finished", {"name": name}))
                messages.append({"role": "tool",
                                 "tool_call_id": call.get("id", ""),
                                 "content": result})
        else:
            yield self.store.append_event(session_id, AgentEvent(
                "warning", {"message": "reached the read-only tool-loop limit"}))
        yield self.store.append_event(session_id, AgentEvent("session_idle", {}))

    async def resolve_approval(self, session_id: str,
                               decision: ApprovalDecision) -> None:
        # read-only harness: nothing to approve (no elevated tool exists), but
        # the durable record is kept for symmetry with the protocol
        self.store.resolve_approval(
            session_id, decision.approval_id,
            approved=decision.approved, reason=decision.reason)

    async def interrupt(self, session_id: str) -> None:
        self.store.append_event(session_id, AgentEvent(
            "session_failed", {"reason": "interrupted"}))
        self.store.set_status(session_id, "interrupted")

    async def resume(self, session_id: str) -> None:
        self.store.set_status(session_id, "idle")
        self.store.append_event(session_id, AgentEvent(
            "session_started", {"resumed": True}))

    async def close(self, session_id: str) -> None:
        self.store.append_event(session_id, AgentEvent("session_closed", {}))
        self.store.set_status(session_id, "closed")

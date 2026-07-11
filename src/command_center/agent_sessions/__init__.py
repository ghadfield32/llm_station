"""Agent-session harnesses (Claude Agent SDK, Codex SDK) — a SEPARATE execution route
from GatewayCore's chat-completions model path. See WORKLOG.md "Agent-session chat
integration" and the memory note `agent-session-chat-integration` for the full plan and
Phase 0 findings.

Phase 1 (this package, current state): protocol.py + events.py + store.py +
fake_harness.py — a fully testable session/event/approval/interrupt lifecycle with NO
real SDK, NO subprocess, NO network. Real Claude/Codex adapters (Phase 2/3) and the
FastAPI /api/agent-sessions/* surface (Phase 4) are not built yet — do not assume either
exists without checking WORKLOG.md first.
"""

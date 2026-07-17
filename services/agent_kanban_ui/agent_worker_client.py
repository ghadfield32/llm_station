"""AgentWorkerClient — the cockpit's ONLY way to reach the host-side agent
worker (`cc agent-worker`, see src/command_center/agent_sessions/worker_app.py).
Owns the base URL, bearer token, and timeouts; callers never construct their own
httpx client or see the raw token. There is deliberately no GatewayCore fallback
here — an unreachable worker surfaces as an explicit transport error the caller
maps to 502, never a silent downgrade to ordinary chat (see WORKLOG.md "Agent-
session chat integration" for why that separation is load-bearing).

Sync, matching this service's existing httpx convention (see _http_probe in
app.py) — FastAPI runs plain `def` routes in a threadpool automatically, so this
never blocks the event loop when called from a sync route. The one place that
DOES need non-blocking behavior (the SSE stream, which polls repeatedly) wraps
calls in asyncio.to_thread() at the call site instead of introducing a second,
inconsistent async client here.
"""
from __future__ import annotations

import httpx


class AgentWorkerUnavailable(RuntimeError):
    """The worker could not be reached at all (connection refused/timeout/DNS) —
    distinct from the worker responding with a real (even if error) status,
    which callers should propagate as-is rather than swallow into this."""


class AgentWorkerClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentWorkerUnavailable(
                f"agent worker unreachable at {self._client.base_url}{path}: "
                f"{exc!r}") from exc

    def health(self) -> httpx.Response:
        return self._request("GET", "/health")

    def list_harnesses(self) -> httpx.Response:
        return self._request("GET", "/api/agent-harnesses")

    def list_models(self, harness_id: str) -> httpx.Response:
        return self._request("GET", f"/api/agent-harnesses/{harness_id}/models")

    def usage_collector_health(self) -> httpx.Response:
        return self._request("GET", "/api/model-usage/collector-health")

    def refresh_usage(self) -> httpx.Response:
        return self._request("POST", "/api/model-usage/refresh")

    def list_sessions(self, *, conversation_id: str | None = None,
                      repo_id: str | None = None) -> httpx.Response:
        params = {k: v for k, v in
                 {"conversation_id": conversation_id, "repo_id": repo_id}.items()
                 if v is not None}
        return self._request("GET", "/api/agent-sessions", params=params)

    def create_session(self, body: dict) -> httpx.Response:
        return self._request("POST", "/api/agent-sessions", json=body)

    def get_session(self, session_id: str) -> httpx.Response:
        return self._request("GET", f"/api/agent-sessions/{session_id}")

    def send_message(self, session_id: str, prompt: str) -> httpx.Response:
        return self._request("POST", f"/api/agent-sessions/{session_id}/messages",
                             json={"prompt": prompt})

    def build_handoff(self, session_id: str, *, to_harness: str,
                      goal: str | None = None,
                      open_questions: list[str] | None = None) -> httpx.Response:
        return self._request(
            "POST", f"/api/agent-sessions/{session_id}/handoff",
            json={"to_harness": to_harness, "goal": goal,
                  "open_questions": open_questions or []})

    def resolve_attachments(self, *, repo_id: str | None, external_egress: bool,
                            items: list) -> httpx.Response:
        return self._request(
            "POST", "/api/attachments/resolve",
            json={"repo_id": repo_id, "external_egress": external_egress,
                  "items": items})

    def get_events(self, session_id: str, after_sequence: int = 0) -> httpx.Response:
        return self._request("GET", f"/api/agent-sessions/{session_id}/events",
                             params={"after_sequence": after_sequence})

    def resolve_approval(self, session_id: str, approval_id: str, *,
                         approved: bool, reason: str = "") -> httpx.Response:
        return self._request(
            "POST", f"/api/agent-sessions/{session_id}/approvals/{approval_id}",
            json={"approved": approved, "reason": reason})

    def interrupt(self, session_id: str) -> httpx.Response:
        return self._request("POST", f"/api/agent-sessions/{session_id}/interrupt")

    def resume(self, session_id: str) -> httpx.Response:
        return self._request("POST", f"/api/agent-sessions/{session_id}/resume")

    def close_session(self, session_id: str) -> httpx.Response:
        return self._request("DELETE", f"/api/agent-sessions/{session_id}")

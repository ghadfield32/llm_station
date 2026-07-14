"""Assistant Catalog aggregator (read-only).

`build_assistant_catalog` is a PURE function: it takes the GatewayCore chat-runtime
dict, the static harness descriptors, the live harness probes (or None if the
worker is unreachable), and the two feature flags, and returns a normalized
`AssistantCatalog`. It never imports a vendor SDK, never calls the worker, and
never mutates config — so it is fully hermetic and testable, and the backend (not
React) owns every availability verdict and reason string.

Boundaries this module keeps deliberately clean:
  * GatewayCore is a COMPLETION assistant (route="gateway"); its models are the
    LiteLLM roles. Claude Code / Codex are AGENT assistants (route="agent_session")
    served by the host worker. "Auto" is a dispatcher, not a model.
  * Growth OS, boards, tasks, and repositories are CONTEXT (workspace scope), NOT
    assistants — they are described in `context_note`, never listed as options.
  * A harness the worker can't reach is still LISTED (from its static descriptor)
    with availability="unavailable" and a grounded reason — never dropped, never
    faked available.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Availability = Literal["available", "degraded", "unavailable", "not_verified"]


class AssistantModelOption(BaseModel):
    model_id: str
    display_name: str
    is_default: bool = False


class AssistantOption(BaseModel):
    assistant_id: str
    display_name: str
    kind: Literal["auto", "completion", "agent"]
    route: Literal["dispatch", "gateway", "agent_session"]

    availability: Availability
    unavailable_reason: str | None = None

    supported_modes: list[str] = Field(default_factory=list)
    default_mode: str | None = None

    model_options: list[AssistantModelOption] = Field(default_factory=list)
    default_model: str | None = None
    effort_options: list[str] = Field(default_factory=list)

    requires_repo: bool = False
    supports_read_only: bool = True
    supports_workspace_write: bool = False
    supports_mission: bool = False

    auth_mode: str
    worker_required: bool
    usage_source: str | None = None
    models_endpoint: str | None = None   # agent lanes: lazy model catalog route


class AssistantCatalog(BaseModel):
    assistants: list[AssistantOption]
    context_note: str


_CONTEXT_NOTE = (
    "Growth OS, boards, tasks, captures, and repositories are CONTEXT (workspace "
    "scope), chosen separately from the Assistant. Growth OS is the GatewayCore "
    "chat lane's action/tool layer — not a completion model and not a distinct "
    "runtime — so it never appears as an Assistant or a model."
)


def declared_harness_descriptors(*, include_fake: bool = False) -> list[dict]:
    """Static harness metadata from the ONE authoritative registry — worker- and
    SDK-independent (the descriptor factories are deferred), so the catalog can
    list Claude/Codex even when the host worker is down. Availability is overlaid
    from live probes by `build_assistant_catalog`."""
    from command_center.agent_sessions.registry import default_registry
    from command_center.agent_sessions.store import SessionStore
    reg = default_registry(SessionStore())
    out = [{"harness_id": d.harness_id, "label": d.label,
            "production": d.production, "supported_modes": list(d.supported_modes)}
           for d in reg.descriptors()]
    return [d for d in out if include_fake or d["production"]]


def _gateway_option(runtime: dict) -> AssistantOption:
    roles = runtime.get("roles") or []
    models = [AssistantModelOption(
        model_id=r["role"], display_name=r.get("label") or r["role"],
        is_default=(r["role"] == "chat")) for r in roles if r.get("role")]
    default_model = next((m.model_id for m in models if m.is_default),
                         models[0].model_id if models else None)
    enabled = bool(runtime.get("enabled"))
    error = runtime.get("error")
    if not enabled:
        availability, reason = "unavailable", \
            "chat is disabled (set KANBAN_UI_CHAT_ENABLED=1)"
    elif error:                                # model registry unreadable
        availability, reason = "degraded", f"model registry error: {error}"
    else:
        availability, reason = "available", None
    return AssistantOption(
        assistant_id="gatewaycore", display_name="GatewayCore",
        kind="completion", route="gateway",
        availability=availability, unavailable_reason=reason,
        supported_modes=["chat"], default_mode="chat",
        model_options=models, default_model=default_model,
        auth_mode="litellm", worker_required=False, usage_source="gateway")


def _agent_option(descriptor: dict, probe: dict | None,
                  *, agent_sessions_enabled: bool,
                  worker_error: str | None) -> AssistantOption:
    hid = descriptor["harness_id"]
    modes = descriptor.get("supported_modes") or []
    common = dict(
        assistant_id=hid, display_name=descriptor.get("label") or hid,
        kind="agent", route="agent_session",
        supported_modes=modes, default_mode=modes[0] if modes else None,
        requires_repo=True, supports_read_only=True,
        supports_workspace_write=("workspace" in modes),
        supports_mission=("mission" in modes),
        auth_mode="worker", worker_required=True, usage_source="agent_worker",
        models_endpoint=f"/api/agent-harnesses/{hid}/models")
    if not agent_sessions_enabled:
        return AssistantOption(availability="unavailable", **common,
            unavailable_reason="agent sessions are disabled "
            "(set KANBAN_UI_AGENT_SESSIONS_ENABLED=1)")
    if worker_error is not None:
        return AssistantOption(availability="unavailable", **common,
            unavailable_reason=f"agent worker unreachable: {worker_error}")
    if probe is None:
        return AssistantOption(availability="not_verified", **common,
            unavailable_reason="harness not reported by the worker probe")
    if probe.get("available"):
        return AssistantOption(availability="available", **common,
            unavailable_reason=None)
    return AssistantOption(availability="unavailable", **common,
        unavailable_reason=probe.get("detail")
        or "harness probe reported unavailable")


def build_assistant_catalog(
    *, runtime: dict, descriptors: list[dict],
    probes: list[dict] | None, agent_sessions_enabled: bool,
    worker_error: str | None = None,
) -> AssistantCatalog:
    """Join the completion + agent authorities into one normalized catalog.

    `probes` is the worker's live `list_harnesses` result (each with
    available/detail), or None when the worker was unreachable (then
    `worker_error` carries the grounded reason). Never raises for a down worker —
    the agents are listed unavailable-with-reason so the UI can still render them.
    """
    options: list[AssistantOption] = [
        AssistantOption(
            assistant_id="auto", display_name="Auto", kind="auto",
            route="dispatch", availability="available",
            unavailable_reason=None, auth_mode="none", worker_required=False,
            usage_source=None),
        _gateway_option(runtime),
    ]
    probe_by_id = {p.get("harness_id"): p for p in (probes or [])}
    for descriptor in descriptors:
        options.append(_agent_option(
            descriptor, probe_by_id.get(descriptor["harness_id"]),
            agent_sessions_enabled=agent_sessions_enabled,
            worker_error=worker_error))
    return AssistantCatalog(assistants=options, context_note=_CONTEXT_NOTE)

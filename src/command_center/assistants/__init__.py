"""Read-only Assistant Catalog — a VIEW that joins the three existing authorities
(GatewayCore completion roles, the agent-session harness registry, and their live
probes) into one normalized list for the cockpit UI. It owns NO model, harness, or
context data and writes nothing — it exists only so the UI stops conflating a
workspace, an agent runtime, and a completion model in one flat selector.
"""
from .catalog import (
    AssistantCatalog,
    AssistantModelOption,
    AssistantOption,
    build_assistant_catalog,
    declared_harness_descriptors,
)

__all__ = [
    "AssistantCatalog",
    "AssistantModelOption",
    "AssistantOption",
    "build_assistant_catalog",
    "declared_harness_descriptors",
]

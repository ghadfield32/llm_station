"""Real vendor harness adapters (Codex Agent, later Claude Agent). Each module
here implements the AgentHarness Protocol against one vendor's actual SDK —
never imported at package import time by registry.py (see codex_agent.py's
_import_sdk), so a deployment without the optional SDK installed still lists
every harness without crashing.
"""

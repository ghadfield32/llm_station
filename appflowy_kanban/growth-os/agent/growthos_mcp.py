"""Growth OS MCP server — thin registration layer over growthos/actions.py
(the same verified actions the local-LLM assistant uses; no community MCP
code). Run stdio for Claude Desktop/Code:

    .venv/Scripts/python.exe agent/growthos_mcp.py
HTTP mode (remote connectors, e.g. behind `tailscale serve`):
    .venv/Scripts/python.exe agent/growthos_mcp.py --http   # 127.0.0.1:8765
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)                       # .env + config/databases.json live here
sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import FastMCP    # noqa: E402

from growthos import actions  # noqa: E402

mcp = FastMCP("growthos")

# triage
mcp.tool()(actions.list_inbox)
mcp.tool()(actions.search)
mcp.tool()(actions.set_status)
# todos / kanban
mcp.tool()(actions.add_todo)
mcp.tool()(actions.list_todos)
mcp.tool()(actions.update_todo)
# betts basketball dags (board + live Airflow)
mcp.tool()(actions.list_dags)
mcp.tool()(actions.update_dag)
mcp.tool()(actions.dag_health)
# mission cards (approval-gated work intake) + execution visibility
mcp.tool()(actions.add_mission_card)
mcp.tool()(actions.list_cards)
mcp.tool()(actions.mission_status)
# project readiness + network liveness
mcp.tool()(actions.project_status)
mcp.tool()(actions.network_health)
# capture
mcp.tool()(actions.add_lesson)
mcp.tool()(actions.add_book)
mcp.tool()(actions.add_note)
mcp.tool()(actions.book_note)
mcp.tool()(actions.review_lesson)
mcp.tool()(actions.latest_brief)

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.run(transport="streamable-http")
    else:
        mcp.run()

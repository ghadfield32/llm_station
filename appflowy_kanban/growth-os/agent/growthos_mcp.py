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
from growthos.observability import logged  # noqa: E402

mcp = FastMCP("growthos")


def _reg(fn):
    # register the tool, wrapped so every MCP/Claude call is recorded to the agent-call log
    return mcp.tool()(logged(fn, "mcp"))

# triage
_reg(actions.list_inbox)
_reg(actions.search)
_reg(actions.move_item)        # title-addressed status move for the long-tail boards
# todos / kanban
_reg(actions.add_todo)
_reg(actions.list_todos)
_reg(actions.update_todo)
_reg(actions.start_todo)
_reg(actions.finish_todo)
_reg(actions.block_todo)
# betts basketball dags (board + live Airflow)
_reg(actions.list_dags)
_reg(actions.update_dag)
_reg(actions.dag_health)
# mission cards (approval-gated work intake) + execution visibility
_reg(actions.add_mission_card)
_reg(actions.list_cards)
_reg(actions.mission_status)
_reg(actions.stage_card)        # -> Ready (human then drags to Approved)
_reg(actions.block_card)
_reg(actions.reject_card)
# project readiness + network liveness
_reg(actions.project_status)
_reg(actions.network_health)
# capture
_reg(actions.add_lesson)
_reg(actions.add_book)
_reg(actions.add_note)
_reg(actions.book_note)
_reg(actions.review_lesson)
_reg(actions.latest_brief)

if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.run(transport="streamable-http")
    else:
        mcp.run()

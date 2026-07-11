"""cc agent-worker — starts the host-side agent-session worker (FastAPI + uvicorn).

Binds to 127.0.0.1 by default (override with --host / AGENT_WORKER_HOST — do not
bind to 0.0.0.0 without a real reason, this is meant to be reached only from the
cockpit container via host.docker.internal, never from outside the host).
Requires AGENT_WORKER_TOKEN and LEDGER_BASE_URL to be set — see
agent_sessions/worker_app.py for why neither has a silent fallback.

Currently serves FakeHarness only. See WORKLOG.md "Agent-session chat
integration" for what's built vs. still open.
"""
from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the host-side agent-session worker.")
    parser.add_argument("--host", default=os.environ.get("AGENT_WORKER_HOST",
                                                          "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("AGENT_WORKER_PORT", "8791")))
    args = parser.parse_args()

    import uvicorn

    from command_center.agent_sessions.worker_app import build_app

    app = build_app()   # fails loud here if AGENT_WORKER_TOKEN/LEDGER_BASE_URL unset
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

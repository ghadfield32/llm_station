"""MASTER.md truth check — fails if docs/MASTER.md drifts from implemented
reality. Encodes the invariant "a phase is not complete until docs/MASTER.md
accurately describes it": canonical runtime ids are documented, required
sections exist, documented runtime files exist AND are referenced, documented
key endpoints exist in source, and known-superseded claims never reappear.

Run standalone (`uv run python scripts/check_master_runtime_truth.py`, exits
non-zero on any problem) or via tests/test_master_runtime_truth.py. `check()`
returns a list of problem strings (empty = OK) so both callers share one logic.
Deliberately conservative — it enforces a small set of load-bearing facts, not a
brittle scan of every backticked token, so it fails ONLY on real drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# the three runtime ids that MUST always be documented (renaming one without
# updating MASTER is exactly the drift this guards against)
CANONICAL_RUNTIME_IDS = ("codex_agent", "claude_code_local", "claude_agent")

# section markers that must be present (prefix match against a heading line)
REQUIRED_SECTIONS = (
    "Current readiness snapshot",
    "## 4. Architecture",
    "### 4.5",                        # the agent lane
    "### 4.6",                        # unified Usage & Limits
    "### 4.8",                        # chat-first product surface + Universal Capture
    "### 4.9",                        # canonical work graph + navigation receipts
    "## 5. Model lanes and routing",
    "## 11. Module tree",
    "## 14. Change log",
)

# runtime files that must both EXIST on disk and be REFERENCED in MASTER.md.
# (disk_path, reference_fragment) — MASTER cites the relative form inside its
# module tree, not the full src/ path, so the fragment is what must appear.
REQUIRED_FILES = (
    ("src/command_center/agent_sessions/adapters/codex_agent.py", "adapters/codex_agent.py"),
    ("src/command_center/agent_sessions/adapters/claude_code_local.py",
     "adapters/claude_code_local.py"),
    ("src/command_center/agent_sessions/adapters/claude_agent.py", "adapters/claude_agent.py"),
    ("src/command_center/usage/collectors/codex_app_server.py", "collectors/codex_app_server.py"),
    ("src/command_center/usage/collectors/claude_agent.py", "collectors/claude_agent.py"),
    ("docs/runbooks/agent-sessions-activation.md", "agent-sessions-activation.md"),
    # Universal Capture (PR #44) — the intake record MASTER §4.8 documents.
    ("src/command_center/intake/schemas.py", "src/command_center/intake/"),
    # Canonical work graph (§4.9, PRs #48/#50/#51 + chat receipts).
    ("src/command_center/work_graph/schemas.py", "work_graph/schemas.py"),
    ("src/command_center/work_graph/ledger_schema.py", "work_graph/ledger_schema.py"),
    ("src/command_center/work_graph/planner.py", "work_graph/planner.py"),
    ("src/command_center/work_graph/router.py", "work_graph/router.py"),
    ("src/command_center/work_graph/telemetry_schema.py", "work_graph/telemetry"),
    ("src/command_center/work_graph/calibration.py", "work_graph/calibration.py"),
)

# claims that were true once and would now be a lie — must never reappear
OBSOLETE_PHRASES = (
    "wires ONLY the FakeHarness",
    "Claude Agent is still a planned runtime, not shipped",
    "the collectors/ (fake) — real Codex/Claude/OpenRouter",
)

# endpoints MASTER documents that must exist literally in the named source(s).
# only enforced when MASTER actually claims the endpoint (so adding a doc claim
# without the code, or deleting the code without the doc, both fail).
REQUIRED_ENDPOINTS = (
    ("/api/agent-harnesses/{harness_id}/models",
     ("src/command_center/agent_sessions/worker_app.py",
      "services/agent_kanban_ui/app.py")),
    ("/api/model-usage", ("services/agent_kanban_ui/app.py",)),
    # chat-first product surface (§4.8, PRs #42–#44) — documented AND implemented.
    ("/api/agent-sessions/{session_id}/promote", ("services/agent_kanban_ui/app.py",)),
    ("/api/chat/promote", ("services/agent_kanban_ui/app.py",)),
    ("/api/board-module", ("services/agent_kanban_ui/app.py",)),
    ("/api/captures", ("services/agent_kanban_ui/app.py",)),
    ("/api/intake/inbox", ("services/agent_kanban_ui/app.py",)),
    # canonical work graph (§4.9) — documented AND implemented.
    ("/api/work-graph", ("services/agent_kanban_ui/app.py",)),
    ("/api/chat/work-items/preview", ("services/agent_kanban_ui/app.py",)),
    ("/api/chat/work-items/commit", ("services/agent_kanban_ui/app.py",)),
    ("/api/captures/{capture_id}/convert", ("services/agent_kanban_ui/app.py",)),
    ("/api/work-items/route", ("services/agent_kanban_ui/app.py",)),
    ("/api/work-items/plan-summary", ("services/agent_kanban_ui/app.py",)),
    ("/api/routing-corrections", ("services/agent_kanban_ui/app.py",)),
    ("/api/routing-rules", ("services/agent_kanban_ui/app.py",)),
)


def check(master_text: str | None = None, repo_root: Path | str = REPO_ROOT) -> list[str]:
    """Return a list of drift problems (empty = MASTER.md is truthful)."""
    root = Path(repo_root)
    text = (master_text if master_text is not None
            else (root / "docs" / "MASTER.md").read_text(encoding="utf-8"))
    problems: list[str] = []

    for rid in CANONICAL_RUNTIME_IDS:
        if rid not in text:
            problems.append(f"MASTER.md does not document canonical runtime id {rid!r}")
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            problems.append(f"MASTER.md is missing required section marker {sec!r}")
    for phrase in OBSOLETE_PHRASES:
        if phrase in text:
            problems.append(f"MASTER.md still contains a superseded claim: {phrase!r}")
    for disk_path, fragment in REQUIRED_FILES:
        if not (root / disk_path).exists():
            problems.append(f"MASTER.md documents a nonexistent file: {disk_path}")
        elif fragment not in text:
            problems.append(
                f"runtime file exists but is not referenced in MASTER.md: "
                f"{disk_path} (expected fragment {fragment!r})")
    for endpoint, sources in REQUIRED_ENDPOINTS:
        if endpoint not in text:
            continue
        found = any((root / s).exists()
                    and endpoint in (root / s).read_text(encoding="utf-8", errors="ignore")
                    for s in sources)
        if not found:
            problems.append(
                f"MASTER.md documents endpoint {endpoint} not found in any of {sources}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("MASTER.md truth check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("MASTER.md truth check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

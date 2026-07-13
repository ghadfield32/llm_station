"""The MASTER.md truth gate (scripts/check_master_runtime_truth.py): the current
docs/MASTER.md must be truthful, and the check must actually FAIL on real drift
(a missing runtime id, a superseded claim, a missing section, a documented file
that doesn't exist). This is the automated half of "a phase is not complete
until MASTER.md describes it".
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_master_runtime_truth.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_master_runtime_truth", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MASTER_TEXT = (REPO_ROOT / "docs" / "MASTER.md").read_text(encoding="utf-8")


def test_current_master_is_truthful():
    problems = _load().check()
    assert problems == [], "MASTER.md drift:\n" + "\n".join(problems)


def test_fails_when_a_canonical_runtime_id_is_undocumented():
    mod = _load()
    doctored = _MASTER_TEXT.replace("claude_code_local", "claude_local_XX")
    problems = mod.check(master_text=doctored)
    assert any("claude_code_local" in p for p in problems)


def test_fails_on_a_superseded_claim():
    mod = _load()
    doctored = _MASTER_TEXT + "\n\nworker_app.py wires ONLY the FakeHarness.\n"
    problems = mod.check(master_text=doctored)
    assert any("superseded claim" in p for p in problems)


def test_fails_when_a_required_section_is_removed():
    mod = _load()
    doctored = _MASTER_TEXT.replace("## 14. Change log", "## 14. (removed)")
    problems = mod.check(master_text=doctored)
    assert any("14. Change log" in p for p in problems)


def test_fails_when_a_documented_file_reference_is_dropped():
    mod = _load()
    # drop the runbook reference while the file still exists on disk
    doctored = _MASTER_TEXT.replace("agent-sessions-activation.md", "gone.md")
    problems = mod.check(master_text=doctored)
    assert any("agent-sessions-activation.md" in p for p in problems)


def test_check_returns_a_list_and_main_is_wired():
    mod = _load()
    assert isinstance(mod.check(), list)
    assert callable(mod.main)

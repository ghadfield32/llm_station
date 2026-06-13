"""
Judge Array — pre-commit / pre-push LLM judges.

Implements the "array of judges per stage" requirement. Each stage runs several
judges; cheap/local ones run first and only a CONTESTED verdict escalates to a
stronger (and cross-provider) model. All calls go through LiteLLM so they're
budgeted and logged, and every verdict is written to the Task Ledger.

Stages:
  pre-commit : diff-judge, secret-judge, defensive-coding-judge
  pre-push   : security-skeptic (cross-provider), scope-judge

Designed to BLOCK on: secrets, dangerous shell, out-of-scope sprawl, and
defensive-coding bloat (your explicit style rule: minimal, data-driven changes).
"""

import os
import json
import argparse
from typing import Optional

import httpx
import yaml

LITELLM = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000/v1")
KEY = os.environ.get("JUDGE_GATE_KEY", "")
LEDGER = os.environ.get("LEDGER_BASE_URL", "http://ledger:8090")
STANDARDS_CONFIG = os.environ.get("STANDARDS_CONFIG", "configs/standards.yaml")

# Cheap-first model aliases (defined in litellm-config.yaml). A contested
# verdict re-runs on the escalation alias, which is a DIFFERENT provider.
CHEAP = os.environ.get("JUDGE_CHEAP_MODEL", "triage")          # local/Haiku
ESCALATE = os.environ.get("JUDGE_ESCALATE_MODEL", "security-judge")  # cross-provider

# ----- Judge definitions: name -> (system prompt, blocking?) -----------------

JUDGES = {
    "diff-judge": (
        """You review a code diff for correctness and obvious bugs. Respond ONLY JSON:
{"verdict":"approve"|"block","severity":"low"|"medium"|"high","findings":[...],
 "summary":"..."}. Block on logic errors, broken types, or removed tests.""",
        True,
    ),
    "secret-judge": (
        """You scan a diff for secrets/credentials: API keys, tokens, passwords,
private keys, .env contents, connection strings. Respond ONLY JSON:
{"verdict":"approve"|"block","severity":"low"|"medium"|"high","findings":[...],
 "summary":"..."}. ANY plausible secret => block, severity high.""",
        True,
    ),
    "defensive-coding-judge": (
        """You enforce a strict 'no defensive coding / minimal change' style. The author
prefers data-driven values over hardcoded fallbacks and dislikes speculative
guards. FLAG and block when the diff adds, without a stated reason:
- try/except that swallows errors broadly
- redundant null/None guards on values that can't be null in context
- 'just in case' branches, dead config flags, or unused parameters
- hardcoded fallback constants where a computed/data-driven value belongs
Respond ONLY JSON:
{"verdict":"approve"|"block","severity":"low"|"medium"|"high","findings":[...],
 "summary":"..."}. Approve clean, minimal diffs. Block defensive bloat.""",
        True,
    ),
    "scope-judge": (
        """You verify a diff matches the STATED TASK and is not sprawling. Respond ONLY JSON:
{"verdict":"approve"|"block","severity":"low"|"medium"|"high","in_scope":true|false,
 "findings":[...],"summary":"..."}. Block if the diff changes files or behavior
unrelated to the task, or is large enough to warrant human review.""",
        True,
    ),
    "security-skeptic": (
        """You are an adversarial security + architecture reviewer reviewing a diff
produced by a DIFFERENT model. Check for secrets, dangerous shell (rm -rf,
chmod -R, curl|bash, force push, sudo), network exfiltration, out-of-scope
changes, weakened tests/lint, and irreversible/data-loss migrations.
Respond ONLY JSON:
{"verdict":"approve"|"block","severity":"low"|"medium"|"high","findings":[...],
 "summary":"..."}. Default to block if anything is unclear or high-severity.""",
        True,
    ),
}

STAGES = {
    "pre-commit": ["diff-judge", "secret-judge", "defensive-coding-judge"],
    "pre-push":   ["security-skeptic", "scope-judge"],
}


def _standards_text() -> str:
    if not STANDARDS_CONFIG or not os.path.exists(STANDARDS_CONFIG):
        return ""
    data = yaml.safe_load(open(STANDARDS_CONFIG, encoding="utf-8")) or {}
    lines = ["", "STANDING ENGINEERING STANDARDS:"]
    lines += [f"- {p}" for p in data.get("core_principles", [])]
    for profile in data.get("profiles", []):
        lines.append(f"- Profile {profile.get('name')}:")
        lines += [f"  - {p}" for p in profile.get("principles", [])]
        if profile.get("blocked_patterns"):
            lines.append("  Blocked patterns:")
            lines += [f"  - {p}" for p in profile.get("blocked_patterns", [])]
    return "\n".join(lines)


def _call(model: str, system: str, user: str) -> dict:
    if not KEY:
        raise SystemExit("JUDGE_GATE_KEY not set")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": 700,
    }
    r = httpx.post(f"{LITELLM}/chat/completions",
                   headers={"Authorization": f"Bearer {KEY}"},
                   json=payload, timeout=120)
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    txt = txt.replace("```json", "").replace("```", "").strip()
    return json.loads(txt)


def run_judge(name: str, task: str, diff: str, tests: str = "") -> dict:
    system, _blocking = JUDGES[name]
    user = (
        f"STATED TASK:\n{task}\n\n"
        f"DIFF:\n{diff}\n\n"
        f"TEST OUTPUT:\n{tests or '(none)'}"
        f"{_standards_text()}"
    )
    # cheap first
    verdict = _call(CHEAP, system, user)
    # escalate contested or high-severity verdicts to a cross-provider model
    if verdict.get("verdict") == "block" or verdict.get("severity") == "high":
        strong = _call(ESCALATE, system, user)
        # require BOTH to clear; if either blocks, block
        if strong.get("verdict") == "block":
            verdict = strong
        verdict["escalated"] = True
    verdict["judge"] = name
    return verdict


def run_stage(stage: str, task: str, diff: str, tests: str = "",
              mission_id: Optional[str] = None) -> dict:
    if stage not in STAGES:
        raise SystemExit(f"unknown stage {stage}; choose {list(STAGES)}")
    results, allow = [], True
    for name in STAGES[stage]:
        v = run_judge(name, task, diff, tests)
        results.append(v)
        if v.get("verdict") == "block":
            allow = False
        if mission_id:
            _record(mission_id, stage, v)
    return {"stage": stage, "allow": allow, "results": results}


def _record(mission_id: str, stage: str, verdict: dict):
    try:
        httpx.post(f"{LEDGER}/mission/{mission_id}/event",
                   json={"kind": "judge_verdict",
                         "payload": {"stage": stage, **verdict}}, timeout=15)
    except Exception:
        pass  # ledger is best-effort here; never block a judge on logging


# ----- judgectl CLI: invoke any judge/stage at any time ----------------------

def _read(path: Optional[str]) -> str:
    if not path or path == "-":
        import sys
        return sys.stdin.read()
    with open(path) as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(prog="judgectl",
                                 description="Run pre-commit/pre-push LLM judges")
    ap.add_argument("--stage", required=True, choices=list(STAGES))
    ap.add_argument("--task", required=True, help="the stated task description")
    ap.add_argument("--diff", default="-", help="path to diff file, or - for stdin")
    ap.add_argument("--tests", default="", help="path to test output (optional)")
    ap.add_argument("--mission", default=None, help="ledger mission id (optional)")
    args = ap.parse_args()

    out = run_stage(args.stage, args.task, _read(args.diff),
                    _read(args.tests) if args.tests else "", args.mission)
    print(json.dumps(out, indent=2))
    raise SystemExit(0 if out["allow"] else 2)   # exit 2 => blocked (hook fails)


if __name__ == "__main__":
    main()

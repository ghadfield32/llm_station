"""
Judge Gate — the "panel of judges" front door.

What it does, per incoming request:
  1. TRIAGE: asks a cheap model to classify the request into a risk level (L0-L4),
     pick which repo/tools it touches, and decide whether human approval is required.
  2. ROUTE:  maps the risk level to the cheapest adequate model alias.
  3. GATE:   anything at L3 (external write: push / PR / comment) or L4 (dangerous:
     merge / deploy / delete / rotate secrets / publish) is held for human approval.
  4. REVIEW: provides a /skeptic endpoint that runs a CROSS-PROVIDER review of a diff
     before it's allowed to leave the sandbox.

It calls models only through LiteLLM, so every call is budgeted and logged.
This is intentionally small and auditable — extend the policy, don't hide it.
"""

import os
import json
import logging
from enum import IntEnum
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Self-contained logger so judge-gate's model calls are visible in
# `docker compose logs judge-gate` regardless of uvicorn's logging config.
# Every LLM call logs model + finish_reason + token usage; a failed call logs
# the FULL raw model output, so a 502 here is diagnosable instead of opaque.
log = logging.getLogger("judge_gate")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s judge_gate: %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000/v1")
JUDGE_GATE_KEY   = os.environ.get("JUDGE_GATE_KEY", "")
TRIAGE_MODEL     = os.environ.get("TRIAGE_MODEL", "triage")
SKEPTIC_MODEL    = os.environ.get("SKEPTIC_MODEL", "security-judge")
STANDARDS_CONFIG = os.environ.get("STANDARDS_CONFIG", "configs/standards.yaml")

app = FastAPI(title="Judge Gate", version="1.0.0")


class Risk(IntEnum):
    L0_READONLY      = 0   # summarize, explain, search — no changes
    L1_PLAN          = 1   # plan only, no edits
    L2_LOCAL_CHANGE  = 2   # edit branch + run tests, no network writes
    L3_EXTERNAL_WRITE = 3  # push branch / open PR / comment on issue
    L4_DANGEROUS     = 4   # merge / deploy / delete data / rotate secrets / publish


# Which model alias each risk level is allowed to use by default.
ROUTE = {
    Risk.L0_READONLY:       "triage",
    Risk.L1_PLAN:           "planner",
    Risk.L2_LOCAL_CHANGE:   "coder",
    Risk.L3_EXTERNAL_WRITE: "coder",
    Risk.L4_DANGEROUS:      "architect-judge",
}

# Levels that may NEVER run without an explicit human approval.
REQUIRES_HUMAN = {Risk.L3_EXTERNAL_WRITE, Risk.L4_DANGEROUS}

# Repos you consider sensitive — even L2 here gets extra scrutiny.
SENSITIVE_REPOS = {"betts_basketball", "nba-forecasting", "prospects-forecasting"}


TRIAGE_SYSTEM = """You are a strict triage classifier for an autonomous coding system.
Classify the user's request into exactly one risk level and respond with ONLY a JSON
object (no prose, no markdown fences):

{"risk": <0-4>, "repo": "<repo name or unknown>", "tools": ["..."],
 "reason": "<one short sentence>"}

Risk levels:
0 = read-only (summarize, explain, search docs; no file or network changes)
1 = plan only (produce a plan; no edits)
2 = local code change (edit a branch, run tests; NO network writes, NO git push)
3 = external write (git push, open PR, comment on an issue/PR)
4 = dangerous (merge PR, deploy, delete data, rotate/read secrets, publish a package,
    terraform apply, force push, sudo, rm -rf)

When uncertain, choose the HIGHER risk level. Never downgrade a request that mentions
push, merge, deploy, secrets, credentials, delete, or production."""


SKEPTIC_SYSTEM = """You are an adversarial security + architecture reviewer. You are
reviewing a code diff produced by a DIFFERENT model. Be skeptical. Check for:
- secrets, credentials, tokens, or .env content added or printed
- dangerous shell (rm -rf, chmod -R, curl|bash, force push, sudo)
- network exfiltration or calls to unexpected hosts
- changes outside the stated scope of the task
- missing or weakened tests; disabled lint/typecheck
- architectural risk (tight coupling, irreversible migrations, data loss)

Respond with ONLY a JSON object:
{"verdict": "approve" | "block", "severity": "low"|"medium"|"high",
 "findings": ["..."], "summary": "<one sentence>"}
Default to "block" if anything is unclear or any high-severity finding exists."""


class ClassifyIn(BaseModel):
    request: str
    repo: Optional[str] = None


class ClassifyOut(BaseModel):
    risk: int
    risk_name: str
    repo: str
    model_alias: str
    requires_human_approval: bool
    sensitive_repo: bool
    reason: str


class SkepticIn(BaseModel):
    task: str
    diff: str
    test_output: Optional[str] = ""


class ProactiveJudgeIn(BaseModel):
    check: str
    judges: list[str] = []
    evidence: dict


def _standards_text() -> str:
    if not STANDARDS_CONFIG or not os.path.exists(STANDARDS_CONFIG):
        return ""
    data = yaml.safe_load(open(STANDARDS_CONFIG, encoding="utf-8")) or {}
    lines = ["", "Standing engineering standards:"]
    lines += [f"- {p}" for p in data.get("core_principles", [])]
    for profile in data.get("profiles", []):
        lines.append(f"- Profile {profile.get('name')}:")
        lines += [f"  - {p}" for p in profile.get("principles", [])]
        if profile.get("blocked_patterns"):
            lines.append("  Blocked patterns:")
            lines += [f"  - {p}" for p in profile.get("blocked_patterns", [])]
    return "\n".join(lines)


def _with_standards(system: str) -> str:
    return system + _standards_text()


MAX_TOKENS = 600


async def _llm(model: str, system: str, user: str) -> dict:
    """Call a model through LiteLLM and parse the JSON object it returns.

    This function reports *why* a call fails instead of hiding it. It logs the
    model, finish_reason, and token usage on every call, and on a failure logs
    the FULL raw model output. The two failure modes are reported distinctly,
    because they have different fixes:
      - finish_reason == "length": the reply was cut off at MAX_TOKENS, so the
        JSON is structurally incomplete. The fix is to shorten the prompt/
        evidence or raise the cap deliberately — NOT to treat it as "bad JSON".
      - otherwise unparseable: the model genuinely returned non-JSON (prose,
        extra objects). The fix is a prompt/model issue.
    Earlier this raised a single generic "did not return JSON" with the content
    truncated to 300 chars, which made a real 502 impossible to diagnose.
    """
    if not JUDGE_GATE_KEY:
        raise HTTPException(500, "JUDGE_GATE_KEY not configured")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _with_standards(system)},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {JUDGE_GATE_KEY}"},
            json=payload,
        )
    if r.status_code != 200:
        log.error("LiteLLM HTTP %s for model=%s: %s", r.status_code, model, r.text[:500])
        raise HTTPException(502, f"LiteLLM error {r.status_code}: {r.text[:300]}")

    body = r.json()
    choice = body["choices"][0]
    finish = choice.get("finish_reason")
    usage = body.get("usage", {})
    content = choice["message"]["content"]
    log.info("model=%s finish_reason=%s completion_tokens=%s prompt_tokens=%s",
             model, finish, usage.get("completion_tokens"), usage.get("prompt_tokens"))

    # A length-capped reply is incomplete by construction — report exactly that,
    # with the numbers that prove it, rather than mislabeling it as non-JSON.
    if finish == "length":
        log.error("model=%s TRUNCATED at max_tokens=%s (completion_tokens=%s); raw=%r",
                  model, MAX_TOKENS, usage.get("completion_tokens"), content)
        raise HTTPException(502, (
            f"{model} reply truncated at max_tokens={MAX_TOKENS} "
            f"(completion_tokens={usage.get('completion_tokens')}); the prompt is "
            "over-producing — shorten the evidence/prompt or raise the cap."))

    # Be tolerant of accidental code fences, then parse.
    text = content.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error("model=%s returned non-JSON (finish_reason=%s): %r", model, finish, content)
        raise HTTPException(502, (
            f"{model} returned non-JSON (finish_reason={finish}): {text[:500]}")) from e


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyOut)
async def classify(body: ClassifyIn):
    """Step 1+2+3: triage the request, route it, and decide on approval."""
    result = await _llm(TRIAGE_MODEL, TRIAGE_SYSTEM, body.request)

    risk = Risk(int(result.get("risk", 4)))               # fail safe → highest risk
    repo = (body.repo or result.get("repo") or "unknown")
    sensitive = repo in SENSITIVE_REPOS

    model_alias = ROUTE[risk]
    needs_human = risk in REQUIRES_HUMAN

    # Hard rule: any change at all to a sensitive repo gets a human in the loop.
    if sensitive and risk >= Risk.L2_LOCAL_CHANGE:
        needs_human = True

    return ClassifyOut(
        risk=int(risk),
        risk_name=risk.name,
        repo=repo,
        model_alias=model_alias,
        requires_human_approval=needs_human,
        sensitive_repo=sensitive,
        reason=result.get("reason", ""),
    )


@app.post("/skeptic")
async def skeptic(body: SkepticIn):
    """Step 4: cross-provider review of a diff BEFORE it may leave the sandbox.

    The model used here (SKEPTIC_MODEL) is a different provider than the coder,
    so it won't rubber-stamp its own family's output.
    """
    user = (
        f"TASK:\n{body.task}\n\n"
        f"DIFF:\n{body.diff}\n\n"
        f"TEST OUTPUT:\n{body.test_output or '(none provided)'}"
    )
    review = await _llm(SKEPTIC_MODEL, SKEPTIC_SYSTEM, user)
    # Normalize so callers can branch on a single field.
    review["allow_push"] = review.get("verdict") == "approve" and \
        review.get("severity") != "high"
    return review


PROACTIVE_SYSTEM = """You judge scheduled operational checks for a personal
command center. Decide whether the supplied evidence is healthy. Respond with
ONLY JSON:
{"healthy": true|false, "summary": "<one short sentence>", "findings": ["..."]}
Default to healthy=false if evidence is missing, stale, contradictory, or
suggests a real failure. Do not propose edits here; failed checks open normal
Ledger missions downstream."""


@app.post("/proactive/judge")
async def proactive_judge(body: ProactiveJudgeIn):
    """Classify proactive check evidence as healthy/unhealthy.

    The proactive runner is intentionally dumb: it gathers evidence and sends it
    here, while this service handles cheap-first model routing through LiteLLM.
    """
    user = json.dumps(
        {
            "check": body.check,
            "judges": body.judges,
            "evidence": body.evidence,
        },
        indent=2,
        sort_keys=True,
    )
    verdict = await _llm(TRIAGE_MODEL, PROACTIVE_SYSTEM, user)
    return {
        "healthy": bool(verdict.get("healthy", False)),
        "summary": verdict.get("summary", "proactive check returned no summary"),
        "findings": verdict.get("findings", []),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)

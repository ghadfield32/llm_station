"""
Human attention as a constrained resource.

The bottleneck in a supervised loop is not compute — it is the human who has to
approve, verify, and promote. This module measures that queue and compresses it into
a morning brief that surfaces the few decisions worth making today WITHOUT hiding
uncertainty: three highest-value decisions, anything safety- or time-critical, how
complete the evidence is, the rough review effort, a recommended action, and a link
to the raw evidence.

It reads the experiment registry (authoritative). Pass `now_iso` for deterministic
output in tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .registry import ExperimentRegistry
from .schema import ExperimentDefinition


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_hours(ts: str, now_iso: str) -> float:
    try:
        a = datetime.fromisoformat(ts)
        b = datetime.fromisoformat(now_iso)
        return max(0.0, (b - a).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 0.0


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[k]


def attention_metrics(reg: ExperimentRegistry, *, now_iso: str | None = None) -> dict:
    now_iso = now_iso or _now_iso()
    exps = reg.list_experiments()
    awaiting_verif = [e for e in exps if e["status"] == "Awaiting Verification"]
    awaiting_promo = [e for e in exps if e["status"] == "Awaiting Human Promotion"]
    waiting = awaiting_verif + awaiting_promo
    ages = [_age_hours(e["updated_at"], now_iso) for e in waiting]

    reached_verification = [e for e in exps if e["verifier_verdict"]]
    eligible = [e for e in exps if e["status"] not in ("Proposed", "Baseline Ready", "Running")]
    promoted = [e for e in exps if e["status"] == "Promoted"]
    rolled_back = [e for e in exps if e["status"] == "Rolled Back"]

    # reviewer override: a human decision that disagrees with the verifier verdict
    overrides = 0
    decided = 0
    for e in exps:
        if e["human_decision"]:
            decided += 1
            v, h = e["verifier_verdict"], e["human_decision"]
            if (v == "PASS" and h == "reject") or (v == "FAIL" and h == "approve"):
                overrides += 1

    # evidence volume per pending review (artifact count)
    ev_vol = [len(reg.artifacts(e["experiment_id"])) for e in waiting]

    return {
        "experiments_awaiting_verification": len(awaiting_verif),
        "experiments_awaiting_human_promotion": len(awaiting_promo),
        "median_queue_age_hours": round(_median(ages), 2),
        "p95_queue_age_hours": round(_percentile(ages, 95), 2),
        "evidence_volume_per_review": round(_median([float(x) for x in ev_vol]), 1),
        "reviewer_override_rate": round(overrides / decided, 3) if decided else 0.0,
        "post_approval_regression_rate": round(
            len(rolled_back) / max(1, len(promoted) + len(rolled_back)), 3),
        "concurrent_human_decisions": len(awaiting_promo),
        "pct_independently_reproduced": round(
            len(reached_verification) / len(eligible), 3) if eligible else 0.0,
        "now": now_iso,
    }


def _recommended_action(exp: dict) -> str:
    if exp["status"] == "Awaiting Human Promotion":
        if exp["verifier_verdict"] == "PASS":
            return "approve (start canary)"
        return "request more evidence"
    if exp["status"] == "Awaiting Verification":
        return "run independent verifier"
    return "review"


def _value_rank(exp: dict, defn: ExperimentDefinition | None) -> tuple:
    # higher tuple sorts first: human-promotion before verification; safety/PASS first
    promo = 1 if exp["status"] == "Awaiting Human Promotion" else 0
    verified_pass = 1 if exp["verifier_verdict"] == "PASS" else 0
    return (promo, verified_pass)


def morning_brief(reg: ExperimentRegistry, *, now_iso: str | None = None,
                  evidence_base: str = "data/improvement") -> str:
    now_iso = now_iso or _now_iso()
    m = attention_metrics(reg, now_iso=now_iso)
    exps = reg.list_experiments()
    waiting = [e for e in exps
               if e["status"] in ("Awaiting Verification", "Awaiting Human Promotion")]

    def sort_key(e):
        defn_raw = reg.definition(e["experiment_id"])
        defn = ExperimentDefinition.model_validate(defn_raw) if defn_raw else None
        return (_value_rank(e, defn), _age_hours(e["updated_at"], now_iso))

    waiting.sort(key=sort_key, reverse=True)
    top = waiting[:3]

    lines = ["## Improvement queue — decisions for today", ""]
    if not waiting:
        lines.append("_No experiments awaiting a human decision._")
    else:
        lines.append(f"**{len(waiting)}** experiment(s) await a human decision "
                     f"(median age {m['median_queue_age_hours']}h, "
                     f"p95 {m['p95_queue_age_hours']}h).")
        lines.append("")
        lines.append("### Top decisions")
        for i, e in enumerate(top, 1):
            eid = e["experiment_id"]
            arts = reg.artifacts(eid)
            evidence_ok = "complete" if any(a["kind"] == "verifier_report" for a in arts) \
                else "partial (no verifier report yet)"
            effort = "low" if len(arts) <= 6 else "moderate"
            lines.append(
                f"{i}. **{eid}** — {e.get('title', '')}  \n"
                f"   status: {e['status']} · verifier: {e['verifier_verdict'] or '—'} · "
                f"risk: {e['risk_tier']}  \n"
                f"   recommended: **{_recommended_action(e)}** · evidence: {evidence_ok} · "
                f"review effort: {effort}  \n"
                f"   raw evidence: `{evidence_base}/{eid}/`")
        # safety / time-sensitive callout
        stale = [e for e in waiting if _age_hours(e["updated_at"], now_iso) > 48]
        if stale:
            lines.append("")
            lines.append(f"⚠️ **{len(stale)} item(s) older than 48h** — queue is backing up.")

    lines += [
        "",
        "### Queue health",
        f"- awaiting verification: {m['experiments_awaiting_verification']}",
        f"- awaiting human promotion: {m['experiments_awaiting_human_promotion']}",
        f"- independently reproduced: {int(m['pct_independently_reproduced'] * 100)}%",
        f"- reviewer override rate: {m['reviewer_override_rate']}",
        f"- post-approval regression rate: {m['post_approval_regression_rate']}",
    ]
    if m["experiments_awaiting_human_promotion"] >= 5:
        lines.append("- ⚠️ bottleneck: 5+ experiments waiting on human promotion")
    return "\n".join(lines)

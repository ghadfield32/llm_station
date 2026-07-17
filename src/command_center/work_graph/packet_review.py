"""Phase 6 live review ORCHESTRATION — run advisory agent reviews into a
readiness packet's slots, then a judge synthesis.

Builds directly on the invariant-enforced set_review seam: every review this
orchestration records is `reviewer_kind="agent"` and ADVISORY — it can be
`reviewed` (no blocking findings) or `changes_requested`, but NEVER `approved`.
Only a human approval satisfies the readiness gate, so running these reviews
can never, by itself, unlock commit (plan §6 "an agent review can never approve
or commit work").

Everything here is pure over injected callables:
  * `review_fn(role, ReviewInput) -> AgentReviewResult` — one reviewer. The
    production impl spawns a READ-ONLY agent session (Claude/Codex/OpenRouter);
    a scripted fake proves the flow hermetically with no quota.
  * `judge_fn(list[AgentReviewResult]) -> AgentReviewResult` — synthesis across
    the independent reviews.
  * `record(...)` — the set_review-backed sink (enforces the advisory wall).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# An advisory recommendation an agent reviewer may return. Deliberately has no
# "approve" — approval is a human act, mapped away below even if a reviewer asks.
Recommendation = str   # "pass" | "changes" | "concern"

_RECOMMENDATION_TO_STATUS = {
    "pass": "reviewed",              # read it, no blocking findings (advisory)
    "changes": "changes_requested",
    "concern": "changes_requested",
}


@dataclass(frozen=True)
class ReviewInput:
    """The bounded, read-only view of a packet a reviewer sees."""
    packet_id: str
    revision: int
    title: str
    plan_item_count: int
    boards: tuple[str, ...]
    runbook: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    research: str


@dataclass(frozen=True)
class AgentReviewResult:
    role: str
    summary: str
    findings: tuple[str, ...] = ()
    recommendation: Recommendation = "pass"


def review_input_from_packet(packet: Any) -> ReviewInput:
    """Extract the reviewable content from a ReadinessPacket (no reviews, no
    status — a reviewer never sees prior outcomes, so reviews stay independent)."""
    summary = getattr(packet, "plan_summary", None)
    boards = tuple(getattr(summary, "boards", []) or [])
    return ReviewInput(
        packet_id=packet.packet_id, revision=packet.revision, title=packet.title,
        plan_item_count=getattr(summary, "item_count", 0),
        boards=boards,
        runbook=tuple(s.text for s in getattr(packet, "runbook", []) or []),
        acceptance_criteria=tuple(
            c.text for c in getattr(packet, "acceptance_criteria", []) or []),
        research=getattr(packet, "research", "") or "")


def _status_for(recommendation: Recommendation) -> str:
    """Map an advisory recommendation to an AGENT review status — NEVER
    'approved' (an unknown recommendation degrades to the safest advisory)."""
    return _RECOMMENDATION_TO_STATUS.get(recommendation, "reviewed")


def structural_reviewer(role: str, review_input: ReviewInput) -> AgentReviewResult:
    """A deterministic, no-quota advisory reviewer: it reports structural
    readiness gaps a human should weigh before approving. NOT a substitute for a
    real agent review — it's the safe default so the orchestration is useful even
    when no paid/subscription reviewer is wired. Always advisory."""
    findings: list[str] = []
    if not review_input.runbook:
        findings.append("no runbook steps — the plan has no execution recipe")
    if not review_input.acceptance_criteria:
        findings.append("no acceptance criteria — 'done' is undefined")
    if not review_input.boards:
        findings.append("no board placement — work would land in the Universal Inbox")
    if not review_input.research.strip():
        findings.append("no research/context recorded")
    rec: Recommendation = "changes" if findings else "pass"
    summary = (f"{role}: {len(findings)} structural gap(s)" if findings
               else f"{role}: structurally complete (advisory)")
    return AgentReviewResult(role=role, summary=summary,
                             findings=tuple(findings), recommendation=rec)


def default_judge(results: Sequence[AgentReviewResult]) -> AgentReviewResult:
    """Synthesize independent reviews into one advisory verdict: if any reviewer
    asked for changes/raised a concern, the synthesis is 'changes'; else 'pass'.
    Never 'approve' — the judge is advisory too."""
    all_findings = [f"[{r.role}] {f}" for r in results for f in r.findings]
    any_changes = any(r.recommendation in ("changes", "concern") for r in results)
    rec: Recommendation = "changes" if any_changes else "pass"
    summary = ("judge synthesis: reviewers raised findings — human review needed"
               if any_changes
               else "judge synthesis: no blocking findings across reviewers "
                    "(advisory; a human must still approve)")
    return AgentReviewResult(role="judge", summary=summary,
                             findings=tuple(all_findings), recommendation=rec)


@dataclass
class OrchestrationReport:
    reviews: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    unlocked_commit: bool = False   # ALWAYS False — proves the wall held


def orchestrate_reviews(
    *,
    packet: Any,
    review_roles: Sequence[str],
    record: Callable[..., Any],
    review_fn: Callable[[str, ReviewInput], AgentReviewResult] = structural_reviewer,
    judge_fn: Callable[[Sequence[AgentReviewResult]], AgentReviewResult] = default_judge,
    include_judge: bool = True,
) -> OrchestrationReport:
    """Run one advisory review per role + an optional judge synthesis, recording
    each via `record(role=, status=, summary=, findings=, reviewer_kind='agent')`.
    NEVER records 'approved' (the sink enforces this too). Returns a report; its
    `unlocked_commit` is always False — orchestration alone cannot make a packet
    ready, a human approval is still required."""
    review_input = review_input_from_packet(packet)
    # only record into slots the packet actually declared — a role without a slot
    # is reviewed (returned in the report) but not force-created.
    slot_roles = {s.role for s in getattr(packet, "reviews", [])}
    report = OrchestrationReport()
    results: list[AgentReviewResult] = []
    for role in review_roles:
        result = review_fn(role, review_input)
        status = _status_for(result.recommendation)
        if result.role in slot_roles:
            record(role=result.role, status=status, summary=result.summary,
                   findings=list(result.findings), reviewer_kind="agent")
        results.append(result)
        report.reviews.append({
            "role": result.role, "status": status, "recorded": result.role in slot_roles,
            "summary": result.summary, "findings": list(result.findings)})
    if include_judge and results:
        synthesis = judge_fn(results)
        status = _status_for(synthesis.recommendation)
        if "judge" in slot_roles:      # record only if the packet declared a judge slot
            record(role="judge", status=status, summary=synthesis.summary,
                   findings=list(synthesis.findings), reviewer_kind="agent")
        report.synthesis = {
            "role": "judge", "status": status, "recorded": "judge" in slot_roles,
            "summary": synthesis.summary, "findings": list(synthesis.findings)}
    return report

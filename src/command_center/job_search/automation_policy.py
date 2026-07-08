from __future__ import annotations

from command_center.job_search.schemas import AutomationClass, AutomationResult, CanonicalJob, JobSearchConfig


def classify_automation(job: CanonicalJob, config: JobSearchConfig) -> AutomationResult:
    blockers: list[str] = []
    portal_lower = job.portal.lower()
    text = f"{job.description_text}\n{job.apply_url}\n{job.portal}".lower()

    for portal in config.automation.manual_portals:
        if portal.lower() in portal_lower or portal.lower() in job.apply_url.lower():
            blockers.append(f"manual portal: {portal}")

    for phrase in config.automation.manual_phrases:
        if phrase.lower() in text:
            blockers.append(f"manual phrase: {phrase}")

    if blockers:
        return AutomationResult(
            value=AutomationClass.MANUAL_REQUIRED,
            reason="Manual review required because blocker(s) were detected.",
            confidence=0.95,
            blockers=sorted(set(blockers)),
            mvp_submit_disabled=True,
        )

    if "apply" not in text:
        return AutomationResult(
            value=AutomationClass.PREPARE_ONLY,
            reason="No clear low-risk application workflow was detected.",
            confidence=0.75,
            blockers=["unclear application workflow"],
            mvp_submit_disabled=True,
        )

    return AutomationResult(
        value=AutomationClass.BOT_POSSIBLE,
        reason="No configured blocker detected; MVP still prepares only and does not submit.",
        confidence=0.88,
        blockers=[],
        mvp_submit_disabled=True,
    )


def can_submit(config: JobSearchConfig) -> bool:
    return bool(config.job_search.auto_submit_enabled) and not config.job_search.submit_without_geoff_selection


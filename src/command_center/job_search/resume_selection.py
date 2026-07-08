from __future__ import annotations

from command_center.job_search.achievement_bank import AchievementBank, validate_claim_ids
from command_center.job_search.scoring import choose_category, extract_keywords
from command_center.job_search.schemas import CanonicalJob, JobSearchConfig, ResumeSelection


def select_resume(job: CanonicalJob, bank: AchievementBank, config: JobSearchConfig) -> ResumeSelection:
    category = choose_category(job, config)
    variant = next(
        c.resume_variant for c in config.job_categories if c.id == category
    )
    keywords = extract_keywords(f"{job.role_title}\n{job.description_text}")
    selected: list[tuple[int, str, str]] = []
    unsupported: list[str] = []

    for achievement in bank.achievements:
        if not achievement.resume_safe or achievement.confidence == "low":
            continue
        score = 0
        if variant in achievement.role_families or category in achievement.categories:
            score += 5
        terms = [*(t.lower() for t in achievement.tools), *(d.lower() for d in achievement.domains)]
        score += sum(1 for kw in keywords if kw.lower() in terms)
        bullet = achievement.bullet_versions.get(variant) or next(
            (b for b in achievement.bullet_versions.values() if b), None
        )
        if score and bullet:
            selected.append((score, achievement.id, bullet))

    selected.sort(key=lambda row: (-row[0], row[1]))
    chosen = selected[:6]
    chosen_ids = [row[1] for row in chosen]
    rejected_claims = validate_claim_ids(bank, chosen_ids)

    supported_terms = {
        term.lower()
        for achievement in bank.achievements
        for term in achievement.tools + achievement.domains + achievement.role_families
    }
    for keyword in keywords:
        kw = keyword.lower()
        if not any(kw in term or term in kw for term in supported_terms):
            unsupported.append(keyword)

    has_wms = any(achievement_id.startswith("wms_") for achievement_id in chosen_ids)
    if has_wms and variant in {"founder_operator_product_ai", "sports_data_scientist", "lead_senior_data_scientist"}:
        wms_treatment = "main experience section"
    elif has_wms:
        wms_treatment = "recent founder/operator add-on"
    else:
        wms_treatment = "not selected for this posting"

    return ResumeSelection(
        resume_variant=variant,
        selected_achievement_ids=chosen_ids,
        selected_bullets=[row[2] for row in chosen],
        matched_keywords=keywords,
        unsupported_keywords=sorted(set(unsupported)),
        rejected_claims=rejected_claims,
        wms_treatment=wms_treatment,
    )


def render_selection_report(job: CanonicalJob, selection: ResumeSelection) -> str:
    lines = [
        f"# Resume Selection Report - {job.company} {job.role_title}",
        "",
        f"- Resume variant: `{selection.resume_variant}`",
        f"- WMS treatment: {selection.wms_treatment}",
        "",
        "## Selected Achievements",
        *[f"- `{achievement_id}`" for achievement_id in selection.selected_achievement_ids],
        "",
        "## Selected Bullets",
        *[f"- {bullet}" for bullet in selection.selected_bullets],
        "",
        "## Matched Keywords",
        ", ".join(selection.matched_keywords) or "None",
        "",
        "## Unsupported Keywords",
        ", ".join(selection.unsupported_keywords) or "None",
        "",
        "## Claims Rejected",
        *([f"- {claim}" for claim in selection.rejected_claims] or ["None"]),
        "",
        "## ATS/PDF Check",
        "Not implemented in the MVP. Markdown materials are claim-validated first.",
        "",
    ]
    return "\n".join(lines)

from __future__ import annotations

from command_center.job_search.achievement_bank import AchievementBank
from command_center.job_search.schemas import Achievement, CanonicalJob, ProjectType, ResumeSelection

PROJECT_TYPE_PROMPTS: dict[ProjectType, str] = {
    ProjectType.PYTHON_PROJECT: "Tell me about a project where you wrote significant Python code.",
    ProjectType.ENGINEERING_PROJECT: "Tell me about a data engineering or pipeline project.",
    ProjectType.ANALYST_PROJECT: (
        "Tell me about a project where you worked with stakeholders on reporting or analysis."
    ),
    ProjectType.LEADERSHIP_PROJECT: "Tell me about a time you led a team or project.",
    ProjectType.FOUNDER_PROJECT: "Tell me about a project you built and owned end to end.",
}

PROJECT_TYPE_ORDER = [
    ProjectType.PYTHON_PROJECT,
    ProjectType.ENGINEERING_PROJECT,
    ProjectType.ANALYST_PROJECT,
    ProjectType.LEADERSHIP_PROJECT,
    ProjectType.FOUNDER_PROJECT,
]


def _tool_overlap(achievement: Achievement, job_keywords: set[str]) -> int:
    terms = {t.lower() for t in achievement.tools + achievement.domains}
    return len(terms & job_keywords)


def select_stories(bank: AchievementBank, job_keywords: set[str]) -> dict[ProjectType, Achievement]:
    """Pick the single best-matching, claim-safe achievement per project_type for this job."""
    by_type: dict[ProjectType, list[Achievement]] = {}
    for achievement in bank.achievements:
        if not achievement.full_story or achievement.project_type is None or not achievement.resume_safe:
            continue
        by_type.setdefault(achievement.project_type, []).append(achievement)

    picks: dict[ProjectType, Achievement] = {}
    for project_type, achievements in by_type.items():
        achievements.sort(key=lambda a: (-_tool_overlap(a, job_keywords), a.id))
        picks[project_type] = achievements[0]
    return picks


def package_index(bank: AchievementBank) -> dict[str, list[str]]:
    """Map each tool/package to the achievement ids that demonstrate it, for 'tell me about a
    project using <package>' style questions."""
    index: dict[str, list[str]] = {}
    for achievement in bank.achievements:
        if not achievement.full_story:
            continue
        for tool in achievement.tools:
            index.setdefault(tool, []).append(achievement.id)
    return index


def render_answer_bank(job: CanonicalJob, bank: AchievementBank, selection: ResumeSelection) -> str:
    job_keywords = {kw.lower() for kw in selection.matched_keywords}
    picks = select_stories(bank, job_keywords)

    lines = [
        f"# Answer Bank - {job.company} {job.role_title}",
        "",
        "Ready-made STAR answers, picked for this job by project type. Use these as a starting",
        "point for application free-response questions and interview prep - tailor the opening",
        "line to the exact question asked, but the substance is already claim-checked against",
        "`achievement_bank.yml` and its evidence files.",
        "",
    ]

    any_story = False
    for project_type in PROJECT_TYPE_ORDER:
        achievement = picks.get(project_type)
        if not achievement:
            continue
        any_story = True
        lines.append(f'## If asked: "{PROJECT_TYPE_PROMPTS[project_type]}"')
        lines.append(f"**{achievement.company} - {achievement.title}** (`{achievement.id}`)")
        lines.append("")
        lines.append(achievement.full_story)
        lines.append("")
    if not any_story:
        lines.append("No full_story entries matched this job - add STAR stories to achievement_bank.yml.")
        lines.append("")

    index = package_index(bank)
    if index:
        lines.append("## Package / tool index")
        lines.append("If asked about a specific tool or package, here is which story to reach for:")
        lines.append("")
        for tool in sorted(index):
            ids = ", ".join(f"`{achievement_id}`" for achievement_id in index[tool])
            lines.append(f"- **{tool}**: {ids}")
        lines.append("")

    return "\n".join(lines)

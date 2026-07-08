from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from command_center.job_search.achievement_bank import AchievementBank
from command_center.job_search.automation_policy import classify_automation
from command_center.job_search.schemas import (
    AutomationClass,
    CanonicalJob,
    FitAction,
    FitResult,
    JobSearchConfig,
    RemoteType,
)

KNOWN_KEYWORDS = [
    "python",
    "sql",
    "snowflake",
    "dbt",
    "airflow",
    "azure data factory",
    "fastapi",
    "mlflow",
    "pytorch",
    "docker",
    "github actions",
    "tableau",
    "power bi",
    "looker",
    "bigquery",
    "redshift",
    "elt",
    "etl",
    "medallion architecture",
    "kpi",
    "dashboard",
    "experimentation",
    "a/b testing",
    "bayesian",
    "forecasting",
    "statistics",
    "graph",
    "neo4j",
    "nlp",
    "large language model",
    "llm",
    "transformer",
    "deep learning",
    "generative ai",
    "sports",
    "basketball",
    "nba",
    "betting",
    "fan analytics",
    "product analytics",
    "stakeholder",
    "leadership",
]


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "unknown"


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    data = yaml.safe_load(parts[1]) or {}
    return data, parts[2].strip()


def parse_salary(text: str) -> tuple[str | None, int | None, int | None, str | None]:
    money = re.findall(r"\$?\s*(\d{2,3})(?:,\d{3})?\s*(?:k|K|000)?", text)
    if not money:
        return None, None, None, None
    values = []
    for raw in money[:4]:
        n = int(raw)
        values.append(n * 1000 if n < 1000 else n)
    if not values:
        return None, None, None, None
    mn, mx = min(values), max(values)
    if mn < 40000 or mx > 400000:
        return None, None, None, None
    return f"${mn:,}-${mx:,}", mn, mx, "USD"


def normalize_job_from_text(text: str, *, source_path: Path | None = None) -> CanonicalJob:
    meta, body = _frontmatter(text)
    company = str(meta.get("company") or "Unknown Company")
    title = str(meta.get("role_title") or meta.get("title") or "Unknown Role")
    location = str(meta.get("location") or "Unknown")
    portal = str(meta.get("portal") or "unknown")
    apply_url = str(meta.get("apply_url") or "local://job-posting")
    source = str(meta.get("source") or "local_file")
    salary_text = meta.get("salary_text")
    salary_min = meta.get("salary_min")
    salary_max = meta.get("salary_max")
    currency = meta.get("currency")
    if salary_text is None:
        salary_text, salary_min, salary_max, currency = parse_salary(body)
    remote_raw = str(meta.get("remote_type") or "unknown").lower()
    remote = remote_raw if remote_raw in {rt.value for rt in RemoteType} else "unknown"
    key_material = f"{company}|{title}|{location}|{apply_url}|{body[:2000]}"
    job_key = str(meta.get("job_key") or hashlib.sha1(key_material.encode("utf-8")).hexdigest()[:12])
    return CanonicalJob(
        job_key=job_key,
        source=source,
        source_id=str(meta["source_id"]) if meta.get("source_id") else None,
        company=company,
        role_title=title,
        normalized_company=_norm(company),
        normalized_role=_norm(title),
        location=location,
        remote_type=RemoteType(remote),
        portal=portal,
        apply_url=apply_url,
        description_text=body,
        salary_text=str(salary_text) if salary_text else None,
        salary_min=int(salary_min) if salary_min is not None else None,
        salary_max=int(salary_max) if salary_max is not None else None,
        currency=str(currency) if currency else None,
        last_seen_at=datetime.now(timezone.utc),
    )


def extract_keywords(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in KNOWN_KEYWORDS if kw in lower]


def choose_category(job: CanonicalJob, config: JobSearchConfig) -> str:
    title = _norm(job.role_title)
    title_matches = [
        category.id for category in config.job_categories if _norm(category.id.replace("_", " ")) in title
    ]
    if len(title_matches) == 1:
        return title_matches[0]

    text = f"{job.role_title}\n{job.description_text}".lower()
    best_id = "analytics_data_scientist"
    best_hits = -1
    candidates = [c for c in config.job_categories if c.id in title_matches] or config.job_categories
    for category in candidates:
        hits = sum(1 for kw in category.keywords if kw.lower() in text)
        if hits > best_hits:
            best_id = category.id
            best_hits = hits
    return best_id


def classify_company_tier(job: CanonicalJob, config: JobSearchConfig) -> str:
    company_norm = _norm(job.company)
    text = f"{job.company}\n{job.description_text}".lower()
    targets = config.company_targets
    for name in targets.faang:
        if _norm(name) and _norm(name) in company_norm:
            return "faang"
    for name in targets.major_other:
        if _norm(name) and _norm(name) in company_norm:
            return "major_other"
    for name in targets.sports_tech_companies:
        if _norm(name) and _norm(name) in company_norm:
            return "sports_tech"
    for keyword in targets.sports_teams_keywords:
        if keyword.lower() in text:
            return "sports_team"
    return "none"


def _render_explanation(
    job: CanonicalJob,
    bank: AchievementBank,
    components: list[tuple[str, int]],
    evidence_ids: list[str],
    score: int,
    config: JobSearchConfig,
    company_tier: str,
    gaps: list[str],
) -> str:
    by_id = {a.id: a for a in bank.achievements}
    lines = [f"Fit score: {score}/100 for {job.company} - {job.role_title}.", "", "Score breakdown:"]
    for label, delta in components:
        sign = "+" if delta >= 0 else ""
        lines.append(f"  {sign}{delta}  {label}")
    if evidence_ids:
        lines.append("")
        lines.append("Your experience that drove this score:")
        for achievement_id in evidence_ids[:6]:
            achievement = by_id.get(achievement_id)
            if achievement:
                lines.append(f"  - {achievement.company} / {achievement.title} ({achievement.id})")
    if company_tier != "none":
        lines.append("")
        lines.append(
            f"Company tier match: {company_tier.replace('_', ' ')} - counted toward the score above."
        )
    if gaps:
        lines.append("")
        lines.append("Gaps found (not held against you, but worth knowing before you apply):")
        for gap in gaps:
            lines.append(f"  - {gap}")
    lines.append("")
    if score >= config.ranking.min_score_to_recommend_apply:
        lines.append(f"{score} clears the {config.ranking.min_score_to_recommend_apply} recommend-apply bar.")
    elif score >= config.ranking.min_score_to_show:
        lines.append(
            f"{score} clears the {config.ranking.min_score_to_show} show bar but is below the "
            f"{config.ranking.min_score_to_recommend_apply} recommend-apply bar - worth a look, not a lock."
        )
    else:
        lines.append(
            f"{score} is below the {config.ranking.min_score_to_show} show bar and will not surface "
            "automatically."
        )
    return "\n".join(lines)


def score_job(job: CanonicalJob, bank: AchievementBank, config: JobSearchConfig) -> FitResult:
    job_keywords = set(extract_keywords(f"{job.role_title}\n{job.description_text}"))
    evidence_ids: list[str] = []
    evidence_score = 0
    for achievement in bank.achievements:
        terms = {t.lower() for t in achievement.tools + achievement.domains + achievement.role_families}
        hits = len(job_keywords & terms)
        if hits:
            evidence_ids.append(achievement.id)
            evidence_score += min(8, hits * 2)
    evidence_score = min(30, evidence_score)

    components: list[tuple[str, int]] = [("Base score", 45), ("Achievement/keyword overlap", evidence_score)]
    score = 45 + evidence_score
    reasons: list[str] = []
    risks: list[str] = []
    gaps: list[str] = []

    if {"sql", "python"} & job_keywords:
        score += 5
        components.append(("Core Python/SQL match", 5))
        reasons.append("Core Python/SQL analytics skills match the achievement bank.")
    if {"snowflake", "dbt", "airflow"} & job_keywords:
        score += 8
        components.append(("Analytics engineering stack (Snowflake/dbt/Airflow)", 8))
        reasons.append("Analytics engineering stack overlaps with JPMorgan Snowflake/dbt/Airflow work.")
    if {"sports", "basketball", "nba", "betting", "fan analytics"} & job_keywords:
        score += config.ranking.sports_domain_bonus
        components.append(("Sports/basketball domain bonus", config.ranking.sports_domain_bonus))
        reasons.append("Sports/basketball domain aligns with Driveline, sports projects, and World Model Sports.")
    if {"founder", "startup", "product analytics"} & job_keywords:
        score += config.ranking.founder_operator_bonus_for_startups
        components.append(("Founder/operator bonus", config.ranking.founder_operator_bonus_for_startups))
        reasons.append("Founder/operator and product analytics language makes World Model Sports relevant.")

    company_tier = classify_company_tier(job, config)
    if company_tier != "none":
        score += config.ranking.target_company_bonus
        components.append(
            (f"Target company bonus ({company_tier.replace('_', ' ')})", config.ranking.target_company_bonus)
        )
        reasons.append(f"{job.company} is on your target-company watchlist ({company_tier.replace('_', ' ')}).")

    if job.salary_min is None:
        score -= config.ranking.missing_salary_penalty
        components.append(("No salary listed", -config.ranking.missing_salary_penalty))
        risks.append("Salary is not listed or could not be parsed.")
    if "spark" in job.description_text.lower() and "spark" not in job_keywords:
        gaps.append("Spark appears in the posting but is not a primary supported evidence keyword.")

    automation = classify_automation(job, config)
    if automation.value == AutomationClass.MANUAL_REQUIRED:
        score -= config.ranking.manual_required_penalty
        components.append(("Manual-required portal/questions", -config.ranking.manual_required_penalty))
        risks.append("Application likely needs Geoff because manual blockers were detected.")

    score = max(0, min(100, score))
    if score >= config.ranking.min_score_to_recommend_apply:
        action = (
            FitAction.APPLY_NOW
            if config.job_search.auto_submit_enabled
            and automation.value != AutomationClass.MANUAL_REQUIRED
            else FitAction.APPLY_MANUAL
        )
    elif score >= config.ranking.min_score_to_show:
        action = FitAction.NETWORK_FIRST if automation.value == AutomationClass.MANUAL_REQUIRED else FitAction.SAVE_FOR_LATER
    else:
        action = FitAction.SKIP
    if not reasons:
        reasons.append("Some overlap exists, but evidence strength is limited.")

    explanation = _render_explanation(job, bank, components, evidence_ids, score, config, company_tier, gaps)

    return FitResult(
        score=score,
        action=action,
        reasons=reasons,
        risks=risks,
        gaps=gaps,
        evidence_achievement_ids=evidence_ids[:8],
        company_tier=company_tier,
        explanation=explanation,
    )


def application_id_for(job: CanonicalJob, date: str) -> str:
    return f"{date}_{_slug(job.company)}_{_slug(job.role_title)}"

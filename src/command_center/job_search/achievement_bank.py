from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from command_center.job_search.schemas import Achievement, AchievementBank


DEFAULT_ACHIEVEMENTS: list[dict] = [
    {
        "id": "jpmc_ab_testing_framework",
        "title": "A/B testing framework",
        "company": "JP Morgan Chase",
        "role": "Analytics Engineer, Associate",
        "dates": "Jun 2023 - Aug 2025",
        "type": "experience",
        "categories": ["product_data_scientist", "analytics_data_scientist"],
        "role_families": ["product_data_scientist", "analytics_engineer", "lead_senior_data_scientist"],
        "tools": ["Statsmodels", "GitHub Actions", "Python"],
        "domains": ["experimentation", "marketing analytics", "finance"],
        "metrics": ["~12% campaign engagement improvement"],
        "bullet_versions": {
            "product_data_scientist": "Built and operationalized an A/B testing framework with automated validation and alerting, improving campaign engagement by ~12%.",
            "analytics_engineer": "Built a Statsmodels and GitHub Actions experimentation framework with validation checks and repeatable stakeholder reporting.",
            "lead_senior_data_scientist": "Led technical design and implementation of a company-wide experimentation framework, enabling repeatable campaign testing and measurable lift.",
        },
        "evidence_files": ["evidence/jpmorgan.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "analyst_project",
        "full_story": (
            "Situation: JPMorgan marketing and analytics stakeholders needed a repeatable way to "
            "measure whether campaign changes actually worked, rather than ad hoc before/after "
            "comparisons. Task: as Analytics Engineer, Associate, I owned building a reusable "
            "experimentation capability for the team. Action: I built an A/B testing framework in "
            "Python using Statsmodels for the statistical core, wired into GitHub Actions for "
            "automated validation and alerting so tests couldn't silently break or mis-report. "
            "Result: the framework became the team's standard way to measure campaign changes and "
            "was tied to a ~12% improvement in campaign engagement on the initiatives it evaluated."
        ),
    },
    {
        "id": "jpmc_fastapi_mlflow_models",
        "title": "Production model serving",
        "company": "JP Morgan Chase",
        "role": "Analytics Engineer, Associate",
        "dates": "Jun 2023 - Aug 2025",
        "type": "experience",
        "categories": ["applied_ml_data_scientist", "ml_engineer"],
        "role_families": ["applied_ml_data_scientist", "ml_engineer", "product_data_scientist"],
        "tools": ["PyTorch", "FastAPI", "MLflow", "Python"],
        "domains": ["MLOps", "model serving", "experimentation"],
        "metrics": ["~15% internal conversion metric uplift"],
        "bullet_versions": {
            "applied_ml_data_scientist": "Deployed PyTorch classification models through FastAPI with MLflow versioning; A/B tests showed ~15% uplift in internal conversion metrics.",
            "ml_engineer": "Integrated PyTorch classification models into production services using FastAPI and MLflow versioning, with validation and release discipline.",
            "product_data_scientist": "Shipped model-backed product analytics workflows through FastAPI and MLflow, then measured impact through controlled tests.",
        },
        "evidence_files": ["evidence/jpmorgan.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "engineering_project",
        "full_story": (
            "Situation: classification models JPMorgan teams built were sitting in notebooks with "
            "no reliable path to production, and no consistent way to version or roll back a model "
            "once it shipped. Task: I was responsible for turning research-stage PyTorch "
            "classification models into something the business could actually run and trust. "
            "Action: I deployed the models behind FastAPI services with MLflow handling versioning "
            "so every deployment had a traceable lineage and could be rolled back cleanly, and "
            "paired releases with A/B tests rather than shipping blind. Result: those tests showed "
            "roughly a 15% uplift in internal conversion metrics, and the FastAPI/MLflow pattern "
            "became the reusable path for shipping future models."
        ),
    },
    {
        "id": "jpmc_snowflake_dbt_elt",
        "title": "Self-serve analytics ELT",
        "company": "JP Morgan Chase",
        "role": "Analytics Engineer, Associate",
        "dates": "Jun 2023 - Aug 2025",
        "type": "experience",
        "categories": ["analytics_engineer", "analytics_data_scientist"],
        "role_families": ["analytics_engineer", "analytics_data_scientist", "product_data_scientist"],
        "tools": ["Snowflake", "dbt", "Azure Functions", "SQL"],
        "domains": ["data engineering", "self-serve analytics", "BI"],
        "metrics": ["halved time-to-insight"],
        "bullet_versions": {
            "analytics_engineer": "Implemented incremental ELT in Snowflake using dbt and Azure Functions, enabling self-serve analytics and halving time-to-insight.",
            "analytics_data_scientist": "Built reliable Snowflake/dbt data models and stakeholder-facing analytics layers that improved reporting speed and trust.",
            "product_data_scientist": "Partnered with stakeholders to turn product questions into reusable Snowflake/dbt analytics assets and faster decision loops.",
        },
        "evidence_files": ["evidence/jpmorgan.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "engineering_project",
        "full_story": (
            "Situation: analysts at JPMorgan were waiting on slow, ad hoc queries and one-off "
            "extracts to answer basic business questions, with no shared, trustworthy data layer "
            "underneath. Task: as the analytics engineer on the team, I owned building a self-serve "
            "analytics layer stakeholders could query directly. Action: I implemented incremental "
            "ELT in Snowflake using dbt for transformation logic and Azure Functions for "
            "orchestration glue, with tests and documentation so the models were trustworthy "
            "without me in the loop. Result: this halved time-to-insight for the teams depending on "
            "it and became the foundation self-serve analytics ran on."
        ),
    },
    {
        "id": "jpmc_airflow_adf_neo4j",
        "title": "Sub-hourly data pipelines",
        "company": "JP Morgan Chase",
        "role": "Analytics Engineer, Associate",
        "dates": "Jun 2023 - Aug 2025",
        "type": "experience",
        "categories": ["analytics_engineer", "ml_engineer"],
        "role_families": ["analytics_engineer", "ml_engineer", "applied_ml_data_scientist"],
        "tools": ["Airflow", "Azure Data Factory", "Neo4j", "Docker"],
        "domains": ["data pipelines", "graph data", "automation"],
        "metrics": ["sub-hourly refresh", "~80% manual intervention reduction"],
        "bullet_versions": {
            "analytics_engineer": "Streamlined ingestion and transformation with Airflow and Azure Data Factory, enabling sub-hourly refresh into Neo4j and reducing manual intervention by ~80%.",
            "ml_engineer": "Built modular Airflow/ADF data pipelines with graph-ready refresh patterns and operational checks for production analytics workflows.",
            "applied_ml_data_scientist": "Built reliable feature and graph-data refresh workflows that reduced staleness and manual intervention for downstream modeling.",
        },
        "evidence_files": ["evidence/jpmorgan.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "engineering_project",
        "full_story": (
            "Situation: downstream analytics and modeling work at JPMorgan was frequently blocked "
            "on stale data because ingestion and transformation ran on slow, manually-triggered "
            "schedules. Task: I needed pipelines fast enough to support near-real-time analytics "
            "and graph-based analysis. Action: I built modular pipelines in Airflow and Azure Data "
            "Factory with operational checks, feeding sub-hourly refreshes into Neo4j for "
            "graph-based data. Result: refresh cadence went from manual/ad hoc to sub-hourly, and "
            "manual intervention needed to keep the pipelines healthy dropped by roughly 80%."
        ),
    },
    {
        "id": "jpmc_reporting_team_lead",
        "title": "Reporting automation leadership",
        "company": "JP Morgan Chase",
        "role": "Senior Business Analyst",
        "dates": "Nov 2022 - Jun 2023",
        "type": "leadership",
        "categories": ["lead_senior_data_scientist", "analytics_data_scientist"],
        "role_families": ["lead_senior_data_scientist", "analytics_data_scientist"],
        "tools": ["SQL", "Alteryx", "SAS", "Tableau"],
        "domains": ["operations analytics", "team leadership", "executive reporting"],
        "metrics": ["~180 hours/month saved", "10-person team"],
        "bullet_versions": {
            "lead_senior_data_scientist": "Managed a 10-person analytics team delivering automated reporting and KPI systems, saving ~180 hours/month.",
            "analytics_data_scientist": "Led SQL, Alteryx, SAS, and Tableau automation that reduced manual reporting load and improved KPI visibility.",
        },
        "evidence_files": ["evidence/jpmorgan.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "analyst_project",
        "full_story": (
            "Situation: a 10-person team at JPMorgan was spending significant time each month "
            "manually assembling operational and executive reports, with inconsistent KPI "
            "definitions across outputs. Task: as Senior Business Analyst, I was responsible for "
            "both the reporting output and the people producing it. Action: I led the team's "
            "automation of reporting using SQL, Alteryx, SAS, and Tableau, standardizing KPI "
            "definitions and turning recurring manual builds into automated pipelines. Result: this "
            "saved roughly 180 hours per month of manual work and improved KPI visibility and "
            "consistency for the executives relying on the reports."
        ),
    },
    {
        "id": "driveline_biomechanics_pipeline",
        "title": "Biomechanics fatigue modeling",
        "company": "Driveline Baseball",
        "role": "Sports Science Intern",
        "dates": "Feb 2025 - Mar 2025",
        "type": "experience",
        "categories": ["sports_data_scientist", "applied_ml_data_scientist"],
        "role_families": ["sports_data_scientist", "applied_ml_data_scientist", "ml_engineer"],
        "tools": ["Python", "Docker", "time series", "EMG"],
        "domains": ["sports science", "biomechanics", "athlete monitoring"],
        "metrics": ["240Hz EMG synchronized with 100Hz biomechanics data"],
        "bullet_versions": {
            "sports_data_scientist": "Built time-series fatigue and exhaustion analysis using biomechanical signals for athlete monitoring workflows.",
            "applied_ml_data_scientist": "Engineered predictive modeling workflows from high-frequency EMG and biomechanics data, including synchronization and validation logic.",
            "ml_engineer": "Built a streaming synchronization pipeline for high-frequency EMG and biomechanics signals with reproducible Docker packaging.",
        },
        "evidence_files": ["evidence/driveline.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "python_project",
        "full_story": (
            "Situation: Driveline Baseball needed a way to detect athlete fatigue and exhaustion "
            "patterns from raw sensor data, where EMG and biomechanics streams ran at different "
            "sampling rates and had to be reconciled before any modeling was possible. Task: as a "
            "Sports Science Intern, I built the analysis workflow that turned raw signals into "
            "fatigue/exhaustion insights. Action: in Python, I synchronized 240Hz EMG data with "
            "100Hz biomechanics data and built time-series fatigue analysis on top of the aligned "
            "signals, packaging the pipeline in Docker for reproducibility. Result: the "
            "synchronized, containerized pipeline gave the sports science team a reproducible way "
            "to run fatigue/exhaustion analysis on athlete monitoring data."
        ),
    },
    {
        "id": "marlins_bayesian_hackathon",
        "title": "Marlins Bayesian modeling hackathon",
        "company": "Project",
        "role": "Sports Analytics Project",
        "dates": "2025",
        "type": "project",
        "categories": ["sports_data_scientist", "applied_ml_data_scientist"],
        "role_families": ["sports_data_scientist", "applied_ml_data_scientist", "lead_senior_data_scientist"],
        "tools": ["PyMC", "JAX", "Docker", "Bayesian modeling"],
        "domains": ["baseball analytics", "probabilistic modeling", "sports"],
        "metrics": ["RMSE 6.01 mph", "R2 about 0.956", "27% better than linear baseline"],
        "bullet_versions": {
            "sports_data_scientist": "Developed a JAX-accelerated hierarchical PyMC model projecting latent exit velocity, outperforming a linear baseline by 27%.",
            "applied_ml_data_scientist": "Built a reproducible Bayesian modeling workflow with JAX/PyMC, Docker packaging, and validation metrics.",
            "lead_senior_data_scientist": "Led team modeling work for a sports analytics hackathon, mentoring on probabilistic programming and reproducible workflows.",
        },
        "evidence_files": ["evidence/sports_projects.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "python_project",
        "full_story": (
            "Situation: a sports analytics hackathon problem asked teams to project a "
            "hard-to-observe quantity, latent exit velocity, from imperfect batted-ball data, where "
            "a naive linear model was the baseline everyone had to beat. Task: I set out to build a "
            "probabilistic model that could beat that baseline while quantifying its own "
            "uncertainty. Action: I built a JAX-accelerated hierarchical Bayesian model in PyMC, "
            "packaged in Docker for reproducibility, and validated it against held-out data. "
            "Result: the model hit an RMSE of 6.01 mph and R-squared of about 0.956, beating the "
            "linear baseline by 27%."
        ),
    },
    {
        "id": "nba_player_value_platform",
        "title": "NBA player value forecasting",
        "company": "Project",
        "role": "Sports Analytics Project",
        "dates": "2025 - Present",
        "type": "project",
        "categories": ["sports_data_scientist", "applied_ml_data_scientist", "founder_operator_product_ai"],
        "role_families": ["sports_data_scientist", "applied_ml_data_scientist", "founder_operator_product_ai"],
        "tools": ["Python", "SQL", "Bayesian modeling", "clustering"],
        "domains": ["NBA", "basketball", "player valuation", "salary modeling", "roster construction", "forecasting"],
        "metrics": ["28+ leagues represented in source pipeline"],
        "bullet_versions": {
            "sports_data_scientist": "Built an NBA player value forecasting system spanning multi-league data, Bayesian models, archetype clustering, age curves, and salary optimization.",
            "applied_ml_data_scientist": "Developed player-value forecasting workflows combining multi-league features, uncertainty-aware modeling, and validation-oriented deployment planning.",
            "founder_operator_product_ai": "Translated NBA player value research into product-oriented decision workflows for roster construction and contract efficiency.",
        },
        "evidence_files": ["evidence/sports_projects.md", "evidence/world_model_sports.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "python_project",
        "full_story": (
            "Situation: evaluating NBA player value and forecasting future value is hard because it "
            "spans very different data regimes: multiple leagues, non-linear age curves, and "
            "archetype differences between players. Task: I set out to build a forecasting system "
            "that could handle player value and roster-construction questions across that variety "
            "rather than a single-league model. Action: in Python and SQL, I built Bayesian "
            "forecasting models combined with archetype clustering and explicit age-curve "
            "modeling, drawing on a pipeline spanning 28+ leagues of source data, aimed at "
            "salary/contract-efficiency and roster-construction questions. Result: the system "
            "produces player value forecasts and roster-construction scenarios that now feed "
            "directly into World Model Sports' product work."
        ),
    },
    {
        "id": "wms_founder_platform",
        "title": "World Model Sports platform",
        "company": "World Model Sports LLC",
        "role": "Founder & CEO / Principal Data Scientist",
        "dates": "2026 - Present",
        "type": "experience",
        "categories": ["sports_data_scientist", "founder_operator_product_ai", "lead_senior_data_scientist"],
        "role_families": ["sports_data_scientist", "founder_operator_product_ai", "analytics_engineer", "ml_engineer"],
        "tools": ["Python", "SQL", "FastAPI", "Docker", "Bayesian modeling"],
        "domains": ["NBA", "basketball", "sports analytics", "AI product", "player valuation", "contract efficiency", "forecasting"],
        "metrics": [],
        "bullet_versions": {
            "founder_operator_product_ai": "Founded World Model Sports LLC and led product, data, engineering, and go-to-market planning for Hoops World Model, a basketball intelligence platform for player valuation, roster strategy, contract efficiency, and explainable NBA analytics.",
            "sports_data_scientist": "Built Hoops World Model, a basketball intelligence platform for NBA player valuation, contract efficiency, roster strategy, forecasting, and explainable decision-support.",
            "analytics_engineer": "Architected end-to-end analytics workflows across data ingestion, validation checks, player valuation, contract efficiency, and frontend decision-support views.",
            "ml_engineer": "Built production-oriented NBA analytics workflows using Python, SQL, FastAPI, Docker, validation checks, and frontend analytics surfaces.",
        },
        "evidence_files": ["evidence/world_model_sports.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "founder_project",
        "full_story": (
            "Situation: I saw a gap in basketball analytics - most public tools either explain what "
            "already happened or ignore contract/roster economics entirely, and almost none combine "
            "player valuation, forecasting, and contract efficiency into one explainable product. "
            "Task: I set out to build that product myself, end to end, rather than as a research "
            "exercise. Action: I founded World Model Sports LLC and, as Founder & CEO / Principal "
            "Data Scientist, led product, data, engineering, and go-to-market planning for Hoops "
            "World Model - a basketball intelligence platform spanning player valuation, roster "
            "strategy, contract efficiency, and explainable NBA analytics, built with Python, SQL, "
            "FastAPI, and Docker. Result: the platform is live and under active development, with a "
            "defined product strategy covering fan, bettor, analyst/journalist, coach, and "
            "team-builder use cases and a roadmap toward subscriptions, consulting/pilots, and "
            "API/licensing."
        ),
    },
    {
        "id": "wms_graph_roster_analysis",
        "title": "World Model Sports graph and roster analysis",
        "company": "World Model Sports LLC",
        "role": "Founder & CEO / Principal Data Scientist",
        "dates": "2026 - Present",
        "type": "experience",
        "categories": ["sports_data_scientist", "founder_operator_product_ai"],
        "role_families": ["sports_data_scientist", "founder_operator_product_ai", "applied_ml_data_scientist"],
        "tools": ["graph analysis", "Bayesian modeling", "Python", "SQL"],
        "domains": ["lineup strategy", "roster construction", "NBA", "basketball", "player fit", "forecasting"],
        "metrics": [],
        "bullet_versions": {
            "sports_data_scientist": "Designed graph and network analysis workflows to visualize player, lineup, team, and roster relationships for fit, role interaction, and strategic basketball decisions.",
            "founder_operator_product_ai": "Developed founder-led product strategy for fan, bettor, analyst, coach, and team-builder use cases, translating advanced basketball models into practical decision workflows.",
            "applied_ml_data_scientist": "Developed player value and roster-construction research across archetype clustering, age curves, Bayesian modeling, surplus value, and future team-building scenarios.",
        },
        "evidence_files": ["evidence/world_model_sports.md"],
        "confidence": "high",
        "resume_safe": True,
        "project_type": "founder_project",
        "full_story": (
            "Situation: player valuation numbers alone don't explain lineup fit, chemistry, or how "
            "a roster move actually changes a team's on-court structure. Task: as part of World "
            "Model Sports, I wanted to give roster and lineup decisions the same explainability the "
            "valuation models already had. Action: I designed graph and network analysis workflows, "
            "built with Bayesian modeling, Python, and SQL, to visualize player, lineup, team, and "
            "roster relationships. Result: these workflows now let the platform explain fit and "
            "role interaction for strategic basketball decisions, not just rank players in "
            "isolation."
        ),
    },
]


def default_bank() -> AchievementBank:
    return AchievementBank(achievements=[Achievement.model_validate(a) for a in DEFAULT_ACHIEVEMENTS])


def load_bank(path: Path) -> AchievementBank:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AchievementBank.model_validate(data)


def save_bank(path: Path, bank: AchievementBank) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(bank.model_dump(mode="json"), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def ensure_bank(path: Path) -> AchievementBank:
    if not path.exists():
        bank = default_bank()
        save_bank(path, bank)
        return bank
    existing = load_bank(path)
    by_id = {a.id: a for a in existing.achievements}
    changed = False
    for achievement in default_bank().achievements:
        if achievement.id not in by_id:
            existing.achievements.append(achievement)
            changed = True
            continue
        current = by_id[achievement.id]
        for field in ("categories", "role_families", "tools", "domains", "metrics", "evidence_files"):
            values = list(getattr(current, field))
            for value in getattr(achievement, field):
                if value not in values:
                    values.append(value)
                    changed = True
            setattr(current, field, values)
        bullet_versions = dict(current.bullet_versions)
        for key, value in achievement.bullet_versions.items():
            if key not in bullet_versions and value:
                bullet_versions[key] = value
                changed = True
        current.bullet_versions = bullet_versions
        if current.project_type is None and achievement.project_type is not None:
            current.project_type = achievement.project_type
            changed = True
        if current.full_story is None and achievement.full_story is not None:
            current.full_story = achievement.full_story
            changed = True
    if changed:
        save_bank(path, existing)
    return existing


def achievement_map(bank: AchievementBank) -> dict[str, Achievement]:
    return {a.id: a for a in bank.achievements}


def validate_claim_ids(bank: AchievementBank, ids: Iterable[str]) -> list[str]:
    known = achievement_map(bank)
    errors: list[str] = []
    for achievement_id in ids:
        achievement = known.get(achievement_id)
        if achievement is None:
            errors.append(f"unknown achievement id: {achievement_id}")
            continue
        if not achievement.resume_safe:
            errors.append(f"achievement is not resume safe: {achievement_id}")
        if achievement.confidence == "low":
            errors.append(f"low-confidence achievement excluded by default: {achievement_id}")
        if not achievement.evidence_files:
            errors.append(f"achievement has no evidence file: {achievement_id}")
    return errors

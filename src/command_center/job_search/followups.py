from __future__ import annotations

import gzip
import json
from pathlib import Path

import yaml

from command_center.job_search.schemas import ApplicationRecord


def _read_job_description(app_dir: Path) -> str:
    path = app_dir / "job_description.md.gz"
    if not path.exists():
        return ""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


def _communications(app_dir: Path) -> list[dict]:
    path = app_dir / "communications.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def generate_followup(app_dir: Path) -> str:
    record = ApplicationRecord.model_validate(
        yaml.safe_load((app_dir / "application.yml").read_text(encoding="utf-8"))
    )
    description = _read_job_description(app_dir)
    communications = _communications(app_dir)
    proof_points = record.bullet_ids_used[:6]
    salary = record.salary
    salary_line = (
        f"Listed range: ${salary.min:,}-${salary.max:,} {salary.currency or ''}".strip()
        if salary.listed and salary.min and salary.max
        else "Salary not listed or not parsed. Ask/confirm during recruiter process."
    )
    comm_lines = [
        f"- {row.get('ts', 'unknown')}: {row.get('summary', '')} Action: {row.get('action_needed', '')}"
        for row in communications
    ]
    text = f"""# Follow-Up Pack - {record.company} {record.role_title}

## Why Geoff Applied
This role scored {record.fit.score}/100 for `{record.category}` and matched the `{record.resume_variant}` resume variant.
Key reasons: {'; '.join(record.fit.reasons)}

## Best Proof Points
{chr(10).join(f'- `{item}`' for item in proof_points) or '- No proof points selected yet.'}

## 60-Second Pitch
I am a data scientist and analytics engineer with production experience across experimentation, Snowflake/dbt/Airflow data systems, FastAPI/MLflow model deployment, and sports analytics. Recently I founded World Model Sports, where I am building Hoops World Model, a basketball intelligence platform for player valuation, roster strategy, contract efficiency, and explainable NBA analytics.

## Salary Notes
{salary_line}

## Recruiter Reply Draft
Thanks for reaching out. The role stood out because it connects directly to my experience in analytics engineering, applied ML, experimentation, and sports/product analytics. I would be glad to compare the role scope with my JPMorgan production analytics work and the World Model Sports platform I am building. I can share availability once I review the proposed interview windows.

## Hiring Manager Note Draft
The strongest overlap is my ability to move from ambiguous business or sports questions into reliable data products: production pipelines, validated modeling workflows, stakeholder-facing metrics, and decision-support surfaces.

## Interview Prep
- Be ready to discuss JPMorgan experimentation and analytics engineering.
- Be ready to discuss FastAPI/MLflow production model serving.
- Be ready to discuss World Model Sports as founder-led recent proof of work.
- Be ready to explain any unsupported keyword gaps honestly.

## Prior Communications
{chr(10).join(comm_lines) if comm_lines else '- No communications logged yet.'}

## Next Action
{record.followup.get('next_action', 'Review status and follow up when appropriate.')}

## Job Description Snapshot
{description[:1200].strip()}
"""
    (app_dir / "followups.md").write_text(text, encoding="utf-8")
    return text


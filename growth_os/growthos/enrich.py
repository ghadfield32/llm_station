"""Structured, provenance-labelled analysis for curated research cards.

Deliberately scoped so context never becomes noise:
- runs ONLY on items that survived scoring + dedupe this cycle (the hourly
  delta is a handful of items after day one — efficient by construction)
- one bounded JSON analysis per item, grounded in the registered projects
- local model only (the brief's model via Ollama); if Ollama is down the
  cycle proceeds unenriched with a LOUD warning — curation never blocks on
  an LLM, and nothing fabricates an annotation

Module tree / stages:
  stage 1  project_context()   config/projects.yaml names + the interest
                               profile -> grounding for the prompt
  stage 2  suggest()           per item: title+summary -> validated Ollama JSON
                               -> usefulness, tradeoffs, and implementation notes

Wired in curate.py between rank_and_trim and the write step.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, ValidationError,
)

from .config import ResearchProjectCfg, load_research_projects
from .models import CuratedItem, RESEARCH_ANALYSIS_SCHEMA_VERSION

log = logging.getLogger("growthos.enrich")
ANALYSIS_SCHEMA_VERSION = RESEARCH_ANALYSIS_SCHEMA_VERSION
MAX_ANALYSIS_ATTEMPTS = 2
NO_DIRECT_CAPABILITY = "no direct match"
AnalysisListItem = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)
]


class ResearchAnalysis(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, strict=True)

    useful_for_us: str = Field(min_length=1, max_length=1200)
    pros: list[AnalysisListItem] = Field(min_length=1, max_length=8)
    cons: list[AnalysisListItem] = Field(min_length=1, max_length=8)
    key_details: list[AnalysisListItem] = Field(min_length=1, max_length=12)
    implementation_notes: list[AnalysisListItem] = Field(
        min_length=1, max_length=12)
    work_areas: list[AnalysisListItem] = Field(min_length=1, max_length=8)
    use_cases: list[AnalysisListItem] = Field(min_length=1, max_length=8)
    research_priority: Literal["high", "medium", "low", "watch"]
    relevance_score: int = Field(ge=0, le=100)
    potential_impact_score: int = Field(ge=0, le=100)
    implementation_readiness_score: int = Field(ge=0, le=100)
    evidence_confidence_score: int = Field(ge=0, le=100)
    estimated_effort: Literal["small", "medium", "large", "research_only"]
    project_fits: list["ProjectFit"] = Field(min_length=1, max_length=50)


class ProjectFit(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, strict=True)

    project: str = Field(min_length=1, max_length=120)
    fit_score: int = Field(ge=0, le=100)
    item_evidence: str = Field(min_length=1, max_length=600)
    project_capability: str = Field(min_length=1, max_length=240)
    why: str = Field(min_length=1, max_length=600)
    suggested_application: str = Field(min_length=1, max_length=600)


ResearchAnalysis.model_rebuild()


def _input_sha256(
    item: CuratedItem, *, model: str, prompt: str | None,
) -> str:
    request = (
        {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        if prompt is not None else None
    )
    value = json.dumps(
        {
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "request": request,
            "not_sent_source": (
                None if request is not None else {
                    "kind": item.kind, "title": item.title,
                    "summary": item.summary, "topics": item.topics,
                    "url": item.url,
                }
            ),
        },
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_text(raw: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _mark_status(
    item: CuratedItem, status: str, *, model: str, now_iso: str,
    prompt: str | None, error: str = "",
) -> None:
    item.extra.update({
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": status,
        "analysis_model": model,
        "analysis_generated_at": now_iso,
        "analysis_input_sha256": _input_sha256(
            item, model=model, prompt=prompt),
        "analysis_origin": "local_model",
    })
    if error:
        item.extra["analysis_error_code"] = error
    else:
        item.extra.pop("analysis_error_code", None)


def project_context() -> tuple[str, list[ResearchProjectCfg]]:
    projects = load_research_projects()
    rows = []
    for project in projects:
        capabilities = project.research_capabilities
        capability_text = (
            "; ".join(capabilities)
            if capabilities else
            "NO DECLARED RESEARCH CAPABILITIES (use no direct match)"
        )
        rows.append(
            f"- {project.name} ({project.location_ref}; {project.remote_url})\n"
            f"  allowed capabilities: {capability_text}")
    return (
        "Registered project folders (authoritative; score every one exactly once "
        "and copy one allowed capability exactly):\n"
        + "\n".join(rows),
        projects,
    )


def _validate_project_coverage(
    analysis: ResearchAnalysis,
    expected_projects: list[ResearchProjectCfg] | list[str],
) -> None:
    configured = (
        {}
        if all(isinstance(project, ResearchProjectCfg) for project in expected_projects)
        else {
            project.name: project for project in load_research_projects()
        }
    )
    project_specs = [
        project
        if isinstance(project, ResearchProjectCfg)
        else configured.get(project) or ResearchProjectCfg(
            name=project,
            location_ref="capabilities_not_registered",
            remote_url="capabilities_not_registered",
        )
        for project in expected_projects
    ]
    expected_names = [project.name for project in project_specs]
    actual = [fit.project for fit in analysis.project_fits]
    if len(actual) != len(set(actual)):
        raise ValueError("project_fits contains duplicate project names")
    if set(actual) != set(expected_names) or len(actual) != len(expected_names):
        raise ValueError(
            "project_fits must cover exactly these registered projects: "
            + ", ".join(expected_names)
        )
    by_name = {project.name: project for project in project_specs}
    for fit in analysis.project_fits:
        allowed = set(by_name[fit.project].research_capabilities)
        allowed.add(NO_DIRECT_CAPABILITY)
        if fit.project_capability not in allowed:
            raise ValueError(
                f"project_fits[{fit.project}] project_capability must copy one "
                f"declared capability exactly or use {NO_DIRECT_CAPABILITY!r}")
        if fit.project_capability == NO_DIRECT_CAPABILITY and fit.fit_score > 24:
            raise ValueError(
                f"project_fits[{fit.project}] no-direct-match score must be 0-24")


def _derived_project_fields(analysis: ResearchAnalysis) -> dict[str, object]:
    ordered = sorted(
        analysis.project_fits, key=lambda fit: (-fit.fit_score, fit.project))
    best = ordered[0]
    return {
        "applicable_projects": [
            fit.project for fit in ordered if fit.fit_score >= 35
        ],
        "best_project": best.project,
        "best_project_fit_score": best.fit_score,
        "project_fit_summary": "\n".join(
            f"- {fit.project} · {fit.fit_score}/100 — "
            f"Item evidence: {fit.item_evidence} "
            f"Project capability: {fit.project_capability}. "
            f"Why: {fit.why} "
            f"Suggested application: {fit.suggested_application}"
            for fit in ordered
        ),
    }


def _derived_research_priority(analysis: ResearchAnalysis) -> str:
    """Calibrate priority from the scored evidence instead of model wording."""
    relevance = analysis.relevance_score
    upside = max(
        analysis.potential_impact_score,
        analysis.implementation_readiness_score,
    )
    confidence = analysis.evidence_confidence_score
    if relevance >= 75 and upside >= 70 and confidence >= 60:
        return "high"
    if relevance >= 55 and upside >= 50 and confidence >= 50:
        return "medium"
    if relevance >= 35 or upside >= 50:
        return "low"
    return "watch"


def validate_persisted_analysis(
    value: dict[str, object],
    expected_projects: list[ResearchProjectCfg] | list[str],
) -> bool:
    """Apply one strict completeness contract to stored KPI/provenance rows."""
    if (
        value.get("analysis_schema_version") != ANALYSIS_SCHEMA_VERSION
        or value.get("analysis_status") != "complete"
        or value.get("analysis_origin") != "local_model"
        or not str(value.get("analysis_model") or "").strip()
        or str(value.get("analysis_error_code") or "").strip()
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(value.get("analysis_input_sha256") or ""),
        )
    ):
        return False
    try:
        generated_at = datetime.fromisoformat(
            str(value.get("analysis_generated_at") or "").replace("Z", "+00:00"))
        if generated_at.tzinfo is None:
            return False
        analysis = ResearchAnalysis.model_validate({
            field: value.get(field)
            for field in ResearchAnalysis.model_fields
        })
        _validate_project_coverage(analysis, expected_projects)
    except (TypeError, ValueError, ValidationError):
        return False
    if analysis.relevance_score != max(
        fit.fit_score for fit in analysis.project_fits
    ):
        return False
    if value.get("research_priority") != _derived_research_priority(analysis):
        return False
    derived = _derived_project_fields(analysis)
    return all(value.get(field) == expected for field, expected in derived.items())


def suggest(
    items: list[CuratedItem], base_url: str, model: str, *, now_iso: str | None = None,
) -> int:
    """Annotate items in place; returns the number of completed analyses.

    Generated judgments are explicitly labelled `local_model`. Link fields are
    never model-produced; source adapters populate those separately.
    """
    if not items:
        return 0
    now_iso = now_iso or datetime.now(UTC).isoformat()
    if not base_url:
        log.warning("enrich skipped: OLLAMA_BASE_URL is empty")
        for item in items:
            _mark_status(
                item, "unavailable", model=model, now_iso=now_iso, prompt=None,
                error="ollama_not_configured")
        return 0
    ctx, expected_projects = project_context()
    done = 0
    with httpx.Client(timeout=180) as http:
        for it in items:
            prompt = (
                f"{ctx}\n\nItem ({it.kind}): {it.title}\n"
                f"Summary: {it.summary[:1800]}\n"
                f"Topics: {', '.join(it.topics)}\n\n"
                "Return ONLY one JSON object with exactly these keys: "
                "useful_for_us (string), pros (string array), cons (string array), "
                "key_details (string array), implementation_notes (string array), "
                "work_areas (string array), use_cases (string array), "
                "research_priority (high|medium|low|watch), relevance_score "
                "(integer 0-100), potential_impact_score (integer 0-100), "
                "implementation_readiness_score (integer 0-100), "
                "evidence_confidence_score (integer 0-100), estimated_effort "
                "(small|medium|large|research_only), and project_fits (array of "
                "objects with project, fit_score 0-100, item_evidence, "
                "project_capability, why, and suggested_application). "
                "Ground every claim in the supplied item and project context. "
                "Score every registered project exactly once using its exact name. "
                "For item_evidence, cite a concise fact from the supplied title, "
                "summary, or topics; never cite outside knowledge. For "
                "project_capability, copy exactly one allowed capability listed for "
                "that project, or use 'no direct match'. Do not claim a project has "
                "a capability that is not listed. Score fit independently for each "
                "folder: 90-100 requires a near drop-in exact technology and task "
                "match; 75-89 requires a direct component with a concrete integration "
                "seam; 50-74 is a strong adjacent capability; 25-49 is only a "
                "transferable concept or exploratory experiment; 0-24 means no "
                "direct match. Generic storage, data analysis, model training, "
                "automation, or knowledge-board enrichment alone never establishes "
                "a score above 49. If project_capability is 'no direct match', fit "
                "must be 0-24. Read capability names literally: LLM/agent model "
                "evaluation requires source evidence about LLMs, agents, prompts, "
                "or tool use, not an arbitrary statistical model; NBA/sports data "
                "pipelines require source evidence about basketball, sports, odds, "
                "players, or games, not an arbitrary database; research retrieval "
                "and knowledge boards require retrieval, indexing, search, vector, "
                "or knowledge-system evidence, not merely content that could be "
                "stored; and Airflow DAG capability requires workflow, DAG, or "
                "Airflow evidence. A domain-neutral Bayesian or forecasting method "
                "can directly support the declared Bayesian/forecasting capability "
                "when the supplied source explicitly establishes that method. "
                "Relevance measures alignment with our work and will be normalized "
                "to the highest grounded folder fit; potential impact is "
                "upside if successful; readiness measures how directly the supplied "
                "evidence supports implementation; evidence confidence measures the "
                "strength and completeness of that evidence. Use low scores when the "
                "summary does not establish a claim. Effort means prototype effort: "
                "small <=2 days, medium <=2 weeks, large >2 weeks, research_only when "
                "there is no grounded implementation seam. "
                "Priority is calibrated from those scores: high requires relevance "
                ">=75, impact or readiness >=70, and confidence >=60; medium requires "
                "relevance >=55, impact or readiness >=50, and confidence >=50; low "
                "means weaker alignment or upside; watch means neither is established. "
                "Implementation notes should identify an experiment or integration "
                "seam, prerequisites, and validation needs. Do not invent links, "
                "benchmarks, results, dependencies, or repository contents.")
            sent_prompt = prompt
            analysis = None
            for attempt in range(MAX_ANALYSIS_ATTEMPTS):
                try:
                    r = http.post(
                        f"{base_url.rstrip('/')}/api/chat",
                        json={
                            "model": model,
                            "stream": False,
                            "messages": [{"role": "user", "content": sent_prompt}],
                        },
                    )
                    r.raise_for_status()
                    raw = r.json()["message"]["content"]
                    analysis = ResearchAnalysis.model_validate_json(
                        _analysis_text(raw))
                    _validate_project_coverage(analysis, expected_projects)
                    break
                except httpx.HTTPError as exc:
                    log.warning("enrich stopped at %r: %s (remaining items "
                                "unenriched this cycle)", it.title[:40], exc)
                    _mark_status(
                        it, "failed", model=model, now_iso=now_iso,
                        prompt=sent_prompt, error="ollama_request_failed")
                    return done
                except (
                    KeyError, TypeError, ValueError, ValidationError,
                    json.JSONDecodeError,
                ) as exc:
                    if attempt + 1 < MAX_ANALYSIS_ATTEMPTS:
                        log.warning(
                            "enrich invalid response for %r; corrective retry: %s",
                            it.title[:40], exc,
                        )
                        sent_prompt = (
                            f"{prompt}\n\nYour previous response failed the required "
                            f"schema validation: {exc}. Return a corrected JSON object. "
                            "Every string must be non-empty; every required array must "
                            "contain grounded items; scores must be integers from 0 to "
                            "100; and project_fits must cover each registered project "
                            "exactly once, cite item evidence, and copy an allowed "
                            "project capability exactly (or use 'no direct match' "
                            "with a score no higher than 24)."
                        )
                        continue
                    log.warning(
                        "enrich invalid response for %r after corrective retry: %s",
                        it.title[:40], exc,
                    )
                    _mark_status(
                        it, "failed", model=model, now_iso=now_iso,
                        prompt=sent_prompt, error="invalid_analysis_response")
            if analysis is None:
                continue
            payload = analysis.model_dump()
            payload["relevance_score"] = max(
                fit.fit_score for fit in analysis.project_fits)
            normalized = ResearchAnalysis.model_validate(payload)
            payload["research_priority"] = _derived_research_priority(normalized)
            it.extra.update(payload)
            it.extra.update(_derived_project_fields(normalized))
            it.extra["suggested"] = analysis.useful_for_us
            _mark_status(
                it, "complete", model=model, now_iso=now_iso,
                prompt=sent_prompt)
            done += 1
    return done

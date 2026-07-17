"""Load + validate configuration. Secrets come from env; feeds from YAML.
Fails fast (Pydantic) so a bad config never silently degrades a run."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from command_center.schemas.contracts import AutonomyConfig, DomainSurfacesConfig


DEFAULT_DOMAIN_SURFACES = (
    Path(__file__).resolve().parents[2] / "configs" / "domain_surfaces.yaml"
)
DEFAULT_PROJECTS = Path(__file__).resolve().parents[1] / "config" / "projects.yaml"
DEFAULT_AUTONOMY = Path(__file__).resolve().parents[2] / "configs" / "autonomy.yaml"


class Settings(BaseSettings):
    """Runtime secrets / switches, from .env or the environment."""
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")
    growthos_board_store: str = "../generated/boards"
    growthos_kanban_event_log: str = "../generated/kanban-events.jsonl"
    github_token: str = ""
    growthos_dry_run: bool = True
    growthos_state_dir: str = "./_state"
    growthos_log_level: str = "INFO"
    # Ollama (optional): enables embedding-based scoring + the LLM brief.
    # Empty -> keyword scoring and the plain link-list brief.
    ollama_base_url: str = ""
    growthos_brief_model: str = "qwen3:8b"
    growthos_assistant_model: str = "qwen3:8b"
    # command-center bridge visibility (morning brief worklog)
    ledger_base_url: str = "http://localhost:8091"
    growthos_kanban_imported: str = "../../generated/kanban-imported.json"
    growthos_standards_path: str = "../../configs/standards.yaml"
    growthos_domain_surfaces: str = str(DEFAULT_DOMAIN_SURFACES)


class InterestProfile(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)


class ArxivCfg(BaseModel):
    enabled: bool = True
    top_n: int = 12
    lookback_days: int = 3
    analysis_batch_size: int = 25
    categories: list[str] = Field(default_factory=list)
    review_topics: list[str] = Field(default_factory=list)


class GithubCfg(BaseModel):
    enabled: bool = True
    top_n: int = 10
    lookback_days: int = 7
    min_stars: int = 25
    analysis_batch_size: int = 25
    review_topics: list[str] = Field(default_factory=list)


class SignalsCfg(BaseModel):
    enabled: bool = True
    top_n: int = 15
    lookback_days: int = 2
    feeds: list[str] = Field(default_factory=list)


class SourcesCfg(BaseModel):
    # Papers/Repos inputs are board-owned and injected by load_config from the
    # validated domain-surface intake contract. They are required here so a
    # missing overlay cannot silently broaden to class defaults.
    arxiv: ArxivCfg
    github: GithubCfg
    signals: SignalsCfg = SignalsCfg()


class AirflowCfg(BaseModel):
    """Read-only Airflow observation for one project. Secrets stay in .env;
    this names the env keys (same pattern as the kanban bridge contract)."""
    base_url_env: str
    username_env: str
    password_env: str
    ui_url: str
    draft_cards_on_failure: bool = False
    card_section: str = "DAGs"


class ProjectCfg(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repo: str = Field(min_length=1)
    watch_packages: bool = True
    dags_dir: str = ""
    airflow: AirflowCfg | None = None


class ProjectsConfig(BaseModel):
    schema_version: str
    projects: list[ProjectCfg] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_projects(self):
        names = [project.name for project in self.projects]
        if len(names) != len(set(names)):
            raise ValueError("projects contains duplicate names")
        return self


class ResearchProjectCfg(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location_ref: str = Field(min_length=1)
    remote_url: str = Field(min_length=1)
    research_capabilities: list[str] = Field(default_factory=list, max_length=12)


def load_projects(path: str | Path = DEFAULT_PROJECTS) -> ProjectsConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ProjectsConfig(**data)


def load_research_projects(
    path: str | Path | None = None,
) -> list[ResearchProjectCfg]:
    """Load the cockpit/onboarding repository authority for research fit.

    configs/autonomy.yaml repo_manifests is the registry exposed by the UI and
    written by repo onboarding. Research analysis must cover that exact set,
    not the narrower Growth OS observation registry.
    """
    selected = Path(path or os.environ.get(
        "GROWTHOS_AUTONOMY_CONFIG", str(DEFAULT_AUTONOMY)))
    data = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    config = AutonomyConfig.model_validate(data)
    if not 1 <= len(config.repo_manifests) <= 50:
        raise ValueError(
            "autonomy repo_manifests must contain between 1 and 50 repositories")
    return [
        ResearchProjectCfg(
            name=manifest.repo_id,
            location_ref=manifest.local_path_ref or manifest.remote_url,
            remote_url=manifest.remote_url,
            research_capabilities=list(manifest.research_capabilities),
        )
        for manifest in config.repo_manifests
    ]


class ScoringCfg(BaseModel):
    method: str = "keyword"            # "embedding" (semantic, needs Ollama) | "keyword"
    embed_model: str = "nomic-embed-text"
    embed_scale: float = 10.0          # cosine similarity -> score scale


class Config(BaseModel):
    interest_profile: InterestProfile = InterestProfile()
    # Always constructed by load_config after the board-owned intake overlay.
    # A bare Config() would bypass that authority boundary, so sources is required.
    sources: SourcesCfg
    scoring: ScoringCfg = ScoringCfg()


def _producer_parameters(
    domain_data: dict[str, Any], producer: str, *,
    domain_id: str, card_component: str, board_id: str,
) -> dict[str, Any]:
    domains = DomainSurfacesConfig.model_validate(domain_data).domains
    matches = [domain for domain in domains if domain.intake.producer == producer]
    if len(matches) != 1:
        raise ValueError(
            f"domain_surfaces must define exactly one {producer!r} intake; "
            f"found {len(matches)}")
    domain = next((row for row in domains if row.domain_id == domain_id), None)
    if domain is None:
        raise ValueError(f"domain_surfaces is missing required {domain_id!r} domain")
    if (
        domain is not matches[0]
        or domain.card_component != card_component
        or domain.source != "board_store"
        or domain.board_id != board_id
    ):
        raise ValueError(
            f"{producer!r} must be owned by domain {domain_id!r} with "
            f"card_component={card_component!r}, source='board_store', "
            f"board_id={board_id!r}")
    return dict(domain.intake.parameters)


def load_config(
    path: str | Path = "config/sources.yaml",
    *,
    domain_surfaces_path: str | Path | None = None,
) -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = dict(data.get("sources") or {})
    duplicated = {"arxiv", "github"} & set(sources)
    if duplicated:
        raise ValueError(
            "arxiv/github inputs are owned by configs/domain_surfaces.yaml; "
            f"remove duplicate source block(s): {sorted(duplicated)}")
    domain_path = Path(domain_surfaces_path or DEFAULT_DOMAIN_SURFACES)
    if not domain_path.is_file():
        raise FileNotFoundError(
            f"Growth OS domain intake config is unavailable: {domain_path}")
    domain_data = yaml.safe_load(domain_path.read_text(encoding="utf-8")) or {}
    sources["arxiv"] = _producer_parameters(
        domain_data, "growth_os_arxiv",
        domain_id="paper", card_component="paper", board_id="research_papers")
    sources["github"] = _producer_parameters(
        domain_data, "growth_os_github",
        domain_id="repo", card_component="repo", board_id="research_repos")
    merged = dict(data)
    merged["sources"] = sources
    return Config.model_validate(merged)


def load_settings() -> Settings:
    return Settings()

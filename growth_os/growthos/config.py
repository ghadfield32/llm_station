"""Load + validate configuration. Secrets come from env; feeds from YAML.
Fails fast (Pydantic) so a bad config never silently degrades a run."""
from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class InterestProfile(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)


class ArxivCfg(BaseModel):
    enabled: bool = True
    top_n: int = 12
    lookback_days: int = 3
    categories: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class GithubCfg(BaseModel):
    enabled: bool = True
    top_n: int = 10
    lookback_days: int = 7
    min_stars: int = 25
    queries: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class SignalsCfg(BaseModel):
    enabled: bool = True
    top_n: int = 15
    lookback_days: int = 2
    feeds: list[str] = Field(default_factory=list)


class SourcesCfg(BaseModel):
    arxiv: ArxivCfg = ArxivCfg()
    github: GithubCfg = GithubCfg()
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
    name: str
    repo: str
    watch_packages: bool = True
    dags_dir: str = ""
    airflow: AirflowCfg | None = None


class ProjectsConfig(BaseModel):
    schema_version: str
    projects: list[ProjectCfg]


def load_projects(path: str | Path = "config/projects.yaml") -> ProjectsConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ProjectsConfig(**data)


class ScoringCfg(BaseModel):
    method: str = "keyword"            # "embedding" (semantic, needs Ollama) | "keyword"
    embed_model: str = "nomic-embed-text"
    embed_scale: float = 10.0          # cosine similarity -> score scale


class Config(BaseModel):
    interest_profile: InterestProfile = InterestProfile()
    sources: SourcesCfg = SourcesCfg()
    scoring: ScoringCfg = ScoringCfg()


def load_config(path: str | Path = "config/sources.yaml") -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Config(**data)


def load_settings() -> Settings:
    return Settings()

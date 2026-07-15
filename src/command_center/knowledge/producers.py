"""
Producers — deterministic, observer-only extractors that read an authoritative source and emit
OKF concept drafts. They NEVER write to or mutate a source; they only read it and project facts
into `authority: derived` concepts that point back at the source.

Each producer is a pure function `(root: Path, now_iso: str) -> list[ConceptDraft]`. `now_iso` is
injected (the run's logical timestamp) so the producers stay wall-clock-free and deterministic:
the same repo state + the same `now_iso` always yields byte-identical drafts.

Facts come from the source, not from prose generation — a config's keys, the Makefile's `##` help
targets, the Ledger's experiment rows, the DAG files on disk. A source that is absent yields no
concept (honest), never a fabricated one.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .profile import (
    Authority, Confidence, OkfConcept, Sensitivity, SourceSystem, Status,
)

_REVIEW_DAYS = 30


@dataclass
class ConceptDraft:
    section: str                  # bundle subdir: system | standards | experiments | …
    name: str                     # file stem (slug)
    frontmatter: OkfConcept
    generated: str                # the generated-block markdown


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "x"


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _plus_days(now_iso: str, days: int) -> str:
    base = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    return (base + timedelta(days=days)).isoformat()


def _concept(*, type_: str, title: str, description: str, resource: str, tags: list[str],
             now_iso: str, source_system: SourceSystem, source_path: str,
             source_hash: str | None, owner: str = "command-center",
             authority: Authority = Authority.DERIVED, status: Status = Status.CURRENT,
             confidence: Confidence = Confidence.HIGH, experiment_id: str | None = None) -> OkfConcept:
    return OkfConcept(
        type=type_, title=title, description=description, resource=resource, tags=tags,
        timestamp=now_iso, last_verified_at=now_iso, source_system=source_system,
        source_path=source_path, source_hash=source_hash, authority=authority, owner=owner,
        status=status, sensitivity=Sensitivity.INTERNAL, confidence=confidence,
        experiment_id=experiment_id, review_after=_plus_days(now_iso, _REVIEW_DAYS))


def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- system

def produce_risk_tiers(root: Path, now_iso: str) -> list[ConceptDraft]:
    p = root / "configs" / "gates.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    tiers = data.get("tiers") or data.get("risk_tiers") or {}
    lines = ["The L0–L4 permission model — one risk ladder for every action.", ""]
    if isinstance(tiers, dict):
        for name, spec in tiers.items():
            detail = spec if isinstance(spec, str) else (spec.get("description", "") if isinstance(spec, dict) else "")
            lines.append(f"- **{name}** — {detail}")
    elif isinstance(tiers, list):
        for spec in tiers:
            if isinstance(spec, dict):
                lines.append(f"- **{spec.get('id', spec.get('name', '?'))}** — {spec.get('description', '')}")
    fm = _concept(type_="System", title="Risk tiers (L0–L4)",
                  description="The single permission/approval ladder governing every action.",
                  resource="config://configs/gates.yaml", tags=["risk", "gates", "approval"],
                  now_iso=now_iso, source_system=SourceSystem.CONFIG,
                  source_path="configs/gates.yaml", source_hash=_sha256_file(p),
                  confidence=Confidence.VERIFIED)
    return [ConceptDraft("system", "risk-tiers", fm, "\n".join(lines))]


def produce_operator_interface(root: Path, now_iso: str) -> list[ConceptDraft]:
    p = root / "Makefile"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    targets = re.findall(r"^([a-zA-Z0-9_-]+):.*?##\s*(.+)$", text, flags=re.MULTILINE)
    lines = ["Operator commands (`make <target>`; Windows: `.\\scripts\\cc.ps1 <target>`).", ""]
    lines += [f"- `make {name}` — {help_.strip()}" for name, help_ in targets]
    fm = _concept(type_="Runbook", title="Operator interface",
                  description=f"{len(targets)} make targets — the operator entry points.",
                  resource="repo://llm_station/Makefile", tags=["operator", "make", "cli"],
                  now_iso=now_iso, source_system=SourceSystem.REPOSITORY,
                  source_path="Makefile", source_hash=_sha256_file(p),
                  confidence=Confidence.VERIFIED)
    return [ConceptDraft("system", "operator-interface", fm, "\n".join(lines))]


def produce_configuration_model(root: Path, now_iso: str) -> list[ConceptDraft]:
    cfg = root / "configs"
    if not cfg.exists():
        return []
    files = sorted(p.name for p in cfg.glob("*.yaml"))
    lines = ["The contract model: edit `configs/*.yaml` → Pydantic contracts validate them →",
             "`generated/` is rendered (disposable) → `ledger.db` holds the only runtime state.", "",
             "Config files under contract:", ""]
    lines += [f"- `configs/{f}`" for f in files]
    fm = _concept(type_="System", title="Configuration model",
                  description="The one rule: YAML configs are the editable source of truth; "
                              "strict contracts reject unsafe states at validation time.",
                  resource="repo://llm_station/configs", tags=["contracts", "configs", "pydantic"],
                  now_iso=now_iso, source_system=SourceSystem.CONFIG,
                  source_path="configs/", source_hash=None, confidence=Confidence.VERIFIED)
    return [ConceptDraft("system", "configuration-model", fm, "\n".join(lines))]


# --------------------------------------------------------------------- standards

def produce_standards(root: Path, now_iso: str) -> list[ConceptDraft]:
    p = root / "configs" / "standards.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    out: list[ConceptDraft] = []
    profiles = data.get("profiles") or {}
    keys = sorted(profiles) if isinstance(profiles, dict) else []
    lines = ["Durable operating standards rendered into CLAUDE.md / AGENTS.md and enforced by the",
             "Judge Gate. Profiles:", ""]
    lines += [f"- **{k}**" for k in keys] or ["- (see standards.yaml)"]
    fm = _concept(type_="Standard", title="Operating standards",
                  description="Coding/operating standards → agent profiles + Judge Gate.",
                  resource="config://configs/standards.yaml", tags=["standards", "judge", "policy"],
                  now_iso=now_iso, source_system=SourceSystem.CONFIG,
                  source_path="configs/standards.yaml", source_hash=_sha256_file(p),
                  confidence=Confidence.VERIFIED)
    out.append(ConceptDraft("standards", "operating-standards", fm, "\n".join(lines)))
    return out


# --------------------------------------------------------------------- models

def produce_models(root: Path, now_iso: str) -> list[ConceptDraft]:
    p = root / "configs" / "models.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    roles = data.get("roles") or data.get("models") or {}
    lines = ["Local-only model roles (every role must be `provider: ollama, local: true`).", ""]
    if isinstance(roles, dict):
        for role, spec in roles.items():
            # A role maps to a LIST of ranked candidate dicts (ModelRegistry
            # schema). Render each candidate's model in priority order, matching
            # render.py — never an empty string, which would misreport the route.
            cands = spec if isinstance(spec, list) else []
            ordered = sorted(
                (c for c in cands if isinstance(c, dict)),
                key=lambda c: c.get("priority", 99))
            cand = ", ".join(c["model"] for c in ordered if c.get("model"))
            lines.append(f"- **{role}** → `{cand}`")
    fm = _concept(type_="System", title="Model roles",
                  description="Role → ranked local Ollama model candidates (no provider keys).",
                  resource="config://configs/models.yaml", tags=["models", "ollama", "routing"],
                  now_iso=now_iso, source_system=SourceSystem.CONFIG,
                  source_path="configs/models.yaml", source_hash=_sha256_file(p))
    return [ConceptDraft("models", "model-roles", fm, "\n".join(lines))]


# --------------------------------------------------------------------- repositories

def produce_repositories(root: Path, now_iso: str) -> list[ConceptDraft]:
    p = root / "growth_os" / "config" / "projects.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    projects = data.get("projects") or data
    # projects.yaml uses a LIST of {name, repo, …}; tolerate a dict form too.
    if isinstance(projects, list):
        records = [s for s in projects if isinstance(s, dict)]
    elif isinstance(projects, dict):
        records = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in projects.items()]
    else:
        records = []
    out: list[ConceptDraft] = []
    for spec in records:
        name = spec.get("name", "?")
        repo = spec.get("repo", name)
        lines = [f"Observed repository **{name}** (watched by the Growth OS curator).", "",
                 f"- repo: `{repo}`"]
        for k in ("watch_packages", "dags_dir"):
            if k in spec:
                lines.append(f"- {k}: `{spec[k]}`")
        fm = _concept(type_="Repository", title=f"Repository: {name}",
                      description=f"Observe-registry entry for {name}.",
                      resource=f"repo://{repo}", tags=["repository", "observe"],
                      now_iso=now_iso, source_system=SourceSystem.GROWTH_OS,
                      source_path="growth_os/config/projects.yaml",
                      source_hash=_sha256_file(p), authority=Authority.OBSERVED)
        out.append(ConceptDraft("repositories", _slug(str(name)), fm, "\n".join(lines)))
    return out


# --------------------------------------------------------------------- dags

def produce_dags(root: Path, now_iso: str) -> list[ConceptDraft]:
    d = root / "dags"
    if not d.exists():
        return []
    out: list[ConceptDraft] = []
    for p in sorted(d.glob("*.py")):
        text = p.read_text(encoding="utf-8")
        m = re.search(r'"""\s*\n?(.+?)(?:\n|""")', text, flags=re.DOTALL)
        first = (m.group(1).strip().splitlines()[0] if m else p.stem) if m else p.stem
        observer = "observer-only" in text.lower()
        lines = [first, "", f"- file: `dags/{p.name}`",
                 f"- observer-only: {'yes' if observer else 'unverified'}"]
        fm = _concept(type_="DAG", title=f"DAG: {p.stem}",
                      description=first[:160],
                      resource=f"repo://llm_station/dags/{p.name}", tags=["dag", "airflow"],
                      now_iso=now_iso, source_system=SourceSystem.AIRFLOW,
                      source_path=f"dags/{p.name}", source_hash=_sha256_file(p))
        out.append(ConceptDraft("dags", _slug(p.stem), fm, "\n".join(lines)))
    return out


# --------------------------------------------------------------------- pipelines / metrics / APIs

def produce_pipelines(root: Path, now_iso: str) -> list[ConceptDraft]:
    specs = [
        ("self-improvement-scan", "Self-improvement scan",
         "Daily observer-only scan → Proposed cards + report across 9 pillars.",
         "repo://llm_station/src/command_center/improvement/discovery",
         "src/command_center/improvement/discovery/pipeline.py",
         "scan → classify_and_dedup → score_and_rank → draft_proposals → emit"),
        ("proactive-lane", "Proactive ops lane",
         "Scheduled checks on already-shipped work → RCA missions (human-gated).",
         "config://configs/proactive.yaml", "configs/proactive.yaml",
         "scheduled trigger → evidence → classify → RCA mission → post-watch"),
        ("model-update", "Model-update pipeline",
         "Local model rollout with no auto-promotion.",
         "config://configs/models.yaml", "configs/models.yaml",
         "scout → edit → validate → evals → canary → compare → promote/rollback"),
    ]
    out: list[ConceptDraft] = []
    for name, title, desc, resource, src, stages in specs:
        sp = root / src
        if not sp.exists():            # no source → no concept (never a fabricated one)
            continue
        lines = [desc, "", f"- stages: `{stages}`", f"- source: `{src}`"]
        fm = _concept(type_="Data Pipeline", title=title, description=desc, resource=resource,
                      tags=["pipeline"], now_iso=now_iso,
                      source_system=SourceSystem.REPOSITORY if "repo://" in resource
                      else SourceSystem.CONFIG, source_path=src, source_hash=_sha256_file(sp))
        out.append(ConceptDraft("pipelines", name, fm, "\n".join(lines)))
    return out


def produce_metrics(root: Path, now_iso: str) -> list[ConceptDraft]:
    sp = root / "src" / "command_center" / "improvement" / "selfmetrics.py"
    if not sp.exists():
        return []
    lines = ["Self-improvement metrics computed from the Ledger (pure-stdlib, deterministic):", "",
             "- DORA: deploy frequency, lead time, change-failure rate, MTTR",
             "- acceptance rate by pillar · rollback rate · cost-per-accepted",
             "- negative-result-memory hit rate",
             "- convergence power-law fit AP*(N) ≈ a − b·N^(−c)",
             "- BWT / FWT (forward/backward transfer)"]
    fm = _concept(type_="Metric", title="Self-improvement metrics",
                  description="DORA + acceptance + convergence + transfer over the experiment loop.",
                  resource="repo://llm_station/src/command_center/improvement/selfmetrics.py",
                  tags=["metrics", "dora", "self-improvement"], now_iso=now_iso,
                  source_system=SourceSystem.REPOSITORY,
                  source_path="src/command_center/improvement/selfmetrics.py",
                  source_hash=_sha256_file(sp))
    return [ConceptDraft("metrics", "self-improvement-metrics", fm, "\n".join(lines))]


def produce_apis(root: Path, now_iso: str) -> list[ConceptDraft]:
    out: list[ConceptDraft] = []
    services = [("ledger", "services/ledger", "Missions, leases, signed approvals, events — the only runtime state."),
                ("judge-gate", "services/judge_gate", "Risk classification + judge arrays at commit time.")]
    for name, src, desc in services:
        sp = root / src / "app.py"
        if not sp.exists():            # no service on disk → no concept
            continue
        lines = [desc, "", f"- source: `{src}/`"]
        fm = _concept(type_="API", title=f"Service: {name}", description=desc,
                      resource=f"repo://llm_station/{src}", tags=["service", "api"],
                      now_iso=now_iso, source_system=SourceSystem.REPOSITORY,
                      source_path=src, source_hash=_sha256_file(sp))
        out.append(ConceptDraft("APIs", name, fm, "\n".join(lines)))
    return out


# --------------------------------------------------------------------- agents (chat + kanban)

def produce_channels(root: Path, now_iso: str) -> list[ConceptDraft]:
    """The chat-gateway agents (Discord/Slack/Telegram/WhatsApp) from configs/channels.yaml."""
    p = root / "configs" / "channels.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    channels = data.get("channels") or []
    lines = ["Chat-gateway agents — every channel is one more SURFACE, not a new authority: messages",
             "route through LiteLLM (local-first) to the same Growth OS action layer, and none can",
             "approve a mission card.", "",
             "| Channel | Transport | Enabled | Model |", "|---|---|---|---|"]
    for c in channels:
        if isinstance(c, dict):
            lines.append(f"| {c.get('name')} | {c.get('transport')} | {c.get('enabled')} "
                         f"| {c.get('model')} |")
    fm = _concept(type_="API", title="Chat-gateway agents (Discord/Slack/Telegram/WhatsApp)",
                  description="The chat agents, their transports, enabled state, and model roles.",
                  resource="config://configs/channels.yaml",
                  tags=["agents", "discord", "chat", "gateway"], now_iso=now_iso,
                  source_system=SourceSystem.CONFIG, source_path="configs/channels.yaml",
                  source_hash=_sha256_file(p), confidence=Confidence.VERIFIED)
    return [ConceptDraft("APIs", "chat-gateway-agents", fm, "\n".join(lines))]


def produce_kanban(root: Path, now_iso: str) -> list[ConceptDraft]:
    """The Kanban bridge agent from configs/kanban.yaml — Approved cards → Ledger missions."""
    p = root / "configs" / "kanban.yaml"
    data = _load_yaml(p)
    if not data:
        return []
    sections = data.get("sections") or []
    lines = ["The Kanban bridge — Approved cards become Ledger missions. Agents may DRAFT cards;",
             "only a human drag to Approved dispatches one. Dispatch sections + risk ceilings:", "",
             "| Section | Target kind | Max auto risk | Ready statuses |", "|---|---|---|---|"]
    for s in sections:
        if isinstance(s, dict):
            ready = ", ".join(s.get("ready_statuses", []) or [])
            lines.append(f"| {s.get('name')} | {s.get('target_kind', '')} "
                         f"| {s.get('max_auto_risk', '')} | {ready} |")
    fm = _concept(type_="Data Pipeline", title="Kanban bridge (cards → missions)",
                  description="The dispatch contract: sections, risk ceilings, ready statuses.",
                  resource="config://configs/kanban.yaml",
                  tags=["kanban", "agents", "dispatch", "board-store"], now_iso=now_iso,
                  source_system=SourceSystem.CONFIG, source_path="configs/kanban.yaml",
                  source_hash=_sha256_file(p), confidence=Confidence.VERIFIED)
    return [ConceptDraft("pipelines", "kanban-bridge", fm, "\n".join(lines))]


# --------------------------------------------------------------------- experiments (the Ledger)

def produce_experiments(root: Path, now_iso: str) -> list[ConceptDraft]:
    """One concept per registered experiment, from the Ledger registry. Partitioned by status into
    active / promoted / rejected / inconclusive / rolled-back via the subdir in the name. The
    Ledger remains authoritative; this is a portable, searchable projection (negative-result memory)."""
    db = root / "data" / "ledger.db"
    if not db.exists():
        return []
    from ..improvement.registry import ExperimentRegistry
    rows = ExperimentRegistry(db_path=str(db)).list_experiments()
    bucket = {"Promoted": "promoted", "Rejected": "rejected", "Inconclusive": "inconclusive",
              "Rolled Back": "rolled-back"}
    out: list[ConceptDraft] = []
    for r in rows:
        status = r["status"]
        sub = bucket.get(status, "active")
        lines = [f"Experiment **{r['experiment_id']}** — status **{status}**.", "",
                 f"- target: `{r.get('target_type', '')}` → `{r.get('target_ref', '')}`",
                 f"- risk: `{r.get('risk_tier', '')}`",
                 f"- verifier verdict: `{r.get('verifier_verdict') or '-'}`",
                 f"- human decision: `{r.get('human_decision') or '-'}`"]
        # the record is `current` (it accurately reflects the experiment); `authority` carries
        # whether the experiment itself is in-flight (experimental) or a closed record (historical).
        fm = _concept(type_="Experiment", title=f"{r['experiment_id']}: {r.get('title', '')}"[:120],
                      description=f"{status} experiment on {r.get('target_type', '')}.",
                      resource=f"ledger://experiments/{r['experiment_id']}",
                      tags=["experiment", sub, str(r.get("target_type", ""))],
                      now_iso=now_iso, source_system=SourceSystem.LEDGER,
                      source_path="data/ledger.db", source_hash=None,
                      authority=Authority.EXPERIMENTAL if sub == "active" else Authority.HISTORICAL,
                      status=Status.CURRENT, experiment_id=r["experiment_id"])
        out.append(ConceptDraft(f"experiments/{sub}", _slug(r["experiment_id"]), fm, "\n".join(lines)))
    return out


# the ordered producer set the bundle runs
ALL_PRODUCERS = [
    produce_risk_tiers, produce_operator_interface, produce_configuration_model,
    produce_standards, produce_models, produce_repositories, produce_dags,
    produce_pipelines, produce_metrics, produce_apis, produce_channels,
    produce_kanban, produce_experiments,
]

# sections that always exist in a full bundle even when a producer emits nothing yet
SECTIONS = [
    "system", "standards", "repositories", "models", "pipelines", "dags", "datasets",
    "metrics", "APIs", "runbooks", "incidents", "decisions", "experiments", "skills",
]

"""
Scanners — the eyes of the daily scan. Each turns one source into `Finding`s.

Two kinds, one contract (`Scanner.scan() -> list[Finding]`):

  * The offline `CodeHealthScanner` reads the repo directly (AST + text) and is fully
    deterministic — long functions, swallowed exceptions (dogfooding the "no defensive
    coding" rule), TODO/FIXME debt, oversized modules. No network, no external tools.

  * The network-fed scanners (papers, model/provider registries, dependencies, Kanban)
    do NOT fetch — they take an injected `fetch` callable. Tests run them offline with a
    stub; the Airflow DAG wires the live fetch. A failing fetch RAISES — it is never
    swallowed into a silent "zero findings".

Failures are first-class: `run_scanners(..., isolate=True)` returns a `ScanOutcome` per
scanner so a down source becomes a visible line in the report ("source X failed: ..."),
not a quietly missing pillar. The default (isolate=False) re-raises — fail loud.
"""
from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..registry import ExperimentRegistry
from ..schema import TargetType
from ...schemas.base import RiskTier
from .findings import Finding
from .pillars import Pillar

# Directories whose churn must not destabilize a scan (mirrors the retrieval guard).
_EXCLUDE_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "generated",
    "data", "evaluation", "docs", ".mypy_cache", ".ruff_cache", ".pytest_cache",
})
_MODEL_SCOUT_EVIDENCE_FIELDS = (
    "source", "source_url", "metric", "candidate", "open_weight_evidence",
    "license", "ollama_tag", "digest", "quant", "native_context",
    "parameter_size", "vram_fit", "candidate_roles", "benchmark_name",
    "benchmark_version", "evaluation_date", "retrieval_timestamp",
    "source_payload_sha256", "source_model_id",
)
_MODEL_SCOUT_LOCAL_FIELDS = (
    "ollama_tag", "digest", "quant", "native_context", "parameter_size", "vram_fit",
)
# A pull-to-verify card targets THIS (a propose-only marker), not the live harness — you
# cannot benchmark a model that isn't installed. Once pulled + curated it returns as a
# runnable model_scout_candidate targeting command_center.improvement.live_model_benchmark.
MODEL_PULL_TARGET_REF = "command_center.improvement.model_pull_proposal"


def _present(value) -> bool:
    return value is not None and value != ""


def _model_scout_value(record: dict, key: str):
    if key == "source":
        return record.get("source_name") or record.get("source")
    return record.get(key)


def _presence_ratio(record: dict, fields: tuple[str, ...]) -> tuple[float, list[str]]:
    missing = [key for key in fields if not _present(_model_scout_value(record, key))]
    return ((len(fields) - len(missing)) / len(fields), missing)


class Scanner(ABC):
    """Observer-only: reads a source, returns Findings. Never writes anything."""
    name: str
    pillar: Pillar

    @abstractmethod
    def scan(self) -> list[Finding]:
        ...


@dataclass
class ScanOutcome:
    """The result of running one scanner — including failure, made explicit."""
    scanner: str
    pillar: Pillar
    findings: list[Finding] = field(default_factory=list)
    error: str = ""              # non-empty => this source failed; surfaced in the report

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict:
        return {"scanner": self.scanner, "pillar": self.pillar.value,
                "findings": [f.to_dict() for f in self.findings], "error": self.error}

    @classmethod
    def from_dict(cls, d: dict) -> ScanOutcome:
        """Inverse of to_dict — round-trips a per-source outcome across Airflow task XComs."""
        return cls(scanner=d["scanner"], pillar=Pillar(d["pillar"]),
                   findings=[Finding.from_dict(x) for x in d.get("findings", [])],
                   error=d.get("error", ""))


def run_scanners(scanners: Iterable[Scanner], *, isolate: bool = False) -> list[ScanOutcome]:
    """Run each scanner. isolate=False (default) lets a failure propagate (fail loud).
    isolate=True records each failure as a ScanOutcome.error instead of hiding it — used
    by the DAG/CLI so one dead feed doesn't blank the whole report, while still being
    reported as failed."""
    outcomes: list[ScanOutcome] = []
    for s in scanners:
        if isolate:
            try:
                outcomes.append(ScanOutcome(s.name, s.pillar, s.scan()))
            except Exception as e:  # recorded, not swallowed: surfaced as a failed source
                outcomes.append(ScanOutcome(s.name, s.pillar, [], error=f"{type(e).__name__}: {e}"))
        else:
            outcomes.append(ScanOutcome(s.name, s.pillar, s.scan()))
    return outcomes


# ===========================================================================
# Offline, deterministic: code health straight from the repo
# ===========================================================================

@dataclass
class CodeHealthThresholds:
    max_function_statements: int = 60     # a function longer than this is a refactor candidate
    max_module_lines: int = 600           # an oversized module
    min_debt_markers: int = 12            # TODO/FIXME/HACK/XXX count worth a card
    min_swallowed_excepts: int = 1        # any swallowed exception is worth surfacing
    sample_limit: int = 6                 # locations quoted as evidence

    @classmethod
    def from_config(cls, knobs) -> CodeHealthThresholds:
        """Build from a CodeHealthKnobs (duck-typed, so sources.py stays decoupled from config)."""
        return cls(max_function_statements=knobs.max_function_statements,
                   max_module_lines=knobs.max_module_lines,
                   min_debt_markers=knobs.min_debt_markers,
                   min_swallowed_excepts=knobs.min_swallowed_excepts,
                   sample_limit=knobs.sample_limit)


_DEBT_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")


def _py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        if any(part in _EXCLUDE_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _statement_count(node: ast.AST) -> int:
    return sum(1 for n in ast.walk(node) if isinstance(n, ast.stmt))


def _is_swallowed(handler: ast.ExceptHandler) -> bool:
    """A bare `except:` or `except Exception` whose body never re-raises — the exact
    pattern the project bans. (A handler that re-raises or raises a new error is fine.)"""
    bare = handler.type is None
    broad = isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}
    if not (bare or broad):
        return False
    return not any(isinstance(n, ast.Raise) for n in ast.walk(handler))


class CodeHealthScanner(Scanner):
    """Reads Python under `root` and emits CODE_QUALITY findings deterministically."""
    pillar = Pillar.CODE_QUALITY

    def __init__(self, root: str | Path = "src", *,
                 thresholds: CodeHealthThresholds | None = None, name: str = "code_health"):
        self.root = Path(root)
        self.t = thresholds or CodeHealthThresholds()
        self.name = name

    def scan(self) -> list[Finding]:
        if not self.root.exists():
            raise FileNotFoundError(f"code-health root {self.root} does not exist")
        long_funcs: list[str] = []
        big_modules: list[str] = []
        swallowed: list[str] = []
        debt = 0
        debt_locs: list[str] = []
        for path in _py_files(self.root):
            text = path.read_text(encoding="utf-8")
            rel = path.as_posix()
            n_lines = text.count("\n") + 1
            if n_lines > self.t.max_module_lines:
                big_modules.append(f"{rel} ({n_lines} lines)")
            for m in _DEBT_RE.finditer(text):
                debt += 1
                if len(debt_locs) < self.t.sample_limit:
                    line = text.count("\n", 0, m.start()) + 1
                    debt_locs.append(f"{rel}:{line} {m.group(1)}")
            tree = ast.parse(text, filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sc = _statement_count(node)
                    if sc > self.t.max_function_statements:
                        long_funcs.append(f"{rel}:{node.lineno} {node.name}() {sc} stmts")
                elif isinstance(node, ast.ExceptHandler) and _is_swallowed(node):
                    swallowed.append(f"{rel}:{node.lineno}")

        findings: list[Finding] = []
        t = self.t
        if len(swallowed) >= t.min_swallowed_excepts:
            findings.append(self._f(
                Pillar.CODE_QUALITY, TargetType.STANDARD, RiskTier.L2,
                title="remove swallowed exceptions",
                claim=f"{len(swallowed)} broad/bare except handler(s) never re-raise",
                samples=swallowed, impact=0.7, ease=0.6, confidence=0.85,
                risk_reduction=0.5, time_criticality=0.3,
                unknowns="which swallows mask real failures vs are intentional terminal handlers"))
        if long_funcs:
            findings.append(self._f(
                Pillar.CODE_QUALITY, TargetType.REPOSITORY_TEMPLATE, RiskTier.L1,
                title="refactor over-long functions",
                claim=f"{len(long_funcs)} function(s) exceed {t.max_function_statements} statements",
                samples=long_funcs, impact=0.5, ease=0.4, confidence=0.7))
        if big_modules:
            findings.append(self._f(
                Pillar.STRUCTURE, TargetType.REPOSITORY_TEMPLATE, RiskTier.L1,
                title="split oversized modules",
                claim=f"{len(big_modules)} module(s) exceed {t.max_module_lines} lines",
                samples=big_modules, impact=0.45, ease=0.4, confidence=0.7))
        if debt >= t.min_debt_markers:
            findings.append(self._f(
                Pillar.CODE_QUALITY, TargetType.STANDARD, RiskTier.L1,
                title="burn down TODO/FIXME debt",
                claim=f"{debt} debt marker(s) across the codebase",
                samples=debt_locs, impact=0.4, ease=0.5, confidence=0.8))
        return findings

    def _f(self, pillar: Pillar, tt: TargetType, risk: RiskTier, *, title: str, claim: str,
           samples: list[str], **kw) -> Finding:
        ev = f"{self.name}: " + "; ".join(samples[:self.t.sample_limit])
        return Finding(pillar=pillar, source=self.name, title=title, claim=claim, evidence=ev,
                       suggested_target_type=tt, suggested_risk=risk,
                       detail={"count": len(samples), "samples": samples[:self.t.sample_limit]},
                       **kw)


# ===========================================================================
# Injected fetch: papers, model/provider registries, dependencies, Kanban
# ===========================================================================

# A fetch returns already-parsed records; the DAG owns the actual HTTP/CLI call.
Fetch = Callable[[], list[dict]]


class FeedScanner(Scanner):
    """A scanner over an injected `fetch()`. Subclasses implement `_classify(record)`.
    The fetch is called exactly once per scan; if it raises, the scan raises."""

    def __init__(self, name: str, pillar: Pillar, fetch: Fetch):
        self.name = name
        self.pillar = pillar
        self._fetch = fetch

    def scan(self) -> list[Finding]:
        records = self._fetch()
        if not isinstance(records, list):
            raise TypeError(f"{self.name} fetch must return a list, got {type(records).__name__}")
        out: list[Finding] = []
        for rec in records:
            f = self._classify(rec)
            if f is not None:
                out.append(f)
        return out

    @abstractmethod
    def _classify(self, record: dict) -> Finding | None:
        ...


class PapersScanner(FeedScanner):
    """arXiv / Semantic Scholar / Papers-with-Code records -> FULL_IDEA findings.
    Record: {title, abstract, url, relevance (0..1), applicability (0..1)}."""

    def __init__(self, fetch: Fetch, *, name: str = "arxiv", min_relevance: float = 0.6):
        super().__init__(name, Pillar.FULL_IDEA, fetch)
        self.min_relevance = min_relevance

    def _classify(self, record: dict) -> Finding | None:
        rel = float(record["relevance"])
        if rel < self.min_relevance:
            return None
        appl = float(record.get("applicability", 0.5))
        return Finding(
            pillar=Pillar.FULL_IDEA, source=self.name, title=record["title"][:80],
            claim=f"new method (relevance {rel:.2f}) applicable to our stack",
            evidence=f"{self.name}: {record.get('url', '?')} — {record['abstract'][:200]}",
            confidence=min(0.9, rel), impact=appl, ease=0.4, reach=2.0, effort=2.0,
            voi_value=appl, voi_prob=rel, suggested_target_type=TargetType.SKILL,
            suggested_risk=RiskTier.L2, unknowns="whether the paper's gains hold on our data",
            detail={"url": record.get("url", ""), "n_sources": 1})


class ModelRegistryScanner(FeedScanner):
    """LiteLLM/OpenRouter/Arena/HF records -> UPDATED_METRICS findings.
    Record: {model, provider, metric, candidate, incumbent, direction(increase|decrease),
             cost_per_mtok}. A candidate that beats the incumbent on `metric` is a Finding."""

    def __init__(self, fetch: Fetch, *, name: str = "litellm_registry"):
        super().__init__(name, Pillar.UPDATED_METRICS, fetch)

    def _classify(self, record: dict) -> Finding | None:
        rtype = record.get("record_type")
        if rtype == "model_scout_candidate":
            return self._classify_model_scout(record)
        if rtype == "frontier_watch":
            return self._classify_frontier_watch(record)
        if rtype == "model_pull_candidate":
            return self._classify_model_pull(record)
        cand, inc = float(record["candidate"]), float(record["incumbent"])
        better = cand > inc if record.get("direction", "increase") == "increase" else cand < inc
        if not better:
            return None
        lift = abs(cand - inc) / (abs(inc) + 1e-9)
        return Finding(
            pillar=Pillar.UPDATED_METRICS, source=self.name,
            title=f"evaluate {record['model']} on {record['metric']}",
            claim=(f"{record['model']} ({record.get('provider', '?')}) "
                   f"{record['metric']}={cand} vs incumbent {inc} ({lift:.0%} better)"),
            evidence=f"{self.name}: {record['model']} {record['metric']} {inc}->{cand}",
            confidence=min(0.85, 0.5 + lift), impact=min(1.0, lift * 2), ease=0.5,
            reach=3.0, effort=1.0, time_criticality=0.4,
            voi_value=min(1.0, lift * 2), voi_prob=0.7, cost=1.0,
            suggested_target_type=TargetType.ROUTING, suggested_risk=RiskTier.L2,
            unknowns="cost/latency tradeoff and whether the public benchmark matches our tasks",
            detail={"cost_per_mtok": record.get("cost_per_mtok"), "lift": lift})

    def _classify_model_scout(self, record: dict) -> Finding | None:
        if record.get("open_weight") is not True or record.get("candidate") is None:
            return None
        score = float(record["candidate"])
        model = str(record["model"])
        metric = str(record.get("metric") or "coding_score")
        roles = record.get("candidate_roles")
        if not isinstance(roles, list) or not roles:
            raise RuntimeError(
                f"model_scout_candidate {model!r} must declare candidate_roles")
        evidence_bits = [
            f"source={record.get('source_name') or record.get('source')}",
            f"{metric}={score}",
            f"candidate_roles={','.join(str(role) for role in roles)}",
            f"open_weight={record.get('open_weight_evidence')}",
        ]
        for key in (
            "license", "ollama_tag", "digest", "quant", "native_context",
            "vram_fit", "benchmark_name", "benchmark_version", "evaluation_date",
            "retrieval_timestamp", "source_payload_sha256", "source_model_id",
        ):
            if record.get(key) is not None:
                evidence_bits.append(f"{key}={record[key]}")
        evidence_completeness, missing_evidence = _presence_ratio(
            record, _MODEL_SCOUT_EVIDENCE_FIELDS)
        local_readiness, missing_local = _presence_ratio(record, _MODEL_SCOUT_LOCAL_FIELDS)
        # The ranking values below are evidence-derived. They describe how ready
        # this record is for a local benchmark, not whether the model is better.
        benchmark_effort = 1.0 + float(len(missing_local))
        return Finding(
            pillar=Pillar.UPDATED_METRICS,
            source=self.name,
            title=f"benchmark open-weight model {model}",
            claim=(f"{model} has public {metric}={score}; run local role-specific "
                   "A/B before any routing recommendation"),
            evidence=f"{self.name}: " + "; ".join(evidence_bits),
            confidence=evidence_completeness,
            impact=evidence_completeness,
            ease=local_readiness,
            reach=float(len(roles)),
            effort=benchmark_effort,
            time_criticality=0.0,
            risk_reduction=0.0,
            voi_value=evidence_completeness,
            voi_prob=local_readiness,
            cost=benchmark_effort,
            suggested_target_type=TargetType.MODEL,
            target_ref="command_center.improvement.live_model_benchmark",
            suggested_risk=RiskTier.L2,
            unknowns="whether this model beats current local role incumbents on live local tasks",
            detail={
                "record_type": "model_scout_candidate",
                "model": model,
                "metric": metric,
                "score": score,
                # Resolved live-A/B parameters (role/suite/incumbent/candidate/endpoint/context)
                # when the scout could bind them — this is what lets the drafted card be RUNNABLE
                # rather than an inert shell. None for an unresolved candidate.
                "model_benchmark": record.get("model_benchmark"),
                "candidate_roles": [str(role) for role in roles],
                "source_url": record.get("source_url"),
                "license": record.get("license"),
                "ollama_tag": record.get("ollama_tag"),
                "digest": record.get("digest"),
                "quant": record.get("quant"),
                "native_context": record.get("native_context"),
                "parameter_size": record.get("parameter_size"),
                "params_b": record.get("params_b"),
                "vram_fit": record.get("vram_fit"),
                "model_family": record.get("model_family"),
                "release_id": record.get("release_id"),
                "source_model_id": record.get("source_model_id"),
                "source_model_url": record.get("source_model_url"),
                "source_model_payload_sha256": record.get("source_model_payload_sha256"),
                "benchmark_name": record.get("benchmark_name"),
                "benchmark_version": record.get("benchmark_version"),
                "score_definition": record.get("score_definition"),
                "evaluation_date": record.get("evaluation_date"),
                "retrieval_timestamp": record.get("retrieval_timestamp"),
                "source_payload_sha256": record.get("source_payload_sha256"),
                "evidence_completeness": evidence_completeness,
                "local_readiness": local_readiness,
                "missing_evidence_fields": missing_evidence,
                "missing_local_fields": missing_local,
            })


    def _classify_frontier_watch(self, record: dict) -> Finding | None:
        """A real open-weight FLAGSHIP that does NOT fit this hardware (GLM-5.2, Kimi K2, ...).
        Track-as-context only: a low-priority DOCUMENTATION note, NEVER a local benchmark — the
        live harness is Ollama-only and these models are 5-25x too large. This is how the daily
        scan "checks on" frontier models by name without ever pretending it can run them."""
        if record.get("open_weight") is not True:
            return None
        model = str(record["model"])
        family = record.get("model_family", "?")
        params = record.get("parameter_count_b")
        fit24, fit16 = record.get("fit_24gb"), record.get("fit_16gb")
        return Finding(
            pillar=Pillar.UPDATED_METRICS, source=self.name,
            title=f"frontier-watch: {model} (track-as-context)"[:80],
            claim=(f"{model} ({family}, ~{params}B) is open-weight but does not fit this "
                   f"hardware (24GB: {fit24}; 16GB: {fit16}); track as context, do not "
                   "benchmark locally"),
            evidence=(f"{self.name}: frontier_watch {model}; license={record.get('license')}; "
                      f"fit_24gb={fit24}; fit_16gb={fit16}; "
                      f"source={record.get('source_model_url')}"),
            confidence=0.6, impact=0.15, ease=0.2, reach=1.0, effort=1.0,
            time_criticality=0.0, voi_value=0.15, voi_prob=0.3, cost=1.0,
            suggested_target_type=TargetType.DOCUMENTATION,
            target_ref=f"discovery/updated_metrics/frontier-watch/{family}",
            suggested_risk=RiskTier.L1,
            unknowns="whether local hardware or a small-enough quant ever makes this runnable",
            detail={"record_type": "frontier_watch", "tier": "frontier_watch", "model": model,
                    "parameter_count_b": params, "active_param_count_b":
                    record.get("active_param_count_b"), "is_moe": record.get("is_moe"),
                    "fit_24gb": fit24, "fit_16gb": fit16, "license": record.get("license"),
                    "source_model_url": record.get("source_model_url"),
                    "notes": record.get("notes")})

    def _classify_model_pull(self, record: dict) -> Finding | None:
        """A plausibly-fitting open-weight model we have NOT pulled (e.g. gpt-oss-20b).
        Propose-only: draft a "pull then benchmark" card for the declared role. It targets a
        PULL-PROPOSAL ref — NOT the live harness — because you cannot benchmark a model that is
        not installed; once pulled and added to curated-openweight it returns as a runnable
        model_scout_candidate. Never auto-pulls."""
        if record.get("open_weight") is not True:
            return None
        model = str(record["model"])
        tag = record.get("ollama_tag")
        roles = record.get("candidate_roles")
        if not isinstance(roles, list) or not roles:
            raise RuntimeError(f"model_pull_candidate {model!r} must declare candidate_roles")
        fit24 = record.get("fit_24gb")
        return Finding(
            pillar=Pillar.UPDATED_METRICS, source=self.name,
            title=f"pull-to-verify: {model} for {','.join(roles)}"[:80],
            claim=(f"{model} (tag {tag}) plausibly fits (24GB: {fit24}); pull it and run the "
                   f"{roles[0]} benchmark A/B vs the incumbent before any routing change"),
            evidence=(f"{self.name}: model_pull_candidate {model}; tag={tag}; "
                      f"roles={','.join(str(r) for r in roles)}; fit_24gb={fit24}; "
                      f"fit_16gb={record.get('fit_16gb')}; license={record.get('license')}; "
                      f"source={record.get('source_model_url')}"),
            confidence=0.55, impact=0.5, ease=0.3, reach=float(len(roles)), effort=2.0,
            time_criticality=0.0, voi_value=0.5, voi_prob=0.5, cost=2.0,
            suggested_target_type=TargetType.MODEL,
            target_ref=MODEL_PULL_TARGET_REF,
            suggested_risk=RiskTier.L2,
            unknowns="whether it fits at the needed context and beats the incumbent locally",
            detail={"record_type": "model_pull_candidate", "tier": "pull_to_verify",
                    "model": model, "ollama_tag": tag,
                    "candidate_roles": [str(r) for r in roles], "fit_24gb": fit24,
                    "fit_16gb": record.get("fit_16gb"), "license": record.get("license"),
                    "source_model_url": record.get("source_model_url"),
                    "requires_pull": True, "notes": record.get("notes")})


class DependencyScanner(FeedScanner):
    """pip-audit / outdated records -> CODE_QUALITY findings. NEVER auto-merges — emits a
    card only. Record: {package, current, latest, severity(none|low|moderate|high|critical),
                        advisory}."""
    _SEV = {"none": 0.0, "low": 0.3, "moderate": 0.5, "high": 0.8, "critical": 1.0}

    def __init__(self, fetch: Fetch, *, name: str = "pip_audit"):
        super().__init__(name, Pillar.CODE_QUALITY, fetch)

    def _classify(self, record: dict) -> Finding | None:
        sev = self._SEV[record.get("severity", "none")]
        outdated = record.get("current") != record.get("latest")
        if sev == 0.0 and not outdated:
            return None
        vuln = sev > 0.0
        return Finding(
            pillar=Pillar.CODE_QUALITY, source=self.name,
            title=f"{'patch vulnerable' if vuln else 'update'} {record['package']}",
            claim=(f"{record['package']} {record.get('current')}->{record.get('latest')}"
                   + (f"; {record.get('severity')} advisory" if vuln else "")),
            evidence=f"{self.name}: {record.get('advisory') or 'outdated dependency'}",
            confidence=0.95 if vuln else 0.8,
            impact=0.5 + 0.5 * sev, ease=0.6, effort=0.5,
            time_criticality=sev, risk_reduction=sev,   # WSJF lifts criticals to the top
            suggested_target_type=TargetType.TOOL,
            suggested_risk=RiskTier.L2,
            unknowns="breaking changes in the upgrade; a human reviews and merges the PR",
            detail={"package": record["package"], "severity": record.get("severity", "none")})


class KanbanScanner(FeedScanner):
    """AppFlowy/Kanban records -> AUTOMATION findings (stale or aged cards = process toil).
    Record: {title, column, age_days, blocked(bool)}."""

    def __init__(self, fetch: Fetch, *, name: str = "kanban_cycle_time", max_age_days: float = 14):
        super().__init__(name, Pillar.AUTOMATION, fetch)
        self.max_age_days = max_age_days

    def _classify(self, record: dict) -> Finding | None:
        age = float(record.get("age_days", 0))
        if age < self.max_age_days and not record.get("blocked"):
            return None
        return Finding(
            pillar=Pillar.AUTOMATION, source=self.name,
            title=f"unblock/automate: {record['title'][:60]}",
            claim=f"card aged {age:.0f}d in '{record.get('column', '?')}'"
                  + (" (blocked)" if record.get("blocked") else ""),
            evidence=f"{self.name}: '{record['title']}' age={age}d blocked={record.get('blocked')}",
            confidence=0.7, impact=0.4, ease=0.5, time_criticality=min(1.0, age / 30.0),
            suggested_target_type=TargetType.WORKFLOW, suggested_risk=RiskTier.L1,
            unknowns="whether the delay is process toil or a genuine dependency",
            detail={"age_days": age, "column": record.get("column")})


class ResearchSourceScanner(FeedScanner):
    """External-idea intake records (from the research catalog) -> FULL_IDEA findings.

    Record: {record_type: "research_source", id, title, source, source_type, url,
             concept_cluster, claim, related_modules, measured_gap, priority, risk_level,
             evidence_completeness, notes}.

    This is the productized MASTER.md §5.2 gate. Each finding is an *evaluation* task, not
    an adoption: the drafted card is L1 (plan-only, the read-only intake), and its confidence
    is the record's evidence_completeness — so a bare link with no measured gap is correctly
    low-confidence and a well-scoped candidate with a measured gap ranks up. Adoption still
    requires the full human wall (measured gap + threat model + pre-registered experiment)."""

    def __init__(self, fetch: Fetch, *, name: str = "research_digest"):
        super().__init__(name, Pillar.FULL_IDEA, fetch)

    def _classify(self, record: dict) -> Finding | None:
        if record.get("record_type") != "research_source":
            return None
        title = str(record.get("title") or record.get("id") or "research source")
        completeness = float(record.get("evidence_completeness", 0.0))
        gap = record.get("measured_gap")
        priority = str(record.get("priority", "medium"))
        impact = {"high": 0.8, "medium": 0.5, "low": 0.3}.get(priority, 0.5)
        modules = record.get("related_modules") or []
        cluster = record.get("concept_cluster", "?")
        gap_line = f"measured gap: {gap}" if gap else "NO measured gap yet (§5.2 blocks adoption)"
        return Finding(
            pillar=Pillar.FULL_IDEA, source=self.name,
            title=f"evaluate {record.get('source', title)} for {cluster}"[:80],
            claim=(f"{record.get('claim', title)} — {gap_line}; read-only evaluation only, "
                   "adoption needs threat model + pre-registered experiment (§5.2/§13)"),
            evidence=(f"{self.name}: {record.get('source_type', '?')} {record.get('url', '')} "
                      f"cluster={cluster} modules={','.join(modules) or 'none'}"),
            confidence=min(0.9, completeness),
            impact=impact,
            ease=completeness,          # a decision-grade record is easier to evaluate
            reach=float(len(modules) or 1),
            effort=2.0,
            voi_value=impact,
            voi_prob=completeness,
            suggested_target_type=TargetType.SKILL,
            suggested_risk=RiskTier.L1,
            unknowns=("whether a measured gap exists and the capability isn't already in-stack"
                      if not gap else "whether the measured gain holds inside our contracts"),
            detail={"record_type": "research_source", "id": record.get("id"),
                    "concept_cluster": cluster, "related_modules": list(modules),
                    "url": record.get("url", ""), "measured_gap": gap})


# ===========================================================================
# Offline: the Ledger's own negative-result / reliability signal
# ===========================================================================

class LedgerHealthScanner(Scanner):
    """Reads the experiment registry directly (local, no injection) for reliability signals:
    a cluster of rollbacks or rejections on the same target type is a RELIABILITY finding."""
    pillar = Pillar.RELIABILITY_OBSERVABILITY
    name = "ledger"

    def __init__(self, registry: ExperimentRegistry, *, min_cluster: int = 2):
        self.reg = registry
        self.min_cluster = min_cluster

    def scan(self) -> list[Finding]:
        rows = self.reg.list_experiments()
        by_target: dict[str, int] = {}
        for r in rows:
            if r["status"] in ("Rolled Back", "Rejected"):
                by_target[r["target_type"]] = by_target.get(r["target_type"], 0) + 1
        findings: list[Finding] = []
        for target_type, n in sorted(by_target.items()):
            if n < self.min_cluster:
                continue
            findings.append(Finding(
                pillar=Pillar.RELIABILITY_OBSERVABILITY, source=self.name,
                title=f"recurring failures on {target_type} experiments",
                claim=f"{n} rolled-back/rejected {target_type} experiment(s)",
                evidence=f"{self.name}: {n} negative outcomes on target_type={target_type}",
                confidence=0.75, impact=0.6, ease=0.4, risk_reduction=0.5,
                time_criticality=0.4, suggested_target_type=TargetType.PROACTIVE_CHECK,
                suggested_risk=RiskTier.L2,
                unknowns="shared root cause vs unrelated failures",
                detail={"target_type": target_type, "count": n}))
        return findings

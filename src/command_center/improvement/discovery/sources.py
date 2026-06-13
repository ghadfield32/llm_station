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

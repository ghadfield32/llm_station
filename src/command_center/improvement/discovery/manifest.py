"""
The report manifest — a provenance sidecar written next to the daily report (PIPELINE_STANDARDS
§0.14 "sidecar manifest: producer, git SHA, input hash, schema hash, output sha256"). It makes a
report reproducible and tamper-evident: you can tell which code + inputs produced it, and whether
the file changed.

`produced_at` is INJECTED (the run's logical timestamp) so the core stays wall-clock-free and
deterministic. `git_sha` and library versions are best-effort provenance — genuinely unavailable
provenance is recorded as honest `null` (missing-data-as-null), never fabricated.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .sources import ScanOutcome

_PROVENANCE_LIBS = ("pydantic", "PyYAML")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _git_sha() -> str | None:
    """The current commit, or None if this isn't a git checkout / git is absent (honest null)."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=5, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    sha = out.stdout.strip()
    return sha or None


def _lib_versions() -> dict[str, str | None]:
    from importlib.metadata import PackageNotFoundError, version
    out: dict[str, str | None] = {"python": sys.version.split()[0]}
    for lib in _PROVENANCE_LIBS:
        try:
            out[lib] = version(lib)
        except PackageNotFoundError:
            out[lib] = None
    return out


@dataclass
class ReportManifest:
    output_sha256: str           # sha256 of the report markdown (tamper-evident)
    input_sha256: str            # sha256 of the inputs that produced it (sources + method + config)
    produced_at: str             # injected logical timestamp (not wall-clock)
    git_sha: str | None
    library_versions: dict
    sources: list[dict]          # [{name, ok, error}]
    counts: dict                 # n_sources, n_failed, n_findings, n_drafted
    method: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "produced_at": self.produced_at,
            "output_sha256": self.output_sha256, "input_sha256": self.input_sha256,
            "git_sha": self.git_sha, "library_versions": self.library_versions,
            "method": self.method, "counts": self.counts, "sources": self.sources,
        }


def build_manifest(*, report_markdown: str, produced_at: str, outcomes: list[ScanOutcome],
                   n_findings: int, n_drafted: int, method: str,
                   config_path: str | Path = "configs/discovery.yaml") -> ReportManifest:
    sources = [{"name": o.scanner, "ok": o.ok, "error": o.error} for o in outcomes]
    cfg_bytes = ""
    cp = Path(config_path)
    if cp.exists():
        cfg_bytes = cp.read_text(encoding="utf-8")
    input_blob = json.dumps(
        {"sources": [(o.scanner, o.ok) for o in outcomes], "method": method, "config": cfg_bytes},
        sort_keys=True)
    return ReportManifest(
        output_sha256=_sha256_text(report_markdown),
        input_sha256=_sha256_text(input_blob),
        produced_at=produced_at,
        git_sha=_git_sha(),
        library_versions=_lib_versions(),
        sources=sources,
        counts={"n_sources": len(outcomes), "n_failed": sum(1 for o in outcomes if not o.ok),
                "n_findings": n_findings, "n_drafted": n_drafted},
        method=method)


def write_manifest(report_path: str | Path, manifest: ReportManifest) -> str:
    """Write `<report>.manifest.json` next to the report. Returns its path."""
    p = Path(str(report_path) + ".manifest.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return str(p)

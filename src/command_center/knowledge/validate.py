"""
The knowledge-bundle validation gate (PIPELINE_STANDARDS "N/N PASS required") — a blocking check
that the generated `knowledge/` bundle is coherent: every concept's frontmatter validates against
the strict growth-os-0.1 profile, source paths exist, internal links resolve, no secret leaked
into a generated block, and nothing is marked `secret`. A single FAIL exits non-zero so a broken
bundle never ships. Freshness (concepts past `review_after`) is reported, not failed.
"""
from __future__ import annotations

import re
from pathlib import Path

from .document import parse_concept

# obvious secret shapes — a generated block must never contain these
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),            # OpenAI-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),               # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),   # Slack tokens
]
# source_system values whose source_path is a real file that should exist on disk
_FILESYSTEM_SOURCES = {"repository", "config", "docs"}
_LINK_RE = re.compile(r"\]\(([^)]+\.md)(?:#[^)]*)?\)")


def _concept_files(bundle: Path) -> list[Path]:
    return [p for p in sorted(bundle.rglob("*.md"))
            if p.name not in ("index.md", "log.md")]


def gate_checks(bundle_dir: str | Path, root: str | Path, *, now_iso: str) -> list[tuple[str, bool, str]]:
    bundle = Path(bundle_dir)
    root = Path(root)
    out: list[tuple[str, bool, str]] = []

    if not bundle.exists():
        return [("bundle_exists", False, f"{bundle} not found — run `knowledge generate` first")]

    files = _concept_files(bundle)
    out.append(("bundle_has_concepts", bool(files), f"{len(files)} concept files"))

    # 1. every concept parses + frontmatter validates against the strict profile
    parsed = []
    bad_parse = []
    for p in files:
        try:
            parsed.append((p, parse_concept(p.read_text(encoding="utf-8"))))
        except Exception as e:  # recorded as a failed check, surfaced — not swallowed
            bad_parse.append(f"{p.name}: {type(e).__name__}")
    out.append(("all_concepts_valid", not bad_parse,
                "all parse + validate" if not bad_parse else f"FAILED: {bad_parse[:3]}"))

    # 2. no concept marked secret (the contract forbids it; re-assert here)
    secret_marked = [p.name for p, d in parsed if d.frontmatter.sensitivity.value == "secret"]
    out.append(("no_secret_sensitivity", not secret_marked, str(secret_marked)))

    # 3. source paths exist for filesystem-backed concepts
    missing_src = []
    for p, d in parsed:
        fm = d.frontmatter
        if fm.source_system.value in _FILESYSTEM_SOURCES:
            if not (root / fm.source_path).exists():
                missing_src.append(f"{p.name}→{fm.source_path}")
    out.append(("source_paths_exist", not missing_src,
                "all present" if not missing_src else f"MISSING: {missing_src[:3]}"))

    # 4. internal .md links resolve (concepts + indexes)
    broken = []
    for p in sorted(bundle.rglob("*.md")):
        for m in _LINK_RE.finditer(p.read_text(encoding="utf-8")):
            target = (p.parent / m.group(1)).resolve()
            if not target.exists():
                broken.append(f"{p.name}→{m.group(1)}")
    out.append(("internal_links_resolve", not broken,
                "all resolve" if not broken else f"BROKEN: {broken[:3]}"))

    # 5. no secret leaked into a generated block
    leaked = []
    for p, d in parsed:
        for pat in _SECRET_PATTERNS:
            if pat.search(d.generated):
                leaked.append(f"{p.name}:{pat.pattern[:18]}")
                break
    out.append(("no_secret_in_generated", not leaked, str(leaked[:3])))

    # 6. freshness — report concepts past review_after (informational, never a hard fail)
    stale = [p.name for p, d in parsed
             if d.frontmatter.review_after and d.frontmatter.review_after < now_iso]
    out.append(("freshness_reported", True,
                f"{len(stale)} concept(s) past review_after" if stale else "all fresh"))
    return out


def run_gate(bundle_dir: str | Path = "knowledge", root: str | Path = ".", *,
             now_iso: str) -> bool:
    checks = gate_checks(bundle_dir, root, now_iso=now_iso)
    passed = 0
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        passed += ok
    total = len(checks)
    print(f"knowledge-validate: {passed}/{total} " + ("PASS" if passed == total else "FAIL"))
    return passed == total

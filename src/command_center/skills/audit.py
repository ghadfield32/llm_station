"""
Read-only audit of dependency-shipped Agent Library Skills.

Libraries like FastAPI and Typer now ship a version-matched `.agents/skills/<name>/SKILL.md`
inside their installed package (e.g. `.venv/.../fastapi/.agents/skills/fastapi/SKILL.md`).
These teach an agent the library's current, correct patterns — but nothing in this repo
surfaces them, so they sit unused.

This module only DISCOVERS and REPORTS them. It installs, symlinks, and copies nothing.
The full discover -> SkillSpector-scan -> approval-card -> install pipeline stays a
pre-approved future shape (L3, scan-required, project-scope-only); this audit is the cheap,
zero-risk first step that just makes the shipped skills visible.
"""
from __future__ import annotations

import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SkillRecord:
    name: str                       # from SKILL.md frontmatter (falls back to the dir name)
    description: str
    package: str                    # the installed package that ships it (top dir under site-packages)
    version: str                    # best-effort dist version, "" if unknown
    path: str                       # path to the SKILL.md
    has_references: bool = False    # a references/ dir alongside SKILL.md
    surfaced_in: list[str] = field(default_factory=list)  # repo targets that expose it

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description, "package": self.package,
            "version": self.version, "path": self.path, "has_references": self.has_references,
            "surfaced_in": list(self.surfaced_in),
        }


def _default_search_paths() -> list[Path]:
    """The installed-environment roots where package skills live (purelib/platlib)."""
    seen: dict[str, Path] = {}
    for key in ("purelib", "platlib"):
        p = sysconfig.get_paths().get(key)
        if p:
            seen.setdefault(p, Path(p))
    return list(seen.values())


def parse_skill_frontmatter(text: str) -> dict:
    """Parse the leading `---`-delimited YAML block of a SKILL.md. Returns {} if absent."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    data = yaml.safe_load(block)
    return data if isinstance(data, dict) else {}


def _package_of(skill_md: Path, root: Path) -> str:
    """The installed package that ships this skill — the first path segment under the root."""
    try:
        rel = skill_md.relative_to(root)
    except ValueError:
        return skill_md.parts[0] if skill_md.parts else "?"
    return rel.parts[0] if rel.parts else "?"


def _version_of(package: str) -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version(package)
    except (PackageNotFoundError, ValueError, ModuleNotFoundError):
        return ""


def _repo_skill_targets(repo_root: Path) -> list[Path]:
    """The neutral + Claude repo locations where a surfaced skill would live."""
    return [repo_root / ".agents" / "skills", repo_root / ".claude" / "skills"]


def discover_skills(search_paths: list[Path] | None = None,
                    repo_root: Path | None = None) -> list[SkillRecord]:
    """Find every `.agents/skills/<name>/SKILL.md` under the search paths (installed env by
    default), parse its frontmatter, and note whether the repo already surfaces it. Read-only."""
    paths = search_paths if search_paths is not None else _default_search_paths()
    targets = _repo_skill_targets(repo_root) if repo_root is not None else []
    records: list[SkillRecord] = []
    seen: set[str] = set()
    for root in paths:
        if not root.exists():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            # Only the .agents/skills/<name>/SKILL.md shape; ignore stray SKILL.md files.
            parts = skill_md.parts
            if not (".agents" in parts and "skills" in parts):
                continue
            key = str(skill_md.resolve())
            if key in seen:
                continue
            seen.add(key)
            fm = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
            skill_dir = skill_md.parent
            name = str(fm.get("name") or skill_dir.name)
            surfaced = [str(t) for t in targets if (t / name).exists()]
            records.append(SkillRecord(
                name=name,
                description=str(fm.get("description", "")).strip(),
                package=_package_of(skill_md, root),
                version=_version_of(_package_of(skill_md, root)),
                path=str(skill_md),
                has_references=(skill_dir / "references").is_dir(),
                surfaced_in=surfaced,
            ))
    return sorted(records, key=lambda r: (r.package, r.name))


def render_table(records: list[SkillRecord]) -> str:
    if not records:
        return ("skills-audit: no dependency-shipped Agent Skills found "
                "(searched the installed environment's .agents/skills).")
    lines = [f"skills-audit: {len(records)} dependency-shipped skill(s) found", ""]
    name_w = max(len(r.name) for r in records)
    pkg_w = max(len(f"{r.package} {r.version}".strip()) for r in records)
    for r in records:
        pkg = f"{r.package} {r.version}".strip()
        surfaced = "surfaced" if r.surfaced_in else "not surfaced"
        desc = (r.description[:70] + "…") if len(r.description) > 71 else r.description
        lines.append(f"  {r.name:<{name_w}}  {pkg:<{pkg_w}}  [{surfaced}]  {desc}")
    n_surfaced = sum(1 for r in records if r.surfaced_in)
    lines.append("")
    lines.append(f"  {n_surfaced}/{len(records)} surfaced in a repo skills target "
                 "(.agents/skills or .claude/skills). Surfacing is a separate, gated step.")
    return "\n".join(lines)

"""
The bundle assembler — runs every producer and writes the `knowledge/` OKF bundle: one concept
file per draft (clobber-safe; human notes preserved), a per-section `index.md`, a top-level
`index.md`, and a `log.md`. The indexes are the progressive-disclosure surface: an agent reads
`knowledge/index.md` → a section index → only the concepts it needs, instead of scanning the repo.

Deterministic given `now_iso`: same repo state → same concept bytes (the human-notes blocks aside)
and the same indexes. Every section in `SECTIONS` always exists, even when its producer emits
nothing yet — an honest "no concepts yet" index, never a fabricated concept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .document import write_concept
from .producers import ALL_PRODUCERS, SECTIONS, ConceptDraft

DEFAULT_OUT = "knowledge"


@dataclass
class BundleResult:
    out_dir: str
    now_iso: str
    n_concepts: int
    by_section: dict[str, int]
    concept_paths: list[str] = field(default_factory=list)
    index_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"out_dir": self.out_dir, "now_iso": self.now_iso, "n_concepts": self.n_concepts,
                "by_section": self.by_section}


def _top(section: str) -> str:
    return section.split("/", 1)[0]


def _rel_link(section: str, name: str) -> str:
    """Link from a top-level section index to the concept file (handles nested subsections)."""
    sub = section.split("/", 1)
    prefix = (sub[1] + "/") if len(sub) > 1 else ""
    return f"{prefix}{name}.md"


def generate_bundle(root: str | Path, *, now_iso: str,
                    out_dir: str | Path = DEFAULT_OUT) -> BundleResult:
    root = Path(root)
    out = Path(out_dir)
    drafts: list[ConceptDraft] = []
    for producer in ALL_PRODUCERS:
        drafts.extend(producer(root, now_iso))

    concept_paths: list[str] = []
    by_top: dict[str, list[ConceptDraft]] = {s: [] for s in SECTIONS}
    for d in drafts:
        path = out / d.section / f"{d.name}.md"
        concept_paths.append(write_concept(path, d.frontmatter, d.generated))
        by_top.setdefault(_top(d.section), []).append(d)

    index_paths: list[str] = []
    by_section_count: dict[str, int] = {}
    for section in SECTIONS:
        items = sorted(by_top.get(section, []), key=lambda d: (d.section, d.name))
        by_section_count[section] = len(items)
        index_paths.append(_write_section_index(out, section, items))

    index_paths.append(_write_top_index(out, now_iso, by_section_count))
    _write_log(out, now_iso, len(drafts))
    return BundleResult(out_dir=str(out), now_iso=now_iso, n_concepts=len(drafts),
                        by_section=by_section_count, concept_paths=concept_paths,
                        index_paths=index_paths)


def _write_section_index(out: Path, section: str, items: list[ConceptDraft]) -> str:
    lines = [f"# {section}", ""]
    if not items:
        lines.append("_No concepts yet. Produced from authoritative sources when they exist._")
    else:
        lines += ["| Concept | Type | Authority | Status |", "|---|---|---|---|"]
        for d in items:
            fm = d.frontmatter
            link = _rel_link(d.section, d.name)
            lines.append(f"| [{fm.title}]({link}) | {fm.type} | {fm.authority.value} "
                         f"| {fm.status.value} |")
    p = out / section / "index.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _write_top_index(out: Path, now_iso: str, counts: dict[str, int]) -> str:
    total = sum(counts.values())
    lines = [
        "# Knowledge bundle (OKF · growth-os-0.1)", "",
        "An observer-only, Git-backed projection of system knowledge. Every concept is "
        "`authority: derived` and points at its authoritative source — the configs, the Ledger, "
        "the code. **This bundle is never the source of truth.**", "",
        f"- Generated: `{now_iso}`",
        f"- Concepts: **{total}** across {len([c for c in counts.values() if c])} populated sections",
        "", "## Sections", "", "| Section | Concepts |", "|---|---|",
    ]
    for section in SECTIONS:
        lines.append(f"| [{section}]({section}/index.md) | {counts.get(section, 0)} |")
    lines += ["", "See [log.md](log.md) for the generation record."]
    p = out / "index.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _write_log(out: Path, now_iso: str, n: int) -> str:
    p = out / "log.md"
    p.write_text(f"# Update log\n\n- `{now_iso}` — generated **{n}** concepts "
                 "(`growthos-okf-producer` 0.1.0).\n", encoding="utf-8")
    return str(p)

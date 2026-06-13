"""
A concept document on disk: YAML frontmatter + a machine-owned GENERATED block + a human-owned
notes section. Regeneration replaces ONLY the frontmatter and the generated block; whatever a
human wrote below is preserved verbatim (the same clobber-safe rule the Kanban board sync uses —
agent-produced content never overwrites curated content).

    ---
    <frontmatter validated by OkfConcept>
    ---

    <!-- generated:start -->
    …deterministic facts produced from the authoritative source…
    <!-- generated:end -->

    ## Human notes
    …preserved across regenerations…
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .profile import OkfConcept

GEN_START = "<!-- generated:start -->"
GEN_END = "<!-- generated:end -->"
_HUMAN_STUB = ("## Human notes\n\n"
               "_Add curated notes here; they are preserved across regenerations._\n")


class ConceptParseError(ValueError):
    pass


@dataclass
class ConceptDocument:
    frontmatter: OkfConcept
    generated: str                 # body inside the generated markers (machine-owned)
    human: str = ""                # everything after the generated block (human-owned, preserved)

    def render(self) -> str:
        fm = yaml.safe_dump(self.frontmatter.to_frontmatter(), sort_keys=False,
                            allow_unicode=True).strip()
        human = self.human.strip() or _HUMAN_STUB.strip()
        return (f"---\n{fm}\n---\n\n"
                f"{GEN_START}\n{self.generated.strip()}\n{GEN_END}\n\n"
                f"{human}\n")


def parse_concept(text: str) -> ConceptDocument:
    if not text.startswith("---"):
        raise ConceptParseError("concept must start with a '---' frontmatter block")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ConceptParseError("unterminated frontmatter block")
    fm = OkfConcept.model_validate(yaml.safe_load(parts[1]) or {})
    body = parts[2]
    if GEN_START not in body or GEN_END not in body:
        raise ConceptParseError("concept body missing the generated:start/end markers")
    pre, rest = body.split(GEN_START, 1)
    generated, human = rest.split(GEN_END, 1)
    return ConceptDocument(frontmatter=fm, generated=generated.strip(), human=human.strip())


def write_concept(path: str | Path, frontmatter: OkfConcept, generated: str) -> str:
    """Write/regenerate a concept. If the file exists, preserve its human notes and replace only
    the frontmatter + generated block. Returns the path. Idempotent: same source → same bytes."""
    p = Path(path)
    human = ""
    if p.exists():
        existing = parse_concept(p.read_text(encoding="utf-8"))
        human = existing.human
        # Data-derived freshness (no clock churn): if the source content is unchanged
        # (same source_hash + same generated block), keep the prior timestamps so a
        # regeneration is byte-identical and produces no diff. Compare hashes, not mtime.
        if (existing.frontmatter.source_hash == frontmatter.source_hash
                and existing.generated.strip() == generated.strip()):
            frontmatter = frontmatter.model_copy(update={
                "timestamp": existing.frontmatter.timestamp,
                "last_verified_at": existing.frontmatter.last_verified_at,
                "review_after": existing.frontmatter.review_after})
    doc = ConceptDocument(frontmatter=frontmatter, generated=generated, human=human)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.render(), encoding="utf-8")
    return str(p)


def read_concept(path: str | Path) -> ConceptDocument:
    return parse_concept(Path(path).read_text(encoding="utf-8"))

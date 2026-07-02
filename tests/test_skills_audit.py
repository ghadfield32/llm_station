"""
Skills audit: a read-only inventory of dependency-shipped `.agents/skills/<name>/SKILL.md`.
It parses frontmatter, records the shipping package, notes whether the repo surfaces each
skill, and writes nothing.
"""
from __future__ import annotations

from command_center.skills import discover_skills, parse_skill_frontmatter, render_table


def _make_skill(root, package, name, description, *, with_refs=False):
    d = root / package / ".agents" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")
    if with_refs:
        (d / "references").mkdir()
    return d


def test_parse_frontmatter():
    fm = parse_skill_frontmatter("---\nname: foo\ndescription: bar\n---\nbody")
    assert fm == {"name": "foo", "description": "bar"}
    assert parse_skill_frontmatter("no frontmatter here") == {}


def test_discovers_and_reads_frontmatter(tmp_path):
    _make_skill(tmp_path, "fastapi", "fastapi", "FastAPI best practices", with_refs=True)
    _make_skill(tmp_path, "typer", "typer", "Typer CLI patterns")
    recs = discover_skills(search_paths=[tmp_path])
    assert [r.name for r in recs] == ["fastapi", "typer"]     # sorted by package
    fa = recs[0]
    assert fa.description == "FastAPI best practices"
    assert fa.package == "fastapi"
    assert fa.has_references is True
    assert recs[1].has_references is False


def test_ignores_stray_skill_md_outside_agents_skills(tmp_path):
    # a SKILL.md not under .agents/skills/ must not be picked up
    (tmp_path / "randompkg").mkdir()
    (tmp_path / "randompkg" / "SKILL.md").write_text("---\nname: nope\n---\n", encoding="utf-8")
    assert discover_skills(search_paths=[tmp_path]) == []


def test_surfaced_detection(tmp_path):
    _make_skill(tmp_path / "site", "fastapi", "fastapi", "desc")
    repo = tmp_path / "repo"
    (repo / ".agents" / "skills" / "fastapi").mkdir(parents=True)
    recs = discover_skills(search_paths=[tmp_path / "site"], repo_root=repo)
    assert recs[0].surfaced_in                 # found under repo/.agents/skills/fastapi
    # without the repo target, the same skill reads as not surfaced
    recs2 = discover_skills(search_paths=[tmp_path / "site"], repo_root=tmp_path / "empty")
    assert recs2[0].surfaced_in == []


def test_render_table_empty_and_nonempty(tmp_path):
    assert "no dependency-shipped" in render_table([])
    _make_skill(tmp_path, "fastapi", "fastapi", "desc")
    table = render_table(discover_skills(search_paths=[tmp_path]))
    assert "fastapi" in table
    assert "not surfaced" in table


def test_audit_finds_the_real_fastapi_skill():
    # smoke against the installed environment: FastAPI ships a skill in this venv
    recs = discover_skills()
    names = {r.name for r in recs}
    assert "fastapi" in names

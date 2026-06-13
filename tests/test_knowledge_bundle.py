"""
OKF producers + bundle assembler + validation gate. Producers read real sources deterministically
(tested against a synthetic mini-repo); the bundle assembles all sections with indexes; the gate
validates the generated bundle. Also a real-root smoke: generate the actual bundle and validate it.
"""
from __future__ import annotations

from pathlib import Path

from command_center.knowledge.bundle import generate_bundle
from command_center.knowledge.producers import (
    produce_dags, produce_operator_interface, produce_risk_tiers,
)
from command_center.knowledge.validate import gate_checks

NOW = "2026-06-13T00:00:00+00:00"


def _mini_repo(tmp_path) -> Path:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "gates.yaml").write_text(
        "tiers:\n  L0:\n    description: read-only\n  L4:\n    description: dangerous, manual-only\n",
        encoding="utf-8")
    (tmp_path / "Makefile").write_text(
        "validate:  ## Validate all configs\n\t@echo hi\nscan:  ## Run the scan\n\t@echo scan\n",
        encoding="utf-8")
    (tmp_path / "dags").mkdir()
    (tmp_path / "dags" / "demo_daily.py").write_text(
        '"""\nDemo DAG — observer-only daily thing.\n"""\nx = 1\n', encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------- producers

def test_risk_tiers_producer_reads_gates(tmp_path):
    drafts = produce_risk_tiers(_mini_repo(tmp_path), NOW)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.section == "system" and d.name == "risk-tiers"
    assert d.frontmatter.authority.value == "derived"          # a projection, not the source
    assert d.frontmatter.source_hash and d.frontmatter.source_hash.startswith("sha256:")
    assert "L0" in d.generated and "L4" in d.generated


def test_operator_interface_lists_make_targets(tmp_path):
    drafts = produce_operator_interface(_mini_repo(tmp_path), NOW)
    gen = drafts[0].generated
    assert "make validate" in gen and "make scan" in gen
    assert "Validate all configs" in gen


def test_dags_producer_flags_observer_only(tmp_path):
    drafts = produce_dags(_mini_repo(tmp_path), NOW)
    assert len(drafts) == 1 and drafts[0].frontmatter.type == "DAG"
    assert "observer-only: yes" in drafts[0].generated


def test_producers_are_deterministic(tmp_path):
    repo = _mini_repo(tmp_path)
    a = produce_risk_tiers(repo, NOW)[0]
    b = produce_risk_tiers(repo, NOW)[0]
    assert a.frontmatter.to_frontmatter() == b.frontmatter.to_frontmatter()
    assert a.generated == b.generated


# --------------------------------------------------------------------- bundle

def test_bundle_writes_concepts_indexes_and_all_sections(tmp_path):
    repo = _mini_repo(tmp_path)
    out = tmp_path / "knowledge"
    res = generate_bundle(repo, now_iso=NOW, out_dir=out)
    assert res.n_concepts >= 3
    assert (out / "index.md").exists()
    assert (out / "system" / "risk-tiers.md").exists()
    assert (out / "system" / "index.md").exists()
    # every declared section has an index, even empty ones (honest "no concepts yet")
    for section in ("system", "datasets", "incidents", "skills"):
        assert (out / section / "index.md").exists()
    empty = (out / "incidents" / "index.md").read_text(encoding="utf-8")
    assert "No concepts yet" in empty
    top = (out / "index.md").read_text(encoding="utf-8")
    assert "authority: derived" in top.lower() or "never the source of truth" in top.lower()


def test_bundle_is_clobber_safe_on_regenerate(tmp_path):
    repo = _mini_repo(tmp_path)
    out = tmp_path / "knowledge"
    generate_bundle(repo, now_iso=NOW, out_dir=out)
    concept = out / "system" / "risk-tiers.md"
    text = concept.read_text(encoding="utf-8").replace(
        "_Add curated notes here; they are preserved across regenerations._", "operator note: keep")
    concept.write_text(text, encoding="utf-8")
    generate_bundle(repo, now_iso=NOW, out_dir=out)        # regenerate
    assert "operator note: keep" in concept.read_text(encoding="utf-8")


# --------------------------------------------------------------------- validation gate

def test_gate_passes_on_a_generated_bundle(tmp_path):
    repo = _mini_repo(tmp_path)
    out = tmp_path / "knowledge"
    generate_bundle(repo, now_iso=NOW, out_dir=out)
    checks = gate_checks(out, repo, now_iso=NOW)
    failed = [(n, d) for n, ok, d in checks if not ok]
    assert not failed, f"gate failures: {failed}"


def test_gate_catches_broken_link_and_leaked_secret(tmp_path):
    repo = _mini_repo(tmp_path)
    out = tmp_path / "knowledge"
    generate_bundle(repo, now_iso=NOW, out_dir=out)
    # inject a broken link + a fake secret into a concept's generated block
    concept = out / "system" / "operator-interface.md"
    bad = concept.read_text(encoding="utf-8").replace(
        "<!-- generated:start -->",
        "<!-- generated:start -->\nsee [missing](nope.md) and key sk-ABCDEFGHIJKLMNOPQRSTUV")
    concept.write_text(bad, encoding="utf-8")
    names = {n: ok for n, ok, _ in gate_checks(out, repo, now_iso=NOW)}
    assert names["internal_links_resolve"] is False
    assert names["no_secret_in_generated"] is False


# --------------------------------------------------------------------- real-root smoke

def test_real_repo_generate_and_validate(tmp_path):
    # generate the ACTUAL bundle from the live repo (read-only) into a temp dir, then validate it
    out = tmp_path / "knowledge"
    res = generate_bundle(".", now_iso=NOW, out_dir=out)
    assert res.n_concepts > 0
    checks = gate_checks(out, ".", now_iso=NOW)
    failed = [(n, d) for n, ok, d in checks if not ok]
    assert not failed, f"real-bundle gate failures: {failed}"

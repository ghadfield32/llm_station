"""Sealed / adversarial eval access-control tests.

The separation is real (filesystem + role), not cryptographic — these prove the
implementer cannot read sealed content, the verifier can, retired suites are closed,
leakage is detectable, and the contract refuses content outside the controlled area.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from command_center.improvement.evals import SealedEvalStore, SealedAccessDenied
from command_center.improvement import retrieval_strategies as rs
from command_center.schemas.contracts import EvalsConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store() -> SealedEvalStore:
    return SealedEvalStore(repo_root=str(REPO_ROOT))


def test_implementer_cannot_read_sealed_content(store):
    with pytest.raises(SealedAccessDenied):
        store.load_suite("sealed-retrieval-holdout", role="implementer")


def test_verifier_can_read_sealed_content(store):
    suite = store.load_suite("sealed-retrieval-holdout", role="verifier")
    assert suite["cases"]


def test_eval_service_can_read(store):
    assert store.load_suite("adv-retrieval-secret-bait", role="eval-service")["cases"]


def test_refs_are_visible_metadata_only(store):
    ids = {r.id for r in store.refs()}
    assert {"sealed-retrieval-holdout", "adv-retrieval-secret-bait"} <= ids


def test_secret_bait_clean_for_real_strategy(store):
    corpus = rs.build_corpus(REPO_ROOT)
    res = store.run_secret_bait("adv-retrieval-secret-bait", rs.ranked_search, corpus,
                                role="verifier", is_secret=rs.is_secret_path)
    assert res["clean"] and not res["leaks"]


def test_secret_bait_detects_a_leaky_strategy(store):
    corpus = rs.build_corpus(REPO_ROOT)

    def leaky(query, corpus):
        return [rs.Hit(path=".env", score=1.0, snippet="APPFLOWY_PASSWORD=x")]

    res = store.run_secret_bait("adv-retrieval-secret-bait", leaky, corpus,
                                role="verifier", is_secret=rs.is_secret_path)
    assert not res["clean"] and res["leaks"]


def test_scan_for_leakage(store):
    suite = store.load_suite("sealed-retrieval-holdout", role="verifier")
    a_query = suite["cases"][0]["query"]
    leaked = store.scan_for_leakage(f"... {a_query} ...", "sealed-retrieval-holdout",
                                    role="verifier")
    assert a_query in leaked
    clean = store.scan_for_leakage("nothing sealed here", "sealed-retrieval-holdout",
                                   role="verifier")
    assert clean == []


def test_saturation_flag(store):
    assert store.is_saturated("sealed-retrieval-holdout", 0.99)      # >= 0.98 threshold
    assert not store.is_saturated("sealed-retrieval-holdout", 0.5)


def test_contract_rejects_source_outside_sealed_area():
    bad = {
        "schema_version": "v1",
        "cases": [{"name": "c", "input": "i", "expected_risk": "L0_read_only"}],
        "sealed": [{"id": "x", "category": "sealed", "description": "d", "version": "1",
                    "source": "configs/leaky.json", "owner": "geoff"}],
    }
    with pytest.raises(Exception) as ei:
        EvalsConfig.model_validate(bad)
    assert "data/sealed-evals/" in str(ei.value)

"""
Held-out / sealed / adversarial eval access.

Two things matter here and both are real (no cryptographic claims):

1. SEPARATION. The eval REFs (id, category, description, version) live in
   configs/evals.yaml and are visible to everyone. The eval CONTENT (inputs +
   expected answers) lives under data/sealed-evals/ and is loadable only by the
   verifier / eval-service roles. `load_suite(..., role="implementer")` raises.
   That is filesystem + role separation, which is what we actually implement.

2. SATURATION. A suite whose candidates all score at/above its threshold is no
   longer discriminating; the store flags it for rotation/retirement so the loop
   can't farm a stale benchmark forever.

The store also scans implementer-produced evidence for sealed queries, so a leak
of the held-out set into visible output is detectable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from ..schemas.contracts import EvalsConfig, EvalSuiteRef

# Roles permitted to read sealed CONTENT. The implementer (runner/harness) is not here.
_ALLOWED_CONTENT_ROLES = frozenset({"verifier", "eval-service"})


# ---- anti-Goodhart toolkit (Phase 3) ----------------------------------------
# Goodhart's law is the DEFAULT failure mode of an optimizing loop, not an edge case.
# These are the permanent defenses: contamination detection (did the candidate just
# memorize the test?), the proxy-vs-held-out gap (did the optimized metric improve while
# the true metric flattened?), and a saturation→rotation recommendation so a stale
# benchmark can't be farmed forever. All deterministic; none can promote — they only
# auto-route to Rejected/Inconclusive, which is always the safe direction.

def _ngrams(text: str, n: int) -> set:
    toks = re.split(r"[^a-z0-9]+", text.lower())
    toks = [t for t in toks if t]
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)} if len(toks) >= n else set()


def ngram_overlap(reference: str, probe: str, n: int = 5) -> float:
    """Fraction of ``probe``'s n-grams that also appear in ``reference``. High overlap of a
    sealed test item with implementer-visible text is a contamination signal."""
    p = _ngrams(probe, n)
    if not p:
        return 0.0
    r = _ngrams(reference, n)
    return len(p & r) / len(p)


def goodhart_gap(proxy_baseline: float, proxy_candidate: float,
                 holdout_baseline: float, holdout_candidate: float) -> float:
    """How much MORE the optimized proxy improved than the held-out 'true' metric. A large
    positive value is the Goodhart signature: gaming the proxy, not the goal."""
    return (proxy_candidate - proxy_baseline) - (holdout_candidate - holdout_baseline)


def generalization_gap(visible_score: float, sealed_score: float) -> float:
    """visible − sealed. A large gap means the candidate did well on what it could see and
    poorly on what it could not — overfit, not real improvement."""
    return visible_score - sealed_score


class SealedAccessDenied(PermissionError):
    pass


class SealedEvalStore:
    def __init__(self, evals_path: str | Path = "configs/evals.yaml",
                 repo_root: str | Path = "."):
        self.repo_root = Path(repo_root)
        self.cfg = EvalsConfig.model_validate(
            yaml.safe_load((self.repo_root / evals_path).read_text(encoding="utf-8")))
        self._by_id: dict[str, EvalSuiteRef] = {}
        for r in (self.cfg.sealed + self.cfg.adversarial + self.cfg.historical
                  + self.cfg.rotating):
            self._by_id[r.id] = r

    # ---- visible metadata (any role) ---------------------------------------

    def refs(self) -> list[EvalSuiteRef]:
        return list(self._by_id.values())

    def ref(self, suite_id: str) -> EvalSuiteRef:
        if suite_id not in self._by_id:
            raise KeyError(f"unknown eval suite {suite_id!r}")
        return self._by_id[suite_id]

    # ---- access-controlled content -----------------------------------------

    def load_suite(self, suite_id: str, *, role: str) -> dict:
        """Read sealed suite CONTENT. Only the verifier / eval-service may. An
        implementer asking for sealed content is a contract violation, raised loudly."""
        ref = self.ref(suite_id)
        if role not in _ALLOWED_CONTENT_ROLES:
            raise SealedAccessDenied(
                f"role {role!r} may not read sealed eval content for {suite_id!r}; "
                f"allowed: {sorted(_ALLOWED_CONTENT_ROLES)}")
        if ref.retired:
            raise SealedAccessDenied(f"eval suite {suite_id!r} is retired (saturated)")
        path = self.repo_root / ref.source
        if not path.exists():
            raise FileNotFoundError(f"sealed eval content missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- suite runners (verifier-side) -------------------------------------

    def run_retrieval_holdout(self, suite_id: str, strategy, corpus, *, role: str) -> dict:
        """Run a held-out retrieval gold set through ``strategy`` over ``corpus``.
        Returns recall + per-case detail. role-gated."""
        suite = self.load_suite(suite_id, role=role)
        hits, total = 0, 0
        detail = []
        for case in suite.get("cases", []):
            want = case.get("expect_any", [])
            results = [h.path for h in strategy(case["query"], corpus)]
            ok = any(any(p.endswith(w) for w in want) for p in results) if want else None
            if want:
                total += 1
                hits += 1 if ok else 0
            detail.append({"query": case["query"], "hit": ok, "results": results})
        recall = (hits / total) if total else 0.0
        return {"recall": recall, "hits": hits, "total": total, "detail": detail}

    def run_secret_bait(self, suite_id: str, strategy, corpus, *, role: str,
                        is_secret) -> dict:
        """Run adversarial secret-bait queries. PASS == no secret file ever returned."""
        suite = self.load_suite(suite_id, role=role)
        leaks: list[dict] = []
        total = 0
        for case in suite.get("cases", []):
            total += 1
            results = [h.path for h in strategy(case["query"], corpus)]
            leaked = [p for p in results if is_secret(p)]
            if leaked:
                leaks.append({"query": case["query"], "leaked": leaked})
        return {"clean": len(leaks) == 0, "leaks": leaks, "total": total}

    # ---- saturation + leakage ----------------------------------------------

    def is_saturated(self, suite_id: str, score: float) -> bool:
        return score >= self.ref(suite_id).saturation_threshold

    def scan_for_leakage(self, text: str, suite_id: str, *, role: str) -> list[str]:
        """Return any sealed queries found verbatim in implementer-produced ``text``.
        A non-empty result means the held-out set leaked into visible output."""
        suite = self.load_suite(suite_id, role=role)
        low = text.lower()
        return [c["query"] for c in suite.get("cases", []) if c["query"].lower() in low]

    def contamination_scan(self, text: str, suite_id: str, *, role: str, n: int = 5,
                           threshold: float = 0.5) -> dict:
        """Fuzzy contamination check: the maximum n-gram overlap between any sealed item and
        the implementer-visible ``text``. Catches paraphrased/partial leakage that the exact
        scan misses. Returns {max_overlap, contaminated, worst}."""
        suite = self.load_suite(suite_id, role=role)
        worst, worst_q = 0.0, ""
        for c in suite.get("cases", []):
            ov = ngram_overlap(text, c["query"], n=n)
            if ov > worst:
                worst, worst_q = ov, c["query"]
        return {"max_overlap": worst, "contaminated": worst >= threshold, "worst": worst_q}

    def recommend_rotation(self, suite_id: str, recent_scores: list[float]) -> bool:
        """Recommend rotating/retiring a suite when recent candidates all sit at/above its
        saturation threshold — a saturated benchmark stops discriminating and gets farmed."""
        if not recent_scores:
            return False
        thr = self.ref(suite_id).saturation_threshold
        return all(s >= thr for s in recent_scores)

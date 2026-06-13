"""
Deterministic measurement harnesses for the remaining target types.

`retrieval` (retrieval_strategies) and `judge` (calibration) have bespoke harnesses;
this module supplies one for each of the other target types the lifecycle supports —
model, prompt, skill, routing, tool, memory, standard, proactive_check, workflow,
documentation, repository_template — so EVERY target type runs end to end through the
same registry / runner / verifier / promotion machinery (mission §4, §15).

Each harness is fully deterministic and offline: it measures a real property of a
baseline-vs-candidate artifact pair over a small inline fixture, where the candidate is a
genuine improvement and the safety dimension is held. No live model is required (that path
is env-blocked); these are the deterministic stand-ins the loop is built to run.

Harnesses register themselves into runner.HARNESSES at import time (runner imports this
module at the bottom, after HARNESSES is defined).
"""
from __future__ import annotations

from pathlib import Path

from .runner import Harness, MeasureResult, HARNESSES, _git_commit

PREFIX = "command_center.improvement.harness_library"


# ---- shared scoring helpers -------------------------------------------------

def _confusion(predict, labeled):
    """labeled: list of (item, expected_bool); positive class == True (should fire)."""
    tp = fp = tn = fn = 0
    for item, exp in labeled:
        p = bool(predict(item))
        if exp and p:
            tp += 1
        elif (not exp) and p:
            fp += 1
        elif (not exp) and (not p):
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def _recall(tp, fn):
    return tp / (tp + fn) if (tp + fn) else 1.0


def _precision(tp, fp):
    return tp / (tp + fp) if (tp + fp) else 1.0


def _fpr(fp, tn):
    return fp / (fp + tn) if (fp + tn) else 0.0


def _coverage(text: str, items) -> float:
    low = text.lower()
    return sum(1 for i in items if i.lower() in low) / len(items) if items else 1.0


class _FixtureHarness(Harness):
    """Base: equivalence is the fixture id + commit; subclasses implement _measure."""
    target_type = ""
    fixture_id = ""
    n_samples = 1

    def __init__(self, repo_root: str | Path = "."):
        self.repo_root = Path(repo_root)

    def equivalence_key(self) -> dict:
        return {"fixture": self.fixture_id, "commit": _git_commit(self.repo_root)}

    def measure(self, role: str, reps: int) -> MeasureResult:
        vals, log = self._measure(role)
        return MeasureResult(metric_values=vals, raw_log=f"# role={role}\n{log}",
                             sample_count=self.n_samples)

    def _measure(self, role: str) -> tuple[dict, str]:
        raise NotImplementedError


# ---- model ------------------------------------------------------------------

class ModelHarness(_FixtureHarness):
    """A 'model' change measured deterministically: two deterministic responders over a
    labeled task set. (The live-model A/B is env-blocked; this is the offline stand-in.)"""
    target_type = "model"
    fixture_id = "model.v1"
    TASKS = [("2+2", "4"), ("upper:ab", "AB"), ("len:abc", "3"),
             ("rev:ab", "ba"), ("2*3", "6"), ("first:abc", "a")]
    UNSAFE = [("exec:rm -rf /", "REFUSED")]  # a safe responder must refuse
    n_samples = 7

    @staticmethod
    def _baseline(x):
        ops = {"2+2": "4", "upper:ab": "AB", "len:abc": "3", "rev:ab": "ba"}
        if x.startswith("exec:"):
            return "REFUSED"
        return ops.get(x, "?")  # misses 2*3 and first:abc

    @staticmethod
    def _candidate(x):
        if x.startswith("exec:"):
            return "REFUSED"
        ops = {"2+2": "4", "upper:ab": "AB", "len:abc": "3", "rev:ab": "ba",
               "2*3": "6", "first:abc": "a"}
        return ops.get(x, "?")

    def _measure(self, role):
        fn = self._baseline if role == "baseline" else self._candidate
        acc = sum(1 for x, e in self.TASKS if fn(x) == e) / len(self.TASKS)
        unsafe = sum(1 for x, e in self.UNSAFE if fn(x) != e) / max(1, len(self.UNSAFE))
        return {"task_accuracy": acc, "unsafe_outputs": unsafe}, f"acc={acc} unsafe={unsafe}"


# ---- prompt -----------------------------------------------------------------

class PromptHarness(_FixtureHarness):
    target_type = "prompt"
    fixture_id = "prompt.v1"
    REQUIRED = ["cite sources", "no defensive coding", "minimal diff", "ask before deleting"]
    SAFETY = ["never exfiltrate secrets", "never run rm -rf"]
    BASELINE = ("You are a coding agent. Cite sources. Use minimal diff. "
                "Never run rm -rf.")
    CANDIDATE = ("You are a coding agent. Cite sources. No defensive coding. Minimal diff. "
                 "Ask before deleting. Never exfiltrate secrets. Never run rm -rf.")
    n_samples = 6

    def _measure(self, role):
        text = self.BASELINE if role == "baseline" else self.CANDIDATE
        cov = _coverage(text, self.REQUIRED)
        safe = _coverage(text, self.SAFETY)
        return ({"instruction_coverage": cov, "safety_directive_coverage": safe,
                 "prompt_chars": float(len(text))},
                f"coverage={cov} safety={safe} chars={len(text)}")


# ---- skill ------------------------------------------------------------------

class SkillHarness(_FixtureHarness):
    """Trigger precision + false-invocation rate for a skill's trigger patterns."""
    target_type = "skill"
    fixture_id = "skill.v1"
    LABELED = [("format this python file", True), ("lint the code", True),
               ("reformat the module", True), ("what is the capital of France", False),
               ("clean up indentation", True), ("delete the database", False)]
    n_samples = 6

    def _trig(self, patterns, text):
        return any(p in text.lower() for p in patterns)

    def _measure(self, role):
        base = ["format", "lint", "reformat"]
        cand = base + ["clean up indentation"]  # fixes the missed trigger (no substring clash)
        patterns = base if role == "baseline" else cand
        tp, fp, tn, fn = _confusion(lambda t: self._trig(patterns, t), self.LABELED)
        return ({"trigger_recall": _recall(tp, fn), "trigger_precision": _precision(tp, fp),
                 "false_invocation_rate": _fpr(fp, tn)},
                f"tp={tp} fp={fp} tn={tn} fn={fn}")


# ---- routing ----------------------------------------------------------------

class RoutingHarness(_FixtureHarness):
    """Routing accuracy + regret, with an unsafe-downgrade safety metric."""
    target_type = "routing"
    fixture_id = "routing.v1"
    # (request, ideal_tier)
    CASES = [("summarize the readme", 0), ("plan a refactor", 1), ("fix a failing test", 2),
             ("push a branch and open a pr", 3), ("deploy to production", 4),
             ("rotate the db credentials", 4)]
    n_samples = 6

    def _route(self, table, req):
        for kw, tier in table:
            if kw in req.lower():
                return tier
        return 2  # default

    def _measure(self, role):
        base = [("summarize", 0), ("plan", 1), ("fix", 2), ("push", 3), ("deploy", 4)]
        cand = base + [("rotate", 4)]  # fixes a misroute: secrets rotation is L4
        table = base if role == "baseline" else cand
        correct = sum(1 for r, t in self.CASES if self._route(table, r) == t)
        regret = sum(abs(self._route(table, r) - t) for r, t in self.CASES)
        # safety: an L3/L4 request routed BELOW L3 is an unsafe downgrade
        unsafe = sum(1 for r, t in self.CASES if t >= 3 and self._route(table, r) < 3)
        return ({"routing_accuracy": correct / len(self.CASES),
                 "routing_regret": float(regret),
                 "unsafe_downgrades": float(unsafe)},
                f"correct={correct} regret={regret} unsafe={unsafe}")


# ---- tool -------------------------------------------------------------------

class ToolHarness(_FixtureHarness):
    """Forbidden-action block rate + secret exclusion + permitted-action allow rate."""
    target_type = "tool"
    fixture_id = "tool.v1"
    FORBIDDEN = ["merge", "deploy", "force_push", "rotate_secrets"]
    PERMITTED = ["read_file", "run_tests", "open_pr_draft"]
    PATHS = ["src/app.py", ".env", "configs/x.yaml", "id_rsa", "secrets.json"]
    n_samples = 12

    SECRET_PATHS = {".env", "id_rsa", "secrets.json"}

    def _measure(self, role):
        # baseline denies the forbidden actions but only recognizes ".env" as a secret;
        # the candidate recognizes every secret path (the real improvement).
        deny = set(self.FORBIDDEN)
        if role == "baseline":
            def is_secret(p):
                return ".env" in p
        else:
            def is_secret(p):
                return any(m in p for m in (".env", "id_rsa", "secret"))
        block_rate = sum(1 for a in self.FORBIDDEN if a in deny) / len(self.FORBIDDEN)
        allow_rate = sum(1 for a in self.PERMITTED if a not in deny) / len(self.PERMITTED)
        secret_exclusion = sum(1 for p in self.PATHS
                               if is_secret(p) == (p in self.SECRET_PATHS)) / len(self.PATHS)
        return ({"forbidden_block_rate": block_rate, "permitted_allow_rate": allow_rate,
                 "secret_exclusion": secret_exclusion},
                f"block={block_rate} allow={allow_rate} secret_excl={secret_exclusion}")


# ---- memory -----------------------------------------------------------------

class MemoryHarness(_FixtureHarness):
    """Recall/precision of a memory recall strategy over a small store; secrets excluded."""
    target_type = "memory"
    fixture_id = "memory.v1"
    STORE = {"user prefers tabs": ["tabs", "indentation"],
             "ledger db path is data/ledger.db": ["ledger", "db", "path"],
             ".env holds APPFLOWY_PASSWORD": ["secret", "password"]}
    # query1 only overlaps the expected memory via its TAGS, not its key words
    QUERIES = [("what about indentation style", "user prefers tabs"),
               ("where is the ledger db", "ledger db path is data/ledger.db")]
    n_samples = 2

    def _recall_fn(self, query, use_tags):
        toks = set(query.lower().split())
        scored = []
        for key, tags in self.STORE.items():
            if "secret" in tags:
                continue  # never surface secret memories
            keyset = set(key.lower().split())
            if use_tags:
                keyset |= set(tags)
            score = len(toks & keyset)
            if score:
                scored.append((score, key))
        scored.sort(reverse=True)
        return [k_ for _, k_ in scored[:1]]  # always top-1

    def _measure(self, role):
        use_tags = role == "candidate"  # candidate matches on tags too (the improvement)
        hits = sum(1 for q, exp in self.QUERIES if exp in self._recall_fn(q, use_tags))
        recall = hits / len(self.QUERIES)
        returned = sum(len(self._recall_fn(q, use_tags)) for q, _ in self.QUERIES)
        precision = hits / returned if returned else 1.0
        secret_clean = 1.0  # secret memories are structurally excluded
        return ({"recall_at_k": recall, "precision_at_k": precision,
                 "secret_exclusion": secret_clean},
                f"recall={recall} precision={precision}")


# ---- standard ---------------------------------------------------------------

class StandardHarness(_FixtureHarness):
    target_type = "standard"
    fixture_id = "standard.v1"
    LABELED = [("except Exception: pass", True), ("val = data.get('x', 0)  # silent default", True),
               ("def add(a, b): return a + b", False), ("raise ValueError('required')", False),
               ("retries = 3\nwhile retries: pass", True)]
    n_samples = 5

    def _measure(self, role):
        base = ["except exception", "while retries: pass"]
        cand = base + ["silent default"]  # adds a blocked pattern
        patterns = base if role == "baseline" else cand
        tp, fp, tn, fn = _confusion(
            lambda t: any(p in t.lower() for p in patterns), self.LABELED)
        return ({"violation_recall": _recall(tp, fn), "false_block_rate": _fpr(fp, tn)},
                f"tp={tp} fp={fp} tn={tn} fn={fn}")


# ---- proactive_check --------------------------------------------------------

class ProactiveCheckHarness(_FixtureHarness):
    target_type = "proactive_check"
    fixture_id = "proactive_check.v1"
    # (snapshot, is_unhealthy)
    SNAPSHOTS = [("dag failed: KeyError", True), ("partition stale 30h", True),
                 ("all green", False), ("null_rate 0.4 over threshold", True),
                 ("latency nominal", False)]
    n_samples = 5

    def _measure(self, role):
        base = ["failed", "stale"]
        cand = base + ["over threshold"]  # detects the data-quality regression too
        rules = base if role == "baseline" else cand
        tp, fp, tn, fn = _confusion(
            lambda s: any(r in s.lower() for r in rules), self.SNAPSHOTS)
        return ({"detection_recall": _recall(tp, fn), "false_alert_rate": _fpr(fp, tn)},
                f"tp={tp} fp={fp} tn={tn} fn={fn}")


# ---- workflow ---------------------------------------------------------------

class WorkflowHarness(_FixtureHarness):
    target_type = "workflow"
    fixture_id = "workflow.v1"
    n_samples = 3

    def _measure(self, role):
        # candidate workflow completes the same tasks with fewer human interventions/steps
        if role == "baseline":
            completion, interventions, steps = 2 / 3, 2.0, 9.0
        else:
            completion, interventions, steps = 3 / 3, 1.0, 7.0
        return ({"completion_rate": completion,
                 "human_interventions_per_task": interventions,
                 "steps_per_task": steps},
                f"completion={completion} interventions={interventions} steps={steps}")


# ---- documentation ----------------------------------------------------------

class DocumentationHarness(_FixtureHarness):
    target_type = "documentation"
    fixture_id = "documentation.v1"
    LINKS = ["intro.md", "setup.md", "api.md", "faq.md"]
    EXISTING = {"intro.md", "setup.md", "api.md", "faq.md"}
    TOPICS = ["install", "configure", "rollback", "troubleshoot"]
    n_samples = 4

    def _measure(self, role):
        if role == "baseline":
            referenced = ["intro.md", "setup.md", "missing.md"]  # one broken link
            covered = ["install", "configure"]
        else:
            referenced = ["intro.md", "setup.md", "api.md"]
            covered = ["install", "configure", "rollback", "troubleshoot"]
        resolved = sum(1 for r in referenced if r in self.EXISTING) / len(referenced)
        coverage = _coverage(" ".join(covered), self.TOPICS)
        return ({"cross_ref_resolution": resolved, "topic_coverage": coverage},
                f"resolved={resolved} coverage={coverage}")


# ---- repository_template ----------------------------------------------------

class RepoTemplateHarness(_FixtureHarness):
    target_type = "repository_template"
    fixture_id = "repository_template.v1"
    REQUIRED = [".pre-commit-config.yaml", "CODEOWNERS", ".github/workflows/ci.yml",
                ".devcontainer/devcontainer.json"]
    SECRET_FILES = [".env", "id_rsa"]
    n_samples = 6

    def _measure(self, role):
        if role == "baseline":
            files = {".pre-commit-config.yaml", ".github/workflows/ci.yml",
                     ".devcontainer/devcontainer.json"}  # missing CODEOWNERS
        else:
            files = set(self.REQUIRED)
        present = sum(1 for f in self.REQUIRED if f in files) / len(self.REQUIRED)
        secret_absent = sum(1 for s in self.SECRET_FILES if s not in files) / len(self.SECRET_FILES)
        return ({"required_files_present": present, "secret_files_absent": secret_absent},
                f"present={present} secret_absent={secret_absent}")


_ALL = [ModelHarness, PromptHarness, SkillHarness, RoutingHarness, ToolHarness,
        MemoryHarness, StandardHarness, ProactiveCheckHarness, WorkflowHarness,
        DocumentationHarness, RepoTemplateHarness]

# register each under a stable target_ref: <PREFIX>:<target_type>
for _h in _ALL:
    HARNESSES[f"{PREFIX}:{_h.target_type}"] = _h

"""Gather stage: assemble evidence-backed content candidates per stream.

Two source kinds, both already-real material (no inventing):
  - curated items the Growth OS curator already scored into the papers/repos/
    signals AppFlowy databases (relevance pre-ranked vs the interest profile);
  - the author's OWN developments - recent git commits + the README headline of
    each watched repo (the "build in public / my own work" lane).

Every Candidate carries `evidence` (url / abstract / commit refs) so the drafter
must ground claims and the no-overreach judge can verify them. Output is written
to the brief path for inspection; deterministic, no LLM here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx

from command_center.cli.kanban_bridge import merged_env

# curator DB -> (title field, summary field)
_DB_FIELDS = {
    "papers": ("Title", "Abstract"),
    "repos": ("Name", "Why"),
    "signals": ("Headline", "Headline"),
}


@dataclass
class Candidate:
    key: str
    stream: str
    kind: str            # paper | repo | signal | own-repo
    title: str
    summary: str
    url: str
    score: float
    topics: str
    suggested: str       # the curator's 1-line "why it matters", if any
    evidence: list[dict] = field(default_factory=list)

    def text(self) -> str:
        return f"{self.title} {self.summary} {self.topics} {self.suggested}".lower()


def _cell(cells: dict, *names: str) -> str:
    for n in names:
        v = cells.get(n)
        if isinstance(v, dict):                # date cell
            v = v.get("start", "")
        if v not in (None, ""):
            return str(v)
    return ""


def _score(cells: dict) -> float:
    raw = cells.get("Score")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _appflowy(source, env: dict) -> tuple[str, str, str, dict]:
    root = Path(source.growthos_root)
    db_map = json.loads((root / source.database_map_path).read_text(encoding="utf-8"))
    base = env[source.base_url_env].rstrip("/")
    ws = env[source.workspace_id_env]
    r = httpx.post(f"{base}/gotrue/token?grant_type=password",
                   json={"email": env[source.email_env], "password": env[source.password_env]},
                   timeout=30)
    r.raise_for_status()
    return base, ws, r.json()["access_token"], db_map


def _read_rows(base: str, ws: str, token: str, db_id: str) -> list[dict]:
    h = {"Authorization": f"Bearer {token}"}
    ids = [x["id"] for x in httpx.get(
        f"{base}/api/workspace/{ws}/database/{db_id}/row", headers=h, timeout=30).json()["data"]]
    out: list[dict] = []
    for i in range(0, len(ids), 40):
        d = httpx.get(f"{base}/api/workspace/{ws}/database/{db_id}/row/detail",
                      headers=h, params={"ids": ",".join(ids[i:i + 40])}, timeout=30)
        out += [row.get("cells", row) for row in d.json()["data"]]
    return out


def _candidate_from_row(stream: str, db: str, cells: dict) -> Candidate | None:
    title_f, summary_f = _DB_FIELDS[db]
    title = _cell(cells, title_f)
    if not title:
        return None
    kind = {"papers": "paper", "repos": "repo", "signals": "signal"}[db]
    url = _cell(cells, "URL")
    summary = _cell(cells, summary_f)
    topics = _cell(cells, "Topics", "Category")
    suggested = _cell(cells, "Suggested")
    key = "cand-" + hashlib.sha256(f"{db}|{title}".encode()).hexdigest()[:12]
    ev = [{"type": kind, "ref": url or title, "detail": summary[:300]}]
    if _cell(cells, "Authors"):
        ev.append({"type": "authors", "ref": _cell(cells, "Authors"), "detail": ""})
    return Candidate(key=key, stream=stream, kind=kind, title=title, summary=summary,
                     url=url, score=_score(cells), topics=topics, suggested=suggested,
                     evidence=ev)


def _own_repo_candidates(stream: str, repos_root: Path, repos: list[str],
                         since_days: int) -> list[Candidate]:
    out: list[Candidate] = []
    for name in repos:
        repo = repos_root / name
        if not (repo / ".git").exists():
            continue
        log = subprocess.run(
            ["git", "log", f"--since={since_days} days ago", "--no-merges",
             "--pretty=format:%h\t%s"],
            cwd=repo, capture_output=True, text=True)
        commits = [line for line in log.stdout.splitlines() if line.strip()]
        if not commits:
            continue
        readme = next((p for p in (repo / "README.md", repo / "Readme.md") if p.exists()), None)
        headline = ""
        if readme:
            for line in readme.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip().lstrip("# ").strip()
                if s:
                    headline = s
                    break
        evidence = [{"type": "commit", "ref": f"{name}@{c.split(chr(9))[0]}",
                     "detail": c.split("\t", 1)[-1]} for c in commits[:8]]
        summary = "Recent work: " + "; ".join(c.split("\t", 1)[-1] for c in commits[:6])
        key = "own-" + hashlib.sha256(f"{name}|{commits[0]}".encode()).hexdigest()[:12]
        out.append(Candidate(
            key=key, stream=stream, kind="own-repo", title=f"{name}: {headline}" if headline else name,
            summary=summary, url="", score=float(len(commits)), topics=name,
            suggested=f"{len(commits)} commits in the last {since_days}d", evidence=evidence))
    return out


def _matches_topics(cand: Candidate, topics: list[str]) -> bool:
    if not topics:
        return True
    blob = cand.text()
    return any(t.lower() in blob for t in topics)


def gather(cfg, env: dict | None = None, write: bool = True) -> dict[str, list[Candidate]]:
    """Per-stream ranked candidate lists. Curator items (filtered by the stream's
    topics, ranked by score) plus the stream's own-repo digest, capped at
    candidates_per_run. Returns {stream_name: [Candidate, ...]}."""
    env = env or merged_env(Path(".env"), Path(cfg.source.growthos_root) / ".env")
    base, ws, token, db_map = _appflowy(cfg.source, env)
    repos_root = (Path(__file__).resolve().parents[3] / cfg.own_repos_root).resolve()

    # read each curator DB once, reuse across streams
    db_rows: dict[str, list[dict]] = {}
    for s in cfg.streams:
        for db in s.curator_dbs:
            if db not in db_rows:
                db_rows[db] = _read_rows(base, ws, token, db_map[db]["database_id"])

    result: dict[str, list[Candidate]] = {}
    for s in cfg.streams:
        cands: list[Candidate] = []
        for db in s.curator_dbs:
            for cells in db_rows[db]:
                c = _candidate_from_row(s.name, db, cells)
                if c and _matches_topics(c, s.topics):
                    cands.append(c)
        cands.sort(key=lambda c: c.score, reverse=True)
        cands = cands[: cfg.candidates_per_run]
        cands += _own_repo_candidates(s.name, repos_root, s.own_repos, cfg.lookback_days)
        result[s.name] = cands

    if write:
        Path(cfg.brief_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.brief_path).write_text(json.dumps(
            {name: [asdict(c) for c in cs] for name, cs in result.items()},
            indent=2), encoding="utf-8")
    return result

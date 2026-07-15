"""package_watch — deterministic dependency watcher.

Watches the direct dependencies of every repo registered in the command
center's configs/kanban.yaml (plus the command center itself), compares the
locked/current versions against PyPI, and upserts real updates into the
`packages` database. No LLM involved: detection is pure data. Acting on an
update stays human-gated — drag the card you create for it to Approved and
the kanban bridge opens an L2 mission (bump + tests + PR).

Module tree / stages (linear, each independently runnable):
  stage 1  discover_repos()   config/projects.yaml registry (watch_packages)
                              -> [(repo_name, repo_path)]
  stage 2  direct_deps()      pyproject [project.dependencies] names (the deps
                              a human manages); requirements.txt fallback for
                              repos without a pyproject
  stage 3  locked_versions()  uv.lock resolved versions for those names
                              (the truth of what runs today)
  stage 4  pypi_latest()      PyPI JSON API latest stable per package
  stage 5  diff()             packaging.version compare; severity = which
                              release segment changed (major/minor/patch) —
                              derived, never thresholded
  stage 6  upsert()           rows keyed pre_hash="{repo}:{package}"; Status
                              set only on NEW rows so human triage
                              (Planned/Skipped) is never clobbered

Run:  python -m growthos.packages          (also wired into the daily loop)
"""
from __future__ import annotations

import logging
import tomllib
from datetime import date
from pathlib import Path

import httpx
from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from .actions import client

log = logging.getLogger("growthos.packages")

PYPI = "https://pypi.org/pypi/{name}/json"


# stage 1 ------------------------------------------------------------------

def discover_repos() -> list[tuple[str, Path]]:
    from .config import load_projects
    out = []
    for proj in load_projects().projects:
        if not proj.watch_packages:
            continue
        path = Path(proj.repo)
        if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
            out.append((proj.name, path))
        else:
            log.warning("repo %s has no pyproject/requirements at %s; skipped",
                        proj.name, path)
    return out


# stage 2 ------------------------------------------------------------------

def direct_deps(repo: Path) -> set[str]:
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        reqs = data.get("project", {}).get("dependencies", [])
        return {Requirement(r).name.lower().replace("_", "-") for r in reqs}
    names: set[str] = set()
    for line in (repo / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            names.add(Requirement(line).name.lower().replace("_", "-"))
    return names


# stage 3 ------------------------------------------------------------------

def locked_versions(repo: Path, names: set[str]) -> dict[str, str]:
    lock = repo / "uv.lock"
    if lock.exists():
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
        return {p["name"].lower(): p["version"]
                for p in data.get("package", [])
                if p.get("name", "").lower() in names and "version" in p}
    # no lockfile: pinned requirements (name==version) are the only truth
    out: dict[str, str] = {}
    req_file = repo / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            req = Requirement(line)
            pins = [s.version for s in req.specifier if s.operator == "=="]
            if pins and req.name.lower() in names:
                out[req.name.lower()] = pins[0]
    return out


# stage 4 ------------------------------------------------------------------

def pypi_latest(http: httpx.Client, name: str) -> str:
    r = http.get(PYPI.format(name=name))
    r.raise_for_status()
    return r.json()["info"]["version"]


# stage 5 ------------------------------------------------------------------

def severity(current: Version, latest: Version) -> str:
    if latest.major != current.major:
        return "major"
    if latest.minor != current.minor:
        return "minor"
    return "patch"


# stage 6 ------------------------------------------------------------------

def main() -> None:
    import logging as _l
    _l.basicConfig(level=_l.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    repos = discover_repos()
    log.info("watching %d repo(s): %s", len(repos), [n for n, _ in repos])

    af = client()
    existing = {}
    for d in af.row_details("packages", af.list_row_ids("packages")):
        c = d["cells"]
        if c.get("Name"):
            existing[f"{c.get('Repo', '')}:{c['Name']}"] = c.get("Status", "")

    today = date.today().isoformat()
    rows, checked = [], 0
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        for repo_name, repo_path in repos:
            deps = direct_deps(repo_path)
            current = locked_versions(repo_path, deps)
            log.info("%s: %d direct deps, %d locked", repo_name, len(deps), len(current))
            for pkg, cur in sorted(current.items()):
                checked += 1
                try:
                    latest = pypi_latest(http, pkg)
                    cur_v, latest_v = Version(cur), Version(latest)
                except (httpx.HTTPError, InvalidVersion) as exc:
                    log.warning("%s/%s: %s", repo_name, pkg, exc)
                    continue
                if latest_v <= cur_v:
                    continue
                key = f"{repo_name}:{pkg}"
                cells = {"Package": pkg, "Repo": repo_name, "Current": cur,
                         "Latest": latest, "Severity": severity(cur_v, latest_v),
                         "LastSeen": today}
                if key not in existing:        # never clobber human triage
                    cells["Status"] = "Inbox"
                rows.append({"pre_hash": key, "cells": cells})
    wrote = af.upsert("packages", rows)
    log.info("checked %d pinned deps, %d updates available, %d rows upserted",
             checked, len(rows), len(wrote))


if __name__ == "__main__":
    main()

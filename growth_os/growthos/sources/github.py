"""Find relevant GitHub repos via the search API (recent + min stars)."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import httpx
from command_center.research_topics import github_query_for_topic
from ..config import GithubCfg
from ..models import CuratedItem

API = "https://api.github.com/search/repositories"


def fetch(cfg: GithubCfg, token: str = "", per_query: int = 8) -> list[CuratedItem]:
    if not cfg.enabled:
        return []
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    pushed = (date.today() - timedelta(days=cfg.lookback_days)).isoformat()
    by_url: dict[str, CuratedItem] = {}
    failures: list[str] = []
    for topic in cfg.review_topics:
        q = github_query_for_topic(topic)
        full_q = f"{q} pushed:>={pushed} stars:>={cfg.min_stars}"
        params = {"q": full_q, "sort": "stars", "order": "desc", "per_page": per_query}
        try:
            r = httpx.get(API, params=params, headers=headers, timeout=30)
            r.raise_for_status()
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            failures.append(f"{topic}: {type(exc).__name__}: {exc}")
            continue
        for repo in r.json().get("items", []):
            updated = None
            try:
                updated = datetime.fromisoformat(repo["updated_at"].replace("Z", "")).date()
            except Exception:
                pass
            url = repo["html_url"]
            existing = by_url.get(url)
            if existing is not None:
                review_topics = existing.extra.setdefault("review_topics", [])
                if topic not in review_topics:
                    review_topics.append(topic)
                continue
            by_url[url] = CuratedItem(
                kind="repo", external_id=url, title=repo["name"],
                url=url, summary=(repo.get("description") or "")[:600],
                topics=repo.get("topics", [])[:6], source=f"github:{topic}", published=updated,
                extra={
                    "owner": repo["owner"]["login"],
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language") or "",
                    "forks": repo.get("forks_count", 0),
                    "open_issues": repo.get("open_issues_count", 0),
                    "license": (repo.get("license") or {}).get("spdx_id") or "",
                    "default_branch": repo.get("default_branch") or "",
                    "archived": bool(repo.get("archived", False)),
                    "pushed_at": repo.get("pushed_at") or "",
                    "code_links": [url],
                    "related_links": [
                        value for value in [repo.get("homepage")] if value
                    ],
                    "review_topics": [topic],
                },
            )
    if failures:
        raise RuntimeError(
            f"{len(failures)}/{len(cfg.review_topics)} GitHub research queries "
            "failed; first failure: " + failures[0]
        )
    return list(by_url.values())

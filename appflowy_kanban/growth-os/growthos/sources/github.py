"""Find relevant GitHub repos via the search API (recent + min stars)."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import httpx
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
    out: list[CuratedItem] = []
    queries = list(cfg.queries) + [f"topic:{t}" for t in cfg.topics]
    for q in queries:
        full_q = f"{q} pushed:>={pushed} stars:>={cfg.min_stars}"
        params = {"q": full_q, "sort": "stars", "order": "desc", "per_page": per_query}
        try:
            r = httpx.get(API, params=params, headers=headers, timeout=30)
            r.raise_for_status()
        except Exception:
            continue
        for repo in r.json().get("items", []):
            updated = None
            try:
                updated = datetime.fromisoformat(repo["updated_at"].replace("Z", "")).date()
            except Exception:
                pass
            out.append(CuratedItem(
                kind="repo", external_id=repo["html_url"], title=repo["name"],
                url=repo["html_url"], summary=(repo.get("description") or "")[:600],
                topics=repo.get("topics", [])[:6], source=f"github:{q}", published=updated,
                extra={"owner": repo["owner"]["login"], "stars": repo.get("stargazers_count", 0),
                       "language": repo.get("language") or ""},
            ))
    return out

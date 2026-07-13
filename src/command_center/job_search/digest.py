from __future__ import annotations

from pathlib import Path

from command_center.job_search.cache_io import read_json_file
from command_center.job_search.config import data_root, ensure_data_dirs, load_config
from command_center.job_search.retention import plan_retention


def write_digest(*, root: Path | None = None) -> Path:
    cfg = load_config()
    base = root or data_root(cfg)
    ensure_data_dirs(base)
    suggestions = []
    for path in (base / "source_cache" / "suggestions").glob("*.json"):
        suggestions.append(read_json_file(path))
    retention = plan_retention(root=base)
    lines = [
        "# Job Search Digest",
        "",
        "## Suggested Jobs",
        f"- Cached suggestions: {len(suggestions)}",
    ]
    for item in suggestions[:5]:
        job = item["job"]
        fit = item["fit"]
        lines.append(f"- {job['company']} - {job['role_title']}: {fit['score']}/100, {fit['action']}")
    lines.extend(
        [
            "",
            "## Needs Geoff",
            "- Review prepared applications in `data/job_search/applications_active/*`.",
            "- Manual blockers are listed in each `application.yml`.",
            "",
            "## Retention",
            f"- Records scanned: {len(retention['records'])}",
        ]
    )
    for row in retention["records"]:
        lines.append(f"- {row['application_id']}: {row['action']} until {row['retention_until']}")
    out = Path(cfg.job_search.digest_path)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out

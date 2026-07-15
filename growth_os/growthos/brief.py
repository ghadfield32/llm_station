"""Daily brief + spaced-repetition review queue.

- Surfaces lessons whose NextReview is due (SM-2-lite intervals).
- Renders a markdown brief of what's new + what to revisit + next book.
- In live mode it can upsert the brief into the first-party `review` board; in
  dry-run it writes _export/brief_YYYY-MM-DD.md.

Spaced repetition (review a lesson, then call schedule_next):
  quality >=4 -> interval *= 2.5 ; ==3 -> *1.5 ; <3 -> reset to 1 day.
"""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
from .models import Lesson


def schedule_next(lesson: Lesson, quality: int) -> Lesson:
    if quality >= 4:
        lesson.interval = max(1, round(lesson.interval * 2.5))
    elif quality == 3:
        lesson.interval = max(1, round(lesson.interval * 1.5))
    else:
        lesson.interval = 1
    lesson.next_review = date.today() + timedelta(days=lesson.interval)
    return lesson


def due_lessons(lessons: list[Lesson], on: date | None = None) -> list[Lesson]:
    on = on or date.today()
    return [lesson for lesson in lessons if lesson.next_review and lesson.next_review <= on]


def render_brief(new_papers, new_repos, new_signals, due, next_book) -> str:
    d = date.today().isoformat()
    out = [f"# Daily brief — {d}", ""]
    if next_book:
        out += [f"**Reading next:** {next_book}", ""]
    def section(title, rows, fmt):
        if not rows:
            return []
        s = [f"## {title}"]
        s += [fmt(r) for r in rows]
        s.append("")
        return s
    out += section("New papers", new_papers, lambda p: f"- [{p.title}]({p.url}) · score {p.score}")
    out += section("New repos", new_repos, lambda r: f"- [{r.title}]({r.url}) · ⭐{r.extra.get('stars',0)}")
    out += section("Signals", new_signals, lambda s: f"- [{s.title}]({s.url}) · {s.source}")
    out += section("Review today", due, lambda lesson: f"- {lesson.lesson}  _( {lesson.domain} )_")
    return "\n".join(out)


def write_brief_file(md: str, out_dir: str = "./_export") -> Path:
    p = Path(out_dir); p.mkdir(parents=True, exist_ok=True)
    f = p / f"brief_{date.today().isoformat()}.md"
    f.write_text(md, encoding="utf-8")
    return f


# ----------------------------------------------------------------------------
# Optional LLM overview (local Ollama): clusters the day's items and says why
# they matter. Any failure degrades to the plain link-list brief.
# ----------------------------------------------------------------------------

def llm_overview(papers, repos, signals, base_url: str, model: str) -> str | None:
    import logging
    import re
    import httpx
    log = logging.getLogger("growthos.brief")
    if not base_url or not (papers or repos or signals):
        return None
    lines = []
    for label, rows in (("PAPER", papers), ("REPO", repos), ("SIGNAL", signals)):
        for r in rows[:15]:
            lines.append(f"{label} (score {r.score}): {r.title}")
    prompt = (
        "You write the morning brief for a data scientist working on Bayesian "
        "modeling, forecasting, sports analytics (basketball/player tracking), "
        "computer vision, MLOps, and LLM agents.\n\n"
        "Below are today's auto-curated items. Write 120-200 words: group them "
        "into 2-4 themes, say in one sentence per theme why it matters for that "
        "work, and bold the single most worth-reading item. No preamble, no "
        "bullet-per-item listing (the full list follows your text).\n\n"
        + "\n".join(lines))
    try:
        r = httpx.post(f"{base_url.rstrip('/')}/api/chat", timeout=300,
                       json={"model": model, "stream": False,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = r.json()["message"]["content"]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return text or None
    except Exception as exc:
        log.warning("LLM overview unavailable (%s); plain brief", exc)
        return None


def mission_worklog(imported_path: str, ledger_url: str) -> str:
    """One line per kanban-bridged mission with its current Ledger status, so
    the morning brief shows what the system dispatched/finished. Loud (logged)
    but non-fatal when the ledger is unreachable — the brief still renders."""
    import json
    import logging
    from pathlib import Path
    import httpx
    log = logging.getLogger("growthos.brief")
    path = Path(imported_path)
    if not path.exists():
        return ""
    imported: dict = json.loads(path.read_text(encoding="utf-8"))
    if not imported:
        return ""
    lines = []
    with httpx.Client(timeout=10) as client:
        for card_key, mission_id in sorted(imported.items(), key=lambda kv: kv[1]):
            try:
                m = client.get(f"{ledger_url.rstrip('/')}/mission/{mission_id}").json()
                status = m.get("status", "?")
                action = (m.get("action") or "").splitlines()[0][:70]
                lines.append(f"- `{mission_id}` **{status}** — {action}")
            except Exception as exc:
                log.warning("ledger unreachable for %s: %s", mission_id, exc)
                lines.append(f"- `{mission_id}` (ledger unreachable)")
    return "\n".join(lines[-15:])


# ----------------------------------------------------------------------------
# Live brief: read what the Curator wrote in the last day + due lessons from
# first-party board store, render the brief, and upsert it into `review` (one
# row per day, pre_hash = the date, so re-runs update rather than duplicate).
# ----------------------------------------------------------------------------

def _recent(af, db: str, title_field: str, hours: int = 26) -> list:
    from types import SimpleNamespace
    from datetime import datetime, timedelta, timezone
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        ids = af.rows_updated_since(db, after)
    except Exception:
        ids = af.list_row_ids(db)
    items = []
    for d in af.row_details(db, ids):
        c = d["cells"]
        if not c.get("Name"):           # skip the grid's default blank rows
            continue
        items.append(SimpleNamespace(
            title=c.get("Name", ""), url=c.get("URL", ""),
            score=c.get("Score", ""), source=c.get("Source", ""),
            extra={"stars": c.get("Stars", "")}))
    return items


def _due_lessons(af) -> list:
    from types import SimpleNamespace
    out = []
    for d in af.row_details("lessons", af.list_row_ids("lessons")):
        c = d["cells"]
        if not c.get("Name"):
            continue
        nxt = c.get("NextReview")
        nxt_date = None
        if isinstance(nxt, dict) and nxt.get("pretty_start_date"):
            nxt_date = date.fromisoformat(nxt["pretty_start_date"])
        if nxt_date is None or nxt_date <= date.today():
            out.append(SimpleNamespace(lesson=c.get("Name", ""),
                                       domain=c.get("Domain") or "Life"))
    return out


def _next_book(af) -> str:
    reading, queued = "", ""
    for d in af.row_details("library", af.list_row_ids("library")):
        c = d["cells"]
        if not c.get("Name"):
            continue
        if c.get("Status") == "Reading" and not reading:
            reading = c["Name"]
        elif c.get("Status") == "To read" and not queued:
            queued = c["Name"]
    return reading or queued


def main():
    import logging
    from .config import load_settings
    from .internal_board import InternalBoardClient

    st = load_settings()
    logging.basicConfig(level=getattr(logging, st.growthos_log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("growthos.brief")

    boards = InternalBoardClient(
        store_dir=st.growthos_board_store,
        event_log=st.growthos_kanban_event_log,
        dry_run=False,
    )
    papers = _recent(boards, "papers", "Title")
    repos = _recent(boards, "repos", "Name")
    signals = _recent(boards, "signals", "Headline")
    due = _due_lessons(boards)
    md = render_brief(papers, repos, signals, due, _next_book(boards))

    overview = llm_overview(papers, repos, signals,
                            st.ollama_base_url, st.growthos_brief_model)
    if overview:
        head, _, rest = md.partition("\n")
        md = f"{head}\n\n## Why today matters\n{overview}\n{rest}"

    worklog = mission_worklog(st.growthos_kanban_imported, st.ledger_base_url)
    if worklog:
        md += "\n## Mission worklog\n" + worklog + "\n"

    f = write_brief_file(md)
    today = date.today().isoformat()
    wrote = boards.upsert("review", [{"pre_hash": f"brief-{today}",
                                  "cells": {"Day": today, "Date": today, "Brief": md,
                                            "Focus": due[0].lesson if due else ""}}])
    log.info("brief written -> %s, review rows upserted: %d", f, len(wrote))


if __name__ == "__main__":
    main()

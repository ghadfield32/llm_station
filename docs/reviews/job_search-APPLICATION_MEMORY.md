# Application Memory

> **Archived — merged into [job_search/READINESS_FAQ.md](../job_search/READINESS_FAQ.md)**
> ("What data is kept, for how long, and why?"), which covers this plus the
> retention/archive mechanics in more current detail.

Active applications live under:

```text
data/job_search/applications_active/<application_id>/
```

Each active application contains:

- `application.yml`
- `job_description.md.gz`
- `generated_resume.md`
- `cover_letter.md`
- `recruiter_message.md`
- `resume_selection_report.md`
- `communications.jsonl`
- `recruiter_notes.md`
- `followups.md`

Retention defaults to 30 days after application date. Recruiter contact,
interviews, take-homes, offers, and negotiations extend retention until 30 days
after the latest activity.

The permanent archive is:

```text
data/job_search/applications_archive/outcomes.sqlite
```

The MVP writes minimal archive rows and marks stale active folders as compacted.
Rich file deletion is disabled by default through `purge_rich_files: false`.


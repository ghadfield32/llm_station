# Resume Claim Policy

Every generated bullet must trace back to:

1. An achievement ID in `achievement_bank.yml`.
2. At least one evidence file under `data/job_search/evidence/`.
3. A non-low confidence rating unless Geoff explicitly overrides it later.

Unsupported job keywords are reported as gaps. They are not inserted into the
resume just because the job posting mentions them.

The MVP emits `resume_selection_report.md` for every prepared application. It
lists selected achievement IDs, selected bullets, matched keywords, unsupported
keywords, rejected claims, and World Model Sports treatment.


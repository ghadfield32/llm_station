# Self-Improvement Scan Pipeline — project tracker

**Status**: in progress (2026-06-13) · **Owner**: self-improvement-scan · **Risk**: observer-only (drafts `Proposed` cards + one report; no promote/merge/deploy)

The top-level planning surface for the daily self-improvement scan, per
`docs/reference/betts-basketball-standards/PIPELINE_STANDARDS_TEMPLATE.md` §0.11a ("add the stage registry row first").
This is the operator tracker: what each stage is, what conforms to standard, and what's left.

> **Scope decision (2026-06-13).** llm_station is a lean LLM control plane, not the basketball
> forecasting stack. It has **no** Cloudflare R2, Railway, 5080/4090 fleet, medallion/DuckDB/dbt,
> or GBDT/Bayesian serving — verified (no `upload_data.sh`, no `BETTS_*`, no boto3/duckdb/pymc/
> xgboost/airflow deps). So we apply the **transferable principles** of the
> `docs/reference/betts-basketball-standards/` standards (data-derived decisions, no defensive coding, no leakage/temporal safety, module-tree
> + stage header, blocking validation gate, manifest/idempotency, multi-session git hygiene) and
> NOT the infrastructure (R2 publish/locks, fleet routing, Railway, medallion). Infra-coupled
> standard items are marked **N/A (no infra)** below with the reason.

---

## 1. Module tree

```
src/command_center/improvement/
  discovery/                      # the scan pipeline (observer-only)
    __init__.py                   # public API surface
    pillars.py        STAGE 0     # 9 pillars → 13 target types + named sources
    findings.py                   # Finding model + → bounded Proposed experiment
    ranking.py        STAGE 3     # ICE/RICE/WSJF/VOI + confidence band  ← weights to externalize
    ranking_config.py (NEW)       # data-derived ranking weights loaded from configs/discovery.yaml
    acceptance.py     (NEW)       # learn P(accept) from Ledger card outcomes (champion/challenger)
    charter.py                    # ObserverCharter — structural observer-only wall
    sources.py        STAGE 1     # scanners: offline code-health + injected feeds; ScanOutcome
    triage.py         STAGE 2     # dedup vs open cards + negative-result memory + cooldown
    report.py         STAGE 5     # decision-grade Markdown report
    manifest.py       (NEW)       # report sidecar: sha256, sources, produced_at, git_sha, libs
    pipeline.py       ORCH        # scan→classify→rank→draft→emit (module-tree header here)
    dag_support.py                # Airflow-free glue + XCom serialization
    delivery/         (NEW)       # how the report reaches the human
      digest.py                   # HTML daily-digest renderer (Start-Here/new/failed/weekly)
      email_smtp.py               # stdlib smtplib sender (env creds; dry-run writes .html)
      ping.py                     # one-line chat-channel nudge
  selfmetrics.py                  # DORA / acceptance / convergence power-law / BWT-FWT
  board.py                        # registry → AppFlowy "Improvements" Kanban (clobber-safe)
dags/self_improvement_daily.py    # observer-only TaskFlow DAG (daily + on-demand asset)
src/command_center/cli/improvement.py   # `improvement scan` + (NEW) `scan-validate`
configs/discovery.yaml            (NEW) # ranking weights + thresholds (DiscoveryConfig contract)
```

Each path is the canonical location — no duplicated modules across trees (PIPELINE_STANDARDS §0.11).

## 2. The five stages (linear, idempotent)

Strict linear chain; each stage reads only prior-stage output; report/draft is last (the
"promotion is always the last step" rule). Idempotency: experiment ids are content hashes of the
finding, drafting is dedup-guarded, the run is keyed to its logical date → re-running a day
produces no duplicate cards.

| # | Stage | Module | Input | Output | Gate / contract |
|--:|-------|--------|-------|--------|-----------------|
| 1 | scan (mapped per source) | `sources.py` | a source spec + injected fetch | `ScanOutcome{findings,error}` | a dead feed is a recorded `error`, never a swallowed exception |
| 2 | classify_and_dedup | `triage.py` | findings | `TriageResult[]` | dedup vs open cards; **negative-result memory** suppresses human-rejected ideas; cooldown |
| 3 | score_and_rank | `ranking.py` + `ranking_config.py` | draft findings | ranked `(Finding,score)[]` | weights are **data-derived config** (not inline literals); confidence reported as a band |
| 4 | draft_proposals | `findings.to_experiment_definition` + `charter.py` | top-N ranked | `Proposed` cards | bounded, secret-free, L2-capped, human-gated; charter exposes no promote/merge/deploy |
| 5 | emit_report_and_cards | `report.py` + `manifest.py` + `delivery/` | ranked + triage + outcomes | report + cards + manifest + digest | card cap never silently drops (overflow reported); report has a sha256 manifest |

Modes (orchestrator): `dry-run` (default — zero writes, renders everything) · `apply` (drafts cards
+ writes report) · per-source restriction (`--source`) · ranking method override (`--method`).

## 3. Standards conformance matrix (transferable principles)

State: ✅ done · 🟡 in progress · ⬜ todo · **N/A** infra-coupled (no R2/fleet/Railway here).

| Standard (transferable) | State | Evidence / Remaining |
|-------------------------|:----:|----------------------|
| No defensive coding / fail-loud (no `except: pass`, no fake values) | ✅ | scan itself *detects* this; `run_scanners` records errors, never swallows; SMTP fails loud on missing creds |
| **Data-derived decisions / no hardcoded thresholds** | ✅ | every knob in `configs/discovery.yaml` (`DiscoveryConfig`), no inline literals; learned P(accept) ranker in `acceptance.py` (`test_discovery_config.py`, `test_acceptance.py`) |
| No data leakage / temporal safety | ✅ | learned ranker uses `temporal_split` (older trains, newer validates), standardizes on train only, features carry no outcome field; `scan-validate` asserts `acceptance_features_have_no_leakage` |
| Module-tree + stage header at top of orchestrator | ✅ | `pipeline.py` module docstring enumerates the module tree, 5 stages, modes, observer boundary, hard contracts |
| Blocking validation gate ("N/N PASS") | ✅ | `validate.py` → `improvement scan-validate` / `make improvement-scan-validate` (10/10 PASS; `test_discovery_validate.py`) |
| Idempotency | ✅ | content-hashed ids; dedup-guarded drafting; logical-date keyed (`test_second_apply_is_idempotent`) |
| Artifact manifest (sha256 + provenance) | ✅ | `manifest.py` sidecar `<report>.manifest.json` (output sha256, injected produced_at, git_sha, lib versions; `test_discovery_manifest.py`) |
| Multi-session git hygiene (exact staging, branch-per-session, no `-A`/force-push) | 🟡 | process rule — see §6; followed by hand |
| uv / pyproject dependency discipline | ✅ | **zero** new deps added (SMTP/hashing/subprocess are stdlib); `uv sync` unchanged |
| R2 publish + lock/validation protocol | **N/A** | no R2 in this repo |
| 5080/4090 fleet routing | **N/A** | no production fleet for this project |
| Railway serving / medallion / DuckDB / dbt | **N/A** | not present; the scan serves a report + Kanban cards, not a model |
| GBDT/Bayesian *serving* | **N/A** | the only modeling here is the P(accept) ranker (§4), kept pure-Python and lean |

## 4. Data-derived ranking — the keystone gap (plan)

The standards' binding rule is *"data-derived decisions … no hardcoded thresholds."* Our fixed
ICE/RICE/WSJF coefficients and the `confidence_band` half-width are inline literals. The compliant,
lean path (no heavy modeling deps):

- **Phase A — externalize (closes the letter of the rule).** Move every weight/threshold into
  `configs/discovery.yaml`, validated by a `DiscoveryConfig` Pydantic contract. Per the modeling
  guides an explicit documented config knob is sanctioned ("config knob, not in-line magic"); inline
  literals are not.
- **Phase B — learn P(accept) (closes the spirit).** Record each card's human outcome
  (Accepted/Rejected/Deferred) from the Ledger. Fit a pure-Python logistic model of acceptance
  probability on finding features (pillar, source, evidence strength, the formula score), **temporal
  split** (train on older cards, validate on newer — never random), **leakage-controlled** (no
  post-decision field as a feature), and gate promotion by **champion-challenger**: the learned
  scorer replaces the formula only when it beats it on held-out accept/reject (e.g. AUC / precision@K).
  Below a documented minimum sample size it **abstains** and uses the formula baseline (logged, not
  faked). The formula stays as the rollback baseline.

This is also why the delivery's **acceptance feedback loop** matters — it's the training signal.

## 5. Delivery — how it reaches the human (email + Kanban + chat)

| Surface | Module | Role | State |
|---------|--------|------|:----:|
| AppFlowy Kanban | `board.py` (+ `Pillar` for swimlanes) | where you ACT (the human wall) | ✅ |
| **Mission-card bridge** | `kanban.py` (`improvement scan --kanban`) | "report daily + **apply if approved**": top findings → human-gated `mission_intake` Backlog cards (Section=Command Center, risk mapped to L0–L4); a human drags to Approved → bridge → mission. Observer-only (no approve verb). | ✅ |
| Email digest (SMTP) | `delivery/digest.py` + `email_smtp.py` | where you LEARN/triage (3-min skim) | ✅ |
| Chat ping (Discord/…) | `delivery/ping.py` | the nudge | ✅ |
| Weekly metrics rollup | `selfmetrics.py` → digest `weekly=` | see the loop improving | 🟡 renderer ready; Monday auto-send TBD |

Digest order: **Start-Here top-3 (by score)** → new-since-yesterday / aging → not-proposed
(negative-memory) → failed sources → weekly trend. Every line links to its Kanban card. Body capped;
overflow reported, never silently dropped. SMTP creds from env; **dry-run writes the `.html` to disk**
(no creds needed); missing creds on a real send **fail loud** (no silent skip).

## 6. Multi-session working rules (transferable git hygiene)

- Branch per session (`setup/…` here); **exact-path staging only**, never `git add -A`.
- Never force-push or amend a pushed commit; `git pull --rebase` and keep other sessions' work.
- Commit code before generated artifacts; never commit `generated/`, `data/`, report outputs.
- Docs (this tracker) updated in the same change set as the code it describes.

## 7. Done / Remaining (in order)

1. ✅ Pipeline built (sources→findings→triage→rank→report), DAG, CLI, selfmetrics.
2. ✅ This tracker (planning surface).
3. ✅ Phase A: `configs/discovery.yaml` + `DiscoveryConfig` (contract in `..schema`); inline literals removed.
4. ✅ `acceptance.py`: `FeatureLog` recorder + pure-Python P(accept) + temporal split + champion-challenger (Phase B harness; abstains until ≥`min_decisions` real outcomes — wired into the scan's draft step).
5. ✅ Module-tree header on `pipeline.py`; `scan-validate` blocking gate (10/10); `manifest.py` sidecar.
6. ✅ `delivery/`: digest renderer + stdlib SMTP sender + chat ping; Kanban `Pillar` row; CLI `--email/--board/--ping` + new-since-yesterday diff.
7. ✅ Close: full suite green; ladder (validate / scan-validate 10/10 / evals) green; ruff + mypy clean on new code; **zero new deps** (no `uv sync` change). Multi-session git hygiene (§6) followed.

Open follow-ups (data-gated, not blocking): the learned ranker stays in **report-only** mode until real
accept/reject history accrues — it abstains to the formula and the champion-challenger verdict is
surfaced (not auto-swapped); swapping the live ranker to P(accept) is a deliberate, gated step.
A weekly metrics rollup email (DORA / acceptance-by-pillar / convergence) — the digest already
accepts a `weekly` dict; auto-scheduling it on Mondays is the remaining wiring.

See also: `../self-improvement-dag.md` is folded into `../../daily-self-improvement-dag.md` (the design +
as-built reference); `../../MASTER.md` §6.4 indexes the scan.

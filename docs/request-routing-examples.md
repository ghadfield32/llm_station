# Request routing examples

These examples show how different requests should classify, route, and respond before any real
model call or external write happens. They are operator-facing examples, not hidden prompts.

## 1. Read-only repo question

**User request**
`Summarize where the data quality checks live in betts_basketball.`

**Route**
- Risk: `L0_read_only`
- Environment: no worktree lease required
- Models: local `triage` first; local/cheap summarizer if enough context
- Judges: scope judge only if the answer proposes changes
- External action: none

**Expected response**
`I found the checks in <files>. No changes were made. The current coverage is <summary>, and the main gap is <gap>.`

## 2. Local implementation

**User request**
`Add a regression test for the age-curve spline and fix the smallest bug needed to pass it.`

**Route**
- Risk: `L2_local_edits`
- Environment: ledger mission, one branch, one leased worktree, repo devcontainer, no secrets
- Executor: Claude Code primary through the `coder` route; Codex fallback if Claude stalls
- Checks: static tools first, then diff judge, secret judge, defensive-coding judge
- External action: stop before push unless upgraded to L3 with approval

**Expected response**
`I created mission <id>, leased branch <branch>, added the regression test, made the minimal fix, and the local checks now pass. No branch was pushed.`

## 3. Open a GitHub PR

**User request**
`Implement the fix and open a PR.`

**Route**
- Risk: `L3_external_write`
- Environment: same L2 leased worktree, then external-write approval
- Executor: Claude Code/Codex as configured
- Judges: pre-commit array plus cross-provider pre-push skeptic
- External action: push feature branch/open PR only after signed human approval

**Expected response before approval**
`The branch is ready and the pre-push skeptic passed. This is L3 because it writes to GitHub. Awaiting approval to push <branch> and open a PR.`

**Expected response after approval**
`Approved. I pushed <branch>, opened PR <url>, and left merge/deploy blocked behind branch protection and your review.`

## 4. Dangerous production action

**User request**
`Merge the PR and deploy it.`

**Route**
- Risk: `L4_dangerous`
- Environment: no autonomous execution
- Judges: can provide a readiness checklist only
- External action: manual only

**Expected response**
`That is L4. I can summarize readiness and list the exact manual checks, but I will not merge, deploy, publish, delete, or handle secrets automatically.`

## 5. Model update

**User request**
`Update the coder model to whichever model is top on the leaderboard.`

**Route**
- Risk: `L1_plan_only` for discovery; `L2` for a candidate config edit; `L3` only if opening a PR
- Environment: `make model-scout` writes a report; config edit must pass contracts
- Judges: `make evals`, canary metrics, cross-provider review for judge roles
- External action: no blind promotion

**Expected response**
`I generated generated/model-scout-report.md. I am not auto-promoting a leaderboard winner; the safe path is candidate edit, validate, evals, canary, then promote or rollback.`

## 6. Standards or skill update

**User request**
`Make the agents remember our no-defensive-coding and data-science standards everywhere.`

**Route**
- Risk: `L2_local_edits`
- Source of truth: `configs/standards.yaml`
- Rendered files: `CLAUDE.md` and `AGENTS.md` by `make repo-install`
- Judges: standards validation and normal pre-commit judges
- External action: no self-rewrite outside the gated pipeline

**Expected response**
`I updated configs/standards.yaml, validated it, and rendered the profile into the target repo's CLAUDE.md and AGENTS.md. Judge Gate reads the same standards file.`

## 7. Usage/cost review

**User request**
`Show me what the agents spent this week and where they escalated too often.`

**Route**
- Risk: `L0_read_only`
- Sources: LiteLLM virtual-key usage plus Ledger mission/judge history
- Output: `generated/usage-digest.md`
- External action: none

**Expected response**
`I wrote generated/usage-digest.md with spend by role/key, call volume, escalation rate, judge block rate, and budget headroom. No config changes were made.`

## 8. Data pipeline failure

**User request**
`The nightly DAG failed; find the root cause and prepare a fix.`

**Route**
- Risk: `L1_plan_only` for RCA; upgrade to `L2_local_edits` only for a gated patch
- Environment: logs/data checks first; leased worktree only after a real issue is confirmed
- Models: local log scanner, then cross-provider root-cause debugger if unclear
- Judges: plan critic, data-contract judge, diff/security/defensive judges for any patch
- External action: PR requires L3 approval

**Expected response**
`The failure is real, not noise. Root cause is <cause>. I opened mission <id> with a fix plan and will only patch inside a leased worktree after the plan passes.`

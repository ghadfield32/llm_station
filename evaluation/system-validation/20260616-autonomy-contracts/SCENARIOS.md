# Scenarios

| Scenario | Status | Evidence |
| --- | --- | --- |
| autonomy config validates | PASS | configs/autonomy.yaml |
| canonical event families declared | PASS | BASELINE.md#event-families |
| repo autonomy enabled | BLOCKED | GAPS.md#repo-and-desktop-blockers |
| desktop automation enabled | BLOCKED | GAPS.md#repo-and-desktop-blockers |
| completion verifier requires evidence | PASS | configs/autonomy.yaml |
| local agent tool/memory/multi-turn validation | PASS | agent-validation.json |
| desktop target snapshot verification | PASS | desktop-target-verify.json |
| desktop adapter readiness | BLOCKED | desktop-adapter-readiness.json |
| no-op canaries scheduled | BLOCKED | GAPS.md#canaries |
| telemetry production backend | BLOCKED | GAPS.md#telemetry |
| GitHub App production auth | BLOCKED | GAPS.md#auth-and-external-runtimes |
| GitHub App installation observed | PASS | github-app-verify.json |
| GitHub App repository permission verification | PASS | GAPS.md#auth-and-external-runtimes |
| GitHub branch protection verification | BLOCKED | branch-protection-verify.json |
| external runtime spike | BLOCKED | GAPS.md#auth-and-external-runtimes |

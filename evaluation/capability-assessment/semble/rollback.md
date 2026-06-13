# Rollback — semble

One command + two cache deletions; nothing else was touched.

```powershell
uv pip uninstall semble
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\semble"
# optional (frees the one-time model download):
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface\hub\models--minishlab--potion-code-16M"
```

Verification after rollback: `make validate`-equivalent suite re-run
(validate / render / evals / mission-dryrun) — semble was never wired into
any config, agent, or pipeline, so baseline behavior is unchanged by
construction. `semble install` was never executed, so there is no agent
config to revert.

# Rollback — abtop

The binary lives only inside the evaluation directory and was never on PATH;
`--setup` was never run, so no agent config was touched.

```powershell
Remove-Item -Recurse -Force evaluation\capability-assessment\abtop\bin
```

That is the entire rollback. Verified post-run: no `~/.claude/abtop*` files,
no `~/.cache/abtop/`, no `statusLine` key in `~/.claude/settings.json`.

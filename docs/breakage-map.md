# Breakage map — what breaks when you change something

Declared in `configs/breakage.yaml`. Before trusting any change, run:
```
make impact            # reads your git diff, prints blast radius + required checks
```

| If you change… | It affects… | Run before trusting |
|---|---|---|
| configs/models.yaml | generated litellm config, routing, judge model choices | make validate; make models; make mission-dryrun → canary |
| configs/judges.yaml | judge stages, cross-provider pairing, budgets | make validate; make mission-dryrun |
| configs/gates.yaml | approval policy, lifecycle, GitHub write permission | make validate; make mission-dryrun |
| configs/environments.yaml | devcontainers, leases, egress, secret exposure | make validate; make render; make env-smoke |
| schemas/*.py | all config validation, JSON schema, docs | make schema; make validate; make render |
| docker-compose.yml | control-plane availability, volumes, network | make verify; make up; make health |

The contracts make most breakage impossible to commit in the first place:
`make validate` rejects typo'd keys, duplicate model priorities, two canaries in one
role, out-of-range weights, missing risk tiers, L3/L4 without approval, and any
repo_task that is persistent or holds secrets.

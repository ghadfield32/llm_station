# Action risk tiers (gateway authority)

The Life Center status/control gateway is **read-only first**. It publishes
typed, redacted health facts and accepts **no** arbitrary command, shell string,
Docker argument, SQL, path, or URL. Any future action must be a named,
schema-validated, allowlisted workflow with a risk tier, approval rule, audit
record, timeout, idempotency behavior, and rollback/recovery procedure.

This mirrors the agent-authority levels (L0–L4) in
[`LIFE_CENTER_SECURITY_BASELINE.md`](../../docs/operations/LIFE_CENTER_SECURITY_BASELINE.md).

| Tier | Examples | Approval |
| --- | --- | --- |
| **L0 read-only** | `get_overview`, `get_service_health`, `get_backup_status`, `get_storage_capacity` | none (redacted output only) |
| **L1 safe check** | `verify_backup`, `refresh_inventory` | logged; no state change beyond a verification record |
| **L2 bounded restart** | isolated stateless-worker restart | human approval per action, audited |
| **L3 stateful change** | service upgrade/rollback | double-agreement + human approval; snapshot first |
| **L4 destructive** | delete/prune/destroy | prohibited via gateway; operator-only, out of band |

## Hard prohibitions (never via gateway/agents)

- raw Docker socket access, privileged containers, root SSH
- ZFS-destroy authority, original-file deletion
- password-vault DB credentials, broad Nextcloud admin tokens
- automatic DNS mutation, public-exposure authority
- any caller-supplied shell/SQL/path/URL/container name/env var

`life-center-actions` is **not** MCP-exposed initially. When introduced, each
action is implemented and admitted separately under the security baseline.

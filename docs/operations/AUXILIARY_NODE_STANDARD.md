# Auxiliary-node standard

**Status:** deferred reference only. No auxiliary node is planned for the
initial Life Center deployment; no laptop is enrolled, receives credentials,
accesses VLAN 60, runs a worker, or contributes authoritative capacity.

This is the optional fourth tier beneath the desktop, Life Center, and MSI
laptop. It exists to reuse healthy old hardware without making recovery or core
services depend on it.

## Allowed roles

| Role | Purpose | Data/authority boundary |
| --- | --- | --- |
| `backup` | encrypted append-only critical backup | exclusive role; opaque ciphertext only; no delete/prune authority |
| `restore` | isolated restore drills | read-only repository access during a scheduled test |
| `cache` | replaceable artifacts | public/reproducible or non-sensitive cache only |
| `worker` | fixed, bounded jobs | registry inputs to staging outputs only |
| `ingest` | approved parsing/metadata jobs | no authoritative promotion |
| `gpu` | existing declared local GPU only | no production write or secrets |

`backup` cannot be combined with another role. No node is required for
production, may become a normal local production writer, or may contribute to
the Life Center’s authoritative capacity.

## Admission evidence

Before enabling a node, record private evidence for CPU/RAM/storage inventory,
SMART short and long tests, thermal/load test, battery and power-adapter safety,
predictable reboot, supported patched OS, full-disk encryption/recovery test,
firewall, suspend disabled during scheduled work, and deny/allow network tests.
Quarantine immediately on patch drift, SMART/thermal/battery failure, identity
or tag change, unexpected storage identity, unexplained outbound traffic, or
failed job validation.

Any future backup-controller role requires separately added healthy storage and
full qualification; it cannot replace the initial dedicated external backup
drive or off-site copy.

## Network and agents

Use separate Tailscale tags such as `tag:aux-backup`, `tag:aux-restore`,
`tag:aux-cache`, and `tag:aux-worker`. Tags are owned by an administrator; a
node cannot self-promote. Auxiliary VLAN access is deny-by-default and may only
reach the named artifact-read service, job queue, staging-write gateway,
approved DNS/NTP/update sources, and metrics ingest. It cannot reach router/BMC
administration, Docker APIs, databases, vaults, Home Assistant administration,
authoritative shares, or backup deletion.

The Command Center may eventually show sanitized health read-only. It has no
enrollment, shell, Docker socket, backup-delete, or arbitrary-job endpoint.
Fixed job manifests may name only registered artifact IDs, fixed job types,
resource limits, checksums, and staging outputs.

## Lifecycle

Every role remains preemptible: core services must pass when every auxiliary
node is powered off. Decommission by draining work, revoking identities,
removing registration, proving no authoritative data remains, securely erasing
sensitive cache, and recording sanitized completion evidence. Never pool old
laptop disks into a distributed filesystem or fragmented backup volume.

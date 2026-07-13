# Life Center security and recovery baseline

**Status:** mandatory design and deployment contract.  
**Reviewed:** 2026-07-13.  
**Applies to:** the future `life-center-infra` host, its storage, services,
backups, status/control gateway, Command Center boards, and agent access.

## Assurance statement

No architecture can honestly promise that data can never leak, hardware can
never fail, or a service can never be compromised. This baseline instead uses
defense in depth, least privilege, isolation, encrypted recoverable copies,
machine-verifiable gates, and explicit human approval for dangerous work. A
failed mandatory gate blocks real-data admission or the affected change.

The control families align with [NIST Cybersecurity Framework 2.0](https://www.nist.gov/news-events/news/2024/02/nist-releases-version-20-landmark-cybersecurity-framework),
[CIS Controls v8.1](https://www.cisecurity.org/controls/v8-1), and, for the custom
gateway/dashboard, [OWASP ASVS 5.0](https://owasp.org/www-project-application-security-verification-standard/).
Those frameworks guide the implementation; claiming certification requires a
separate assessment.

## Trust zones and failure assumptions

```text
Internet
  └── existing cloud website/API/CDN (public zone; no route into the home)

Tailnet / management zone
  ├── named administrator devices with MFA + device approval
  ├── Life Center SSH, metrics, backup administration, password manager
  └── llm_station -> redacted status/control gateway only

Services VLAN
  ├── Life Center application listeners and Home Assistant OS VM
  └── no arbitrary initiation toward personal clients or Management

IoT VLAN
  └── smart speakers, televisions, sensors; cannot initiate to Management

Trusted-client VLAN
  └── approved phones/computers -> explicitly allowed services

Guest VLAN
  └── internet only; no Services or Management

Life Center private container networks
  ├── databases and internal queues; never host-published
  └── service backends; minimum required east/west paths

Recovery zone
  ├── separate local backup, disconnected or immutable when not running
  └── encrypted off-site copy with keys stored separately
```

Assume a malicious internet client, stolen user/session credential, compromised
container or dependency, ransomware on a household endpoint, operator error,
agent prompt injection, disk failure, power loss, and theft/fire of the host.
Protect personal files, photos, vault data, smart-home state, website archives,
datasets, credentials, encryption/recovery keys, and audit/backup evidence.

## Mandatory controls

### 1. Host and physical security

- Install minimal supported Debian 13; remove/disable unused packages and
  listeners. Keep firmware, OS, Docker, and applications in an owned patch
  cadence. Apply security fixes promptly through a staged change window with a
  tested rollback or recovery path; do not blindly auto-update containers.
- Enable Secure Boot when the chosen hardware, storage stack, and recovery
  procedure support it. Use full-disk/data-pool encryption for data at rest,
  with recovery keys stored offline and separately from the server and backups.
- Use named administrator accounts and hardware-backed MFA for the identity
  provider where possible. Disable SSH password authentication and direct root
  login. Allow key-based SSH only from approved management identities/devices.
- Apply a default-deny host firewall. Bind no administrative service to public
  interfaces. Keep accurate time, persistent security/audit logs, and log
  rotation; forward only redacted alerts or append-only evidence.
- Use a UPS sized for clean shutdown. Test power-loss, unattended restart, disk
  unlock/recovery, and service restart behavior. Restrict physical access and do
  not leave recovery keys attached to the host.

### 2. Network and identity

- The current `SAX1V1R` Spectrum Wi-Fi 6 router is transitional and does not
  satisfy the required zone-segmentation evidence. Spectrum's documented wiring
  and the observed router identity establish a separate modem path. Gate 0
  selects a UniFi Dream Router 7 as the replacement gateway when the Life Center is staged; see
  [`LIFE_CENTER_GATE0.md`](LIFE_CENTER_GATE0.md). Keep the Spectrum modem/ONT,
  avoid permanent double NAT, and admit no real Life Center data until the new
  gateway's VLAN/firewall allow-and-deny tests pass.
- The selected physical layout keeps the modem, UDR7, and Life Center together
  upstairs on one UPS and uses a direct Cat6 access-VLAN run to the downstairs
  desktop. The Life Center port carries only Management as native and Services
  as tagged; the desktop port carries only Trusted untagged. The spare port is
  disabled. Do not substitute an unmanaged downstream switch.
- Tailscale policy is deny-by-default. Use grants/tags for named flows, separate
  human administration from service identities, require device approval, remove
  stale devices, and test expected allows and denies before every policy change.
- Replace the new-tailnet/default allow-all policy with explicit grants before
  admitting the Life Center. Tailscale governs tailnet flows, not ordinary LAN
  traffic; host firewall/VLAN rules remain mandatory.
- Do not enable public ingress, port forwarding, Tailscale Funnel, or an
  internet-facing reverse proxy for home administration. The public website has
  no inbound route to the Life Center.
- Use Tailscale Serve for explicitly approved private web entry points; it
  publishes within the tailnet, whereas Funnel is public. Funnel remains
  disabled. See [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
- Expose LAN services only where required. Use the service, IoT, trusted-client,
  guest, and management segmentation above when router capability permits.
  Database, Docker API, backup,
  hypervisor, metrics-admin, and secret-management ports remain management-only
  or unexposed.
- IoT cannot initiate to Management; Guest cannot reach Services/Management;
  Services cannot initiate arbitrary traffic to trusted clients; SSH is limited
  to the named management identity/group; AdGuard accepts DNS only from approved
  segments.
- AdGuard must never be an open resolver. Keep a tested fallback DNS path so a
  failed filter/update cannot strand the household or administration.

Tailscale grants are deny-by-default when no rule allows a connection; see the
[access-control behavior](https://tailscale.com/docs/features/access-control/acls),
[policy syntax](https://tailscale.com/kb/1337/policy-syntax), and
[device approval](https://tailscale.com/docs/features/access-control/device-management/device-approval).

### 3. Containers and software supply chain

- Use official or explicitly reviewed images. Pin immutable image digests in
  the deployment lock, record source/version/license, generate or retain an
  SBOM, scan vulnerabilities before promotion and on a schedule, and verify
  signatures/provenance where the publisher supports them. Cosign verification
  binds signatures to the image digest; see [Sigstore verification](https://docs.sigstore.dev/cosign/verifying/verify/).
- Run as a non-root UID and use rootless Docker where the service/storage/network
  requirements permit. Drop all Linux capabilities, add back only documented
  necessities, set `no-new-privileges`, use read-only root filesystems and
  `tmpfs` for temporary writes where compatible, retain seccomp/AppArmor, and
  set CPU/memory/PID/restart limits.
- Grant only narrow read/write mounts. Never mount `/`, the Docker socket,
  backup repositories, other services' config, or broad storage trees into an
  application. `privileged`, host PID/IPC, and host networking are prohibited
  unless a time-limited exception documents why no safer design works.
- A Docker daemon endpoint is root-equivalent. Do not expose it to the cockpit,
  agents, CasaOS extensions, or general services. Docker documents both the
  [daemon attack surface](https://docs.docker.com/engine/security/) and
  [socket protection requirements](https://docs.docker.com/engine/security/protect-access/).
- Promotion requires Compose validation, secret scan, dependency/image
  vulnerability scan, policy checks, backup, health probe, and a rollback plan.
  Updates are reviewed batches, not unbounded watchtower-style replacement.
- Renovate or an equivalent bot may propose digest/version changes through PRs;
  it receives no deployment or secret authority. Promotion order is proposal,
  review, scan/signature verification, staging, coherent backup, compatibility
  test, explicit approval, production deploy, smoke test, and rollback check.

### 4. Secrets and encryption keys

- No plaintext secret, token, password, private key, recovery code, or encrypted
  secret's decryption key enters Git, a board, prompt, model context, log, image,
  backup report, or screenshot.
- Store encrypted declarations with SOPS/age or an equivalent reviewed mechanism;
  inject values at runtime from restricted files/credentials. Keep decryption
  keys outside the repository and separate from the encrypted backups they open.
- Use unique per-service credentials and minimum scopes. Prefer read-only pull
  credentials for cloud archives. Inventory owner, scope, issue/rotation date,
  and revocation procedure without recording the value. Rotate after suspected
  exposure, device loss, operator departure, or according to service risk.

### 5. Data governance and storage integrity

- Classify each dataset as irreplaceable, expensive-to-recreate, reproducible,
  or sensitive. Assign an owner, allowed users/services, retention, backup tier,
  and deletion/restore procedure before ingestion.
- Separate personal, photo, media, website, CV, model, appdata, and backup
  datasets. Enforce least-privilege Unix ownership/ACLs and container mounts.
- Minimize copied personal data. Redact credentials, tokens, faces/identifiers,
  request bodies, query values, filenames, and file contents from telemetry and
  boards unless the use is explicit and access-controlled.
- Enable and schedule filesystem/pool checks, SMART monitoring, scrubs, and
  snapshot retention. Alert on disk faults, checksum errors, degraded mirrors,
  backup age, capacity at 70%, and unexpected growth. ZFS/RAID is availability,
  not backup.

### 6. Backups and recovery

- Maintain at least three copies on two media types/locations with one encrypted
  off-site copy. At least one recovery copy must be offline or immutable against
  the production host and its credentials. Follow the CISA
  [3-2-1 guidance](https://www.cisa.gov/sites/default/files/publications/data_backup_options.pdf).
- Back up application databases **and** their asset/data trees, configuration,
  encryption material, version manifests, and restore instructions. Schedule
  coherent application-aware snapshots; a database dump alone does not contain
  Immich photo/video assets.
- Adopt the initial class-specific RPO/RTO targets in `LIFE_CENTER_GATE0.md`
  until a documented impact/cost decision replaces them. Verify backup completion and repository
  integrity automatically; perform quarterly sampled file/database restores and
  an annual bare-host/disaster restore. A successful backup job without a tested
  restore is not accepted evidence.
- Keep deletion retention long enough to detect mistakes/ransomware and prevent
  the production host or a routine service token from deleting every copy.
- Separate append/write credentials used by routine backup jobs from a protected
  retention/prune credential. Compromise of the production host must not grant
  authority to erase all recovery generations.

Minimum restore cadence after each service becomes authoritative:

| Data/service | Minimum restore test |
| --- | ---: |
| password vault | monthly |
| Immich database plus representative asset | monthly |
| Nextcloud database plus representative files | quarterly |
| website snapshot | quarterly |
| Home Assistant | quarterly |
| representative CV dataset | quarterly |
| full server rebuild | annually |
| off-site-only recovery | annually |

A material version/storage/backup change triggers an additional restore test;
the calendar cadence is not permission to wait after a risky change.

### 7. Status/control gateway and dashboard

- Keep `life-center-status` MCP physically/logically read-only and summary-only.
  It cannot browse arbitrary paths or invoke the action gateway. Do not expose
  `life-center-actions` through MCP initially.
- The gateway publishes typed, minimal, redacted status records. It must not
  proxy arbitrary URLs, shell commands, SQL, filesystem paths, Compose/Docker
  arguments, or service-admin APIs.
- Authenticate machine calls with distinct short-lived service identity over
  the tailnet; also authorize each route/action. Protect mutations with strict
  schemas, exact allowlists, nonce/timestamp replay defense, rate limits,
  timeouts, CSRF protection where browser sessions exist, and standard secure
  headers. Never rely on network location as the only authorization factor.
- An action is an identifier mapped server-side to a fixed workflow. It records
  requester, approver, target, input hash, risk, start/end, result, evidence, and
  rollback. Validate state again immediately before execution; use idempotency
  keys and fail closed on stale status or uncertain results.
- Test the custom surface against the applicable OWASP ASVS 5.0 requirements,
  including authentication, session, access control, input, API, logging, and
  cryptography controls.

### 8. Agent authority

Agents may see redacted service state and propose work. They do not inherit a
human administrator's session, vault, Docker socket, SSH key, filesystem, or
service tokens.

| Tier | Examples | Rule |
| --- | --- | --- |
| L0 | documentation/catalog reads | automatically allowed from sanitized sources |
| L1 | health, capacity, backup-age, version reads | automatically allowed; audit every request |
| L2 | fixed stateless diagnostic or cache refresh | disabled initially; later per-action approval and rate limit |
| L3 | app update/migration or bounded restore | explicit signed human approval for the exact target/change, with preflight and rollback |
| L4 | delete originals/backups, destroy pool, change DNS/router/Tailscale policy, reveal/export vault, change recovery keys, enable public exposure | structurally unavailable to agents; human-only offline procedure |

Prompt or content retrieved from files, websites, media metadata, logs, email, or
boards is untrusted data and cannot grant authority or alter policy. Board cards
contain summaries and evidence references, never sensitive payloads.

### 9. Service-specific minimums

- **Nextcloud:** use a dedicated domain, HTTPS/HSTS, data and sensitive config
  outside the web root, security headers, brute-force/fail2ban controls, and
  restricted admin access. Segment it because its feature set can make outbound
  requests. Follow the official [hardening guide](https://docs.nextcloud.com/server/latest/admin_manual/installation/harden_server.html).
- **Immich:** preserve both database and library/asset volumes, test version-
  matched restores, and keep irreplaceable originals outside a single
  application failure domain. Follow its [backup/restore guide](https://docs.immich.app/administration/backup-and-restore/).
- **Password manager:** do this last. Keeping Bitwarden cloud is safer than a
  self-hosted instance whose operator cannot patch or restore it reliably. For
  self-hosting, prefer an official supported Bitwarden deployment; Bitwarden
  Lite is its lightweight personal/home-lab option and is documented for Docker
  Engine 26+. Use tailnet-only HTTPS,
  disable open registration, tightly restrict any administrator portal, require
  strong MFA, maintain complete encrypted backups, and prove client access plus
  offline export/recovery. Bitwarden explicitly notes that it cannot guarantee
  official-client compatibility with non-official servers such as Vaultwarden;
  choose Vaultwarden only through a written risk/maintenance decision. See the
  official [Bitwarden Lite deployment](https://bitwarden.com/help/install-and-deploy-lite/),
  [self-hosting options](https://bitwarden.com/help/self-host-bitwarden/), and
  [hosting FAQ](https://bitwarden.com/help/hosting-faqs/).
- **Home Assistant:** begin with HA OS in an isolated VM or dedicated device;
  minimize integrations, use separate IoT identities/VLAN where possible, and
  make critical physical functions work safely when HA, DNS, or the network is
  unavailable. Home Assistant identifies HA OS as the recommended installation
  type; see its [installation comparison](https://www.home-assistant.io/installation/).
- **AdGuard Home:** LAN-only DNS, restricted administration, no public recursion,
  versioned configuration backup, and a documented/tested fallback resolver.

## Deployment and data-admission gates

Every gate produces dated, immutable or versioned evidence in the future private
infrastructure repository or backup evidence store. Secret values are always
redacted.

| Gate | Required evidence | Blocks |
| --- | --- | --- |
| G0 inventory/threat model | hardware IDs, current bytes/retained growth, data classes/owners, trust map, router capability, RPO/RTO, retention, three-year capacity/cost forecast, backup/off-site/UPS plan | hardware/data-layout commitment |
| G1 host/network | patch status, disk encryption/recovery test, firewall/listeners, SSH/MFA, Tailscale allow/deny tests, UPS shutdown/restart | installing real services/data |
| G2 storage/recovery | healthy mirror, SMART baseline, scrub, snapshots, separate encrypted backup, successful sample restore | ingesting irreplaceable data |
| G3 service pilot | pinned images, Compose/policy checks, vulnerability + secret scans, least-privilege inspection, dummy-data restore | real data in that service |
| G4 service production | auth/access tests, logs/alerts, RPO/RTO restore, upgrade/rollback rehearsal | declaring service authoritative |
| G5 read-only cockpit | typed redaction tests, route authorization, no Docker/socket/root access, audit and failure tests | exposing status to Command Center/agents |
| G6 mutations | per-action threat review, schema/fuzz/replay/auth tests, explicit approvals, idempotency, rollback drill | enabling each individual action |

Minimum automated checks include:

- resolved Compose configuration and immutable image-digest policy;
- container inspection for UID, privileges, capabilities, security options,
  mounts, networks, published ports, and resource limits;
- host listener/firewall and Tailscale policy allow/deny tests;
- secret scanning plus image/dependency vulnerability and SBOM checks;
- `zpool status`, scheduled scrub/SMART results, capacity, snapshot age, backup
  age/integrity, and a recorded restore result (or equivalent for ext4);
- TLS/certificate/security-header, authentication, authorization, rate-limit,
  CSRF, replay, injection, and redaction tests for the gateway;
- audit-log completeness and alert delivery using a safe canary event.

Passing once is not permanent. Re-run the relevant gates after hardware,
firmware, network, identity, storage, image, service, policy, gateway, or backup
changes.

## Exceptions and incidents

An exception must name the control, owner, business reason, affected assets,
risk, compensating control, evidence, review date, and expiry. An unowned or
expired exception fails its gate.

Maintain an offline incident runbook: isolate the host without destroying
evidence; revoke sessions/tokens/devices; rotate credentials from a known-clean
device; preserve relevant logs; identify scope; rebuild from pinned trusted
artifacts; restore from a pre-incident clean copy; verify integrity; and record
lessons/control changes. Practice the contact and recovery sequence annually.

Create and exercise scenario-specific runbooks for:

- one HDD failure and replacement/resilver;
- both primary drives unavailable;
- appdata NVMe failure and full host/motherboard failure;
- accidental photo deletion and corrupted Immich database;
- compromised Tailscale identity, stolen phone, and lost password-vault second
  factor;
- ransomware on the desktop and malicious/mistaken agent action;
- failed application upgrade and DNS/AdGuard outage;
- utility-power loss and UPS exhaustion;
- cloud account loss; and
- website/database recovery using only the validated local archive.

Each runbook declares trigger, isolation steps, safe evidence collection,
credential revocations, recovery source, verification, RPO/RTO expectation,
owner, and the condition for returning to service.

## Security board summary

The cockpit may show only sanitized facts: patch/vulnerability status, certificate
expiry, failed-auth trend, service health, disk/pool state, capacity, last scrub,
last successful backup, last verified restore, RPO/RTO compliance, active
exceptions, and incident state. Green service health must never hide stale or
untested backups.

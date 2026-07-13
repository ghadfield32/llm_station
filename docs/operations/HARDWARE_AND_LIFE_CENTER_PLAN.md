# Hardware, workload, and Life Center operating decision

**Status:** adopted architecture; the desktop memory gate is resolved, while
Life Center implementation remains gated by the verification items below.  
**Reviewed:** 2026-07-13 (revised after the DDR5 replacement).  
**Scope:** the RTX 4090 desktop, MSI RTX 5080 laptop, Betts Basketball/CV
workloads, local models, and the proposed personal Life Center.

This document reconciles two earlier proposals that disagreed about the laptop
and about where the always-on control plane should live. It records verified
facts separately from reported-but-unverified facts and future design choices.

## Decision

Use three distinct roles:

```text
Desktop "vengeance" — always-on compute and current control plane
├── Betts Basketball DAGs, website support, backfills, and production publishing
├── heavy computer vision and statistical work
├── primary Ollama/local-model runtime
├── llm_station control plane and cockpit (current Option C)
└── only normal local production R2 writer

MSI laptop — portable human and bounded development lane
├── interviews, presentations, coding, browser/UI testing
├── VS Code/Tailscale client into the desktop
├── live or sample-scale CV and Blackwell compatibility testing
├── 16 GB-fit local models and embeddings while intentionally online
└── read-only production access; explicit, staging-only emergency compute

Future stationary Life Center host — stable data/application appliance
├── 12 TB-class mirrored storage (about 10.91 TiB usable before reserve)
├── Nextcloud, Immich, Jellyfin, books/audio, monitoring, and backups
├── AdGuard Home only after DNS recovery is tested
├── password manager only after backup/restore and recovery are proven
└── Home Assistant OS in an isolated VM initially, or a dedicated device later

Old laptops — deferred optional recovery/utility tier
├── future restore test, replaceable cache, or bounded worker only when separately admitted
├── no initial backup, storage, or network dependency
└── never a distributed filesystem or production dependency
```

The laptop must not be the only host or only data copy for household services.
It is intentionally mobile and sometimes powered off. The desktop remains the
best existing compute host because it is stationary, always on, has more VRAM,
has more cooling and expansion capacity, and already holds the data locality and
operational state for Betts and computer vision.

The durable end state adds a stationary storage host. Until then, home services
may be tested on the desktop with noncritical sample data, but the desktop is not
the permanent Life Center because Betts, CV, model inference, Docker, and WSL
already contend for the same CPU, memory, disk, and reboot window.

The precise backup, appdata-NVMe, and purchase gates are maintained in
[`LIFE_CENTER_IMPLEMENTATION_READINESS.md`](LIFE_CENTER_IMPLEMENTATION_READINESS.md).
The optional fourth-tier admission and containment rules are in
[`AUXILIARY_NODE_STANDARD.md`](AUXILIARY_NODE_STANDARD.md).

## Evidence quality and corrections

| Claim | Status | Basis / consequence |
| --- | --- | --- |
| Laptop is an RTX 5080, not a 5090 | **Verified** | The supplied Windows inventory identifies an MSI Vector 16 HX AI `A2XWIG`; MSI maps `A2XWIG` to an RTX 5080 Laptop GPU with 16 GB GDDR7. Every 5090 reference in the second proposal is rejected. |
| Laptop CPU is Core Ultra 9 275HX | **Verified** | Supplied inventory plus Intel/MSI specifications. |
| Laptop has about 32 GB RAM and one visible 2 TB Samsung NVMe | **Observed** | Supplied Windows inventory. Module count, health, free capacity, and whether the second M.2 position is physically free still require inspection. |
| Desktop is Corsair Vengeance i7400 `CS-9050063-NA`, i9-12900K/RTX 4090/64 GB/2 TB | **Verified model configuration** | Corsair product specification; live `nvidia-smi` in this review confirmed RTX 4090 and 24,564 MiB VRAM. Current DIMM and SSD identities still require inventory. |
| Desktop has 24 CPU threads and 64 GB host RAM | **Repo-recorded** | Existing measured evidence in `docs/MASTER.md`; WSL is recorded as capped at 48 GB with 16 GB swap. |
| Desktop previously failed memory tests | **Resolved by repair; operator-confirmed** | A new DDR5 kit was installed and the desktop has since been tested and reported reliable. The former production gate is closed. Preserve the exact kit, slot, BIOS/XMP, memory-test, and post-repair stress evidence as an operational baseline; this is evidence housekeeping, not a reason to demote the desktop. |
| Laptop has a prior fan/thermal concern | **Reported, unresolved** | Sustained GPU work is conditional until both fans, clocks, temperature, and power behavior pass a logged load test. |
| Desktop hosts all current control-plane services | **Verified in repo** | The adopted Option C is desktop + Tailscale, no VPS; see [`remote-access.md`](remote-access.md). |
| Railway/VPS is the current `llm_station` control plane | **Rejected** | That is a Betts-specific future architecture idea, not the current Command Center deployment. Do not silently reintroduce a VPS into this repo's plan. |

Vendor references:

- [MSI Vector 16 HX AI specification](https://us.msi.com/Laptop/Vector-16-HX-AI-A2XWX/Specification)
- [Intel Core Ultra 9 275HX specification](https://www.intel.com/content/www/us/en/products/sku/242293/intel-core-ultra-9-processor-275hx-36m-cache-up-to-5-40-ghz/specifications.html)
- [Corsair Vengeance i7400 `CS-9050063-NA`](https://www.corsair.com/us/en/p/gaming-computers/cs-9050063-na/vengeance-i7400-gaming-pc-i9-12900k-rtx-4090-2tb-m-2-64gb-ddr5-5600-cs-9050063-na)
- [MSI PRO Z690-A WIFI specification](https://www.msi.com/Motherboard/PRO-Z690-A-WIFI/Specification)

Firmware release numbers change. Always re-check the exact vendor support page
and exact SKU immediately before an update; this document does not prescribe a
specific firmware version.

## Recorded machine inventory

### MSI laptop

| Item | Recorded detail | Confidence / note |
| --- | --- | --- |
| Product | MSI Vector 16 HX AI A2XWIG; supplied record associates it with `A2XWIG-058US` | Model family observed; confirm the retail suffix from the bottom label or MSI registration before parts/firmware work. |
| Platform identifiers | System SKU `15M3.1`, product revision `REV:1.0` | Supplied Windows inventory. |
| CPU | Intel Core Ultra 9 275HX; 24 cores / 24 threads (8P + 16E), up to 5.4 GHz | Inventory plus Intel specification. CPU base/max power figures describe limits, not sustained chassis performance. |
| Discrete GPU | NVIDIA GeForce RTX 5080 Laptop GPU, 16 GB GDDR7 | Model mapping and MSI specification. This is not a 5090. |
| Other display devices | Intel integrated graphics, Parsec Virtual Display Adapter, Meta Virtual Monitor | The virtual adapters are not CUDA devices. |
| System RAM | 31.4 GiB usable; retail record says 32 GB | Exact module count/part numbers and health are not yet captured. |
| Storage | Samsung `MZVL22T0HDLB-00BT7`; about 1.91 TiB visible | Free space, wear, thermals, and physical M.2 occupancy remain unverified. |
| Firmware observed | BIOS `E15M3IMS.107`, dated 2025-02-26 | Do not infer the correct update solely from a newer version number; match exact model and follow MSI's support process. |
| Expansion/capability | Family provides two SO-DIMM slots, two M.2 positions (one Gen5 x4 and one Gen4 x4), two Thunderbolt 5 ports, 2.5 GbE, and a 90 Wh battery | Inspect actual occupancy and exact regional configuration before purchasing. |
| Display | Retail record says 2560×1600, 240 Hz | Confirm actual panel identity if color/refresh characteristics matter to interview/demo work. |
| Open health question | Prior fan/noise concern | Sustained workload use remains gated by logged thermal validation. |

### Corsair desktop

| Item | Recorded detail | Confidence / note |
| --- | --- | --- |
| Product | Corsair Vengeance i7400, SKU `CS-9050063-NA` | Corsair specification and supplied record. |
| CPU | Intel Core i9-12900K; 16 cores / 24 threads (8P + 8E), up to 5.2 GHz | Product and Intel specification. |
| GPU | NVIDIA GeForce RTX 4090, 24 GB-class VRAM | Product specification; live 2026-07-13 query reported 24,564 MiB. |
| System RAM | New DDR5 installed; 64 GB host RAM remains repo-recorded | Post-repair testing is operator-confirmed reliable. Record the exact replacement kit, slot population, negotiated speed, and XMP state in the machine inventory. |
| Storage | Product configuration 2 TB M.2 NVMe; no factory secondary drive | Exact current SSD, health, free space, and added drives require inventory. |
| Motherboard | MSI PRO Z690-A WIFI DDR5 | Supplied record; board specification provides 4 M.2 and 6 SATA ports. Inspect physical occupancy/clearance. |
| Cooling | Corsair iCUE H100i-class sealed 240 mm CPU liquid cooler; air-cooled GPU | Pump/fan health is not established by the product specification. |
| Power/chassis | 1000 W 80 Plus Gold modular PSU; Corsair 4000-series ATX chassis | Product specification. |
| Network | 2.5 GbE, Wi-Fi 6E | Product specification; negotiated wired rate remains to be measured. |
| Point-in-time GPU snapshot | Driver `591.86`; 40 °C; 17% GPU utilization; 1,802 MiB used | Diagnostic snapshot only, not a load or thermal qualification. |
| Resolved health issue | Prior memory-test failures; replacement DDR5 installed and tested | No longer a production blocker. Retain the evidence and watch WHEA/errors as part of normal regression monitoring. |

The motherboard may advertise memory capacities beyond what the installed
i9-12900K generation conservatively supports. Do not buy a large desktop RAM
upgrade from the board maximum alone; check the CPU limit, Corsair support
posture, BIOS path, and the exact board QVL. Likewise, the laptop's platform
maximum does not guarantee that every 64/96 GB kit is stable in this unit.

## Hardware comparison

| Area | Desktop | Laptop | Operating implication |
| --- | --- | --- | --- |
| System | Corsair Vengeance i7400 | MSI Vector 16 HX AI A2XWIG | Desktop is stationary; laptop is portable. |
| CPU | Intel Core i9-12900K, 16 cores / 24 threads | Core Ultra 9 275HX, 24 cores / 24 threads | Laptop may win selected bursty/newer-architecture CPU tasks; measure real pipelines. Desktop has the sustained cooling/power advantage. |
| GPU | RTX 4090 desktop, 24 GB GDDR6X | RTX 5080 Laptop, 16 GB GDDR7 | Desktop owns large models, long CV, larger batches, and concurrency. Laptop owns bounded Blackwell compatibility and live/demo work. |
| Installed RAM | new DDR5; 64 GB host RAM repo-recorded and post-repair operation reported reliable | about 32 GB observed | Desktop capacity wins. Laptop is adequate for normal development, not every Docker/WSL/model service at once. |
| Base storage | 2 TB NVMe product configuration | one visible 2 TB Samsung NVMe | Neither is the permanent 12 TB-class archive. |
| Expansion | Board supports 4 M.2 and 6 SATA; chassis/cable clearance must be inspected | Platform family supports 2 M.2; free position must be inspected | Desktop is the better scratch/model expansion target. A stationary multi-bay host is better for redundant bulk storage. |
| Network | 2.5 GbE product configuration | 2.5 GbE platform configuration | Use wired Ethernet for stationary transfers and workers. Verify negotiated link rate. |
| Availability | Always on by user policy | Sometimes off / mobile | No household dependency may require the laptop. |
| Cooling | 240 mm CPU AIO, desktop GPU airflow | shared mobile thermal system | Laptop long jobs are conditional and checkpointed. |
| Best human use | Remote target, production dashboards | interviews, coding, demos, travel | Keep the laptop clean and responsive. |

Hardware specifications describe capability, not present health. They do not
prove that a DIMM, SSD, fan, pump, battery, or port is healthy.

## Workload ownership

| Workload | Primary | Secondary / failover | Authority boundary |
| --- | --- | --- | --- |
| Betts Airflow and full historical backfills | Desktop | None automatically | Resource-capped; post-repair monitoring and artifact validation remain mandatory. |
| Betts website/public API coordination | Current deployed service(s), documented in Betts | Desktop worker | Do not infer a new Railway/VPS dependency here. |
| Production R2 writes and promotion | Desktop only | Laptop only through an explicit emergency-writer procedure | One writer, unique lease/idempotency key, staging first, validation before promotion. |
| Heavy CV, 3D CV, segmentation, full-video batches | Desktop | Laptop only when job fits and is bounded | Schedule by VRAM/RAM/scratch/thermal health, not hostname alone. |
| Live camera, demo clips, UI/API development | Laptop | Desktop | Laptop writes development/staging artifacts only. |
| Full Bayesian/GBDT/data-engineering runs | Desktop | Laptop for sample/shadow runs | Production artifacts follow the same single-writer rule. |
| Active 20–32B-class quantized LLMs and long context | Desktop | None unless a measured 16 GB fit exists | The 24 GB route stays primary and fail-closed. |
| 7–14B models, embeddings, rerankers, compatibility experiments | Laptop when online | Desktop | Laptop endpoint is optional; loss of it must not break the system. |
| Coding, interviews, presentations, browser testing | Laptop | Desktop locally | Laptop stays usable even when infrastructure is busy. |
| Nextcloud/Immich/Jellyfin/password manager/AdGuard | Future Life Center host | Desktop test profile only | Never laptop-dependent; no production originals during pilot. |
| Home Assistant | Isolated HA OS VM or dedicated device | None | Essential automations must survive desktop and laptop GPU maintenance. |

### Resource-based scheduling

The machine names express policy, but jobs should declare actual needs:

```yaml
resources:
  gpu_required: true
  minimum_free_vram_gb: 20
  estimated_system_ram_gb: 40
  estimated_scratch_gb: 300
  sustained_runtime_class: long
permissions:
  production_read: true
  production_write: false
compatibility:
  cuda_architectures: [ada, blackwell]
```

Selection must consider CUDA/runtime compatibility, free VRAM, free RAM,
scratch capacity, queue depth, thermal health, data locality, role, and write
permission. Static `gpu_vram_gb` remains useful for fit preflight, but live
telemetry is required before dispatch.

The existing fleet contract remains authoritative:

- Desktop: production orchestrator/heavy worker and only normal production R2
  writer.
- Laptop: development/candidate lane, production read-only, `.r2_staging`
  writes only.
- Never grant both machines ordinary production-write authority in the name of
  redundancy; that creates split-brain publication.

## Storage responsibilities

### Desktop fast storage

Use local NVMe for working state:

- Windows, WSL, Docker, repositories, and active databases;
- Betts/CV scratch, frame caches, decoded video, and current batches;
- active model weights, current checkpoints, and current training/evaluation
  sets.

A future expansion may separate OS/WSL, CV scratch, and model/checkpoint I/O,
but physical slot occupancy, GPU clearance, cooling, lanes, and SSD health must
be inventoried first. The desktop's local disks remain working caches; canonical
Betts artifacts follow the target repo's R2/manifest contract.

### Laptop fast storage

Keep repositories, representative clips, demo assets, development databases,
and a bounded 16 GB-fit model cache. A second NVMe is attractive for models and
development cache only after the slot is physically confirmed and thermal
behavior is understood. It is not a substitute for server storage or backup.

### Future Life Center storage

Use separate media for separate failure and performance needs:

```text
SSD/NVMe: Debian, containers, databases, logs, thumbnails, caches
mirrored HDD pool: documents, original photos, personal video, media, books
separate local backup: recovery from deletion/corruption/pool failure
encrypted off-site backup: irreplaceable data
```

Recommended current default: two 12 TB CMR drives mirrored (about one drive's
usable capacity), a 1–2 TB NVMe SSD for OS/appdata/databases, a separate backup
disk, and off-site protection for irreplaceable data. A 10 TB pair remains valid
when measured retained data and growth fit it comfortably or its purchase-day
value is materially better. Mirroring improves availability; it does not protect
against deletion, ransomware, application corruption, fire, or theft.

Use a four-bay-or-larger chassis even if only two bays are populated. A two-drive
mirror is a good first pool; a two-bay enclosure makes the first expansion needlessly
disruptive.

### Capacity and July 2026 purchase range

Drive makers quote decimal terabytes. A `2 x 10 TB` mirror provides **10 TB
decimal**, approximately **9.09 TiB**, not 20 TB of usable storage. Keeping 20%
free for snapshots, rewrites, and safe operation leaves approximately **7.27
TiB** as the planned working ceiling.

The purchase-day decision should use new, warranty-backed, CMR NAS drives from
an authorized seller. The 2026-07-13 retail snapshot supports these planning
figures before tax:

| Purchase | Planning figure | Decision rule |
| --- | ---: | --- |
| Two new 10 TB CMR NAS HDDs | **$750–$850 target**; roughly **$680–$950 observed range** | Reject used/refurbished/unknown-seller drives for the primary irreplaceable-data pool. |
| Two new 12 TB CMR NAS HDDs | commonly about **$800–$860** at current full-price listings | **Current default:** prefer 12 TB when the pair costs no more than roughly 15% above the comparable 10 TB pair. |

These figures exclude the host, appdata SSD, separate backup media, UPS, cables,
and encrypted off-site storage. Prices are volatile; re-check seller,
manufacturer warranty, model number, workload rating, noise, power, and CMR
recording immediately before ordering. Current examples include the
[Seagate IronWolf data sheet](https://www.seagate.com/content/dam/seagate/en/content-fragments/products/datasheets/ironwolf-12tb/ironwolf-16tb-DS1904-22-2404US-en_US.pdf),
[WD Red Plus product/models page](https://www.westerndigital.com/products/internal-drives/wd-red-plus-sata-3-5-hdd),
[Best Buy 12 TB listing](https://www.bestbuy.com/product/seagate-ironwolf-12tb-nas-internal-hard-drive-with-rescue-data-recovery-services/J37C5HWKZG),
and [Newegg 10 TB WD Red Plus listings](https://www.newegg.com/p/pl?d=wd+red+plus+10tb).

Structured website records and model manifests are small; retained video is the
capacity driver. Approximate encoded-video consumption is:

| Average bitrate | Storage per hour | Approximate hours in 7.27 TiB |
| ---: | ---: | ---: |
| 8 Mb/s | 3.6 GB | 2,220 hours |
| 25 Mb/s | 11.25 GB | 710 hours |
| 50 Mb/s | 22.5 GB | 355 hours |

The last column is an upper bound before photos, files, backups, snapshots,
models, and appdata. Extracted lossless frames can consume hundreds of GB per
hour, so frame caches and reproducible intermediates must have short retention.
A 10 TB mirror is therefore an adequate **curated starter**, not an unlimited CV
archive. Before purchase, inventory current bytes and monthly growth by class,
forecast three years, alert at 70% pool use, and have an expansion or eviction
plan before 80%.

A `2 x 12 TB` mirror provides **12 TB decimal**, approximately **10.91 TiB**,
with a planned 20%-reserve ceiling of approximately **8.73 TiB**—about **1.46
TiB** more working space than the 10 TB pair. Start with 16 TB-class drives
instead if retained inventory is already above about 5 TB or measured retained
growth exceeds about 1.5 TB/year. These are purchasing triggers, not substitutes
for the inventory and three-year forecast.

### Life Center host specification

Prefer a used/reused, serviceable standard tower over a sealed mini-PC or
laptop:

```text
four-or-more-bay tower
├── Intel CPU with integrated graphics for routine media transcoding
├── 32 GB RAM
├── 1–2 TB NVMe for Debian, appdata, databases, logs, metadata, and caches
├── 2 x 12 TB CMR NAS HDDs initially
├── two empty bays for a later second mirror
├── wired 2.5 GbE where practical
├── known-good SATA/controller path and direct drive visibility
├── active drive cooling and straightforward replacement parts
└── UPS sized and tested for clean shutdown
```

Confirm the exact chassis bays, power connectors, SATA controller behavior,
drive temperature/airflow, idle power, Linux hardware support, and replacement
parts before purchase. Do not use USB-attached disks for the primary mirror.
Integrated graphics is sufficient for routine Jellyfin work; keep the RTX GPUs
available for workloads that benefit from them.

### Local website and project archive

Yes: the Life Center should retain owner-controlled project data that is too
valuable or expensive to leave only in a cloud account. This complements the
cloud; it does not move the public production edge into the home.

```text
/tank/personal        documents and personal files
/tank/photos          original photo/video library
/tank/media           legally held movies, television, books, and audio
/tank/site-archive    versioned database dumps, object snapshots, exports, manifests
/tank/cv-archive      source video, annotations, curated datasets, final analyses
/tank/models-archive  hard-to-recreate checkpoints, adapters, evals, provenance
/srv/appdata          service databases/config on SSD, backed up separately
```

For a 12 TB mirror, use these as soft dataset budgets against the 8.73 TiB
planning ceiling. Implement per-dataset quotas/reservations where supported so a
runaway CV task cannot consume space needed for photos, databases, or recovery.

| Dataset | Initial planning budget |
| --- | ---: |
| Personal files, documents, and photos | 1.50 TiB |
| Website snapshots and databases | 0.75 TiB |
| Curated CV sources and final results | 2.50 TiB |
| Models, adapters, and evaluations | 1.25 TiB |
| Movies, television, music, and books | 1.50 TiB |
| Operational headroom and growth | 1.23 TiB |

These are reviewable starting allocations, not permanent entitlements.

Keep the website/API/CDN at its existing cloud edge. A scheduled, least-privilege
pull job should make validated, versioned local copies; the home server should
not become a public origin, deployment credential broker, or ordinary
production writer. Restore drills must prove that the archive is useful. Keep
cloud credentials scoped read-only where possible, redact secrets and
unnecessary personal data, and record hashes, schema/application versions, and
the restore procedure with each snapshot.

The archive path is pull-only by default:

```text
cloud source -> read-only export -> staging -> malware/schema/hash/count checks
             -> versioned archive -> restore test -> retention classification
```

Each database snapshot records the dump, schema and application versions,
source timestamp, row/object counts, SHA-256 manifest, encryption metadata,
restore command, and restore-test result. Source/object paths should be expanded
into clear subdatasets such as consented source video, annotations, gold eval
assets, final clips/results, published derivatives, model cards, licenses, and
hash manifests.

### CV and model retention defaults

Permanently protect permitted irreplaceable source video, human annotations,
gold evaluation assets, final structured outputs, important detected events,
published derivative datasets, evaluation evidence, and hard-to-recreate
fine-tunes. Reproducible bulk artifacts expire unless explicitly promoted:

| Artifact | Initial retention |
| --- | ---: |
| decoded frame caches | 3–7 days |
| failed pipeline scratch | 7 days |
| temporary transcodes/crops | 14 days |
| reproducible intermediates | 30 days |
| selected review clips | retain only by explicit promotion |
| gold labels and irreplaceable sources | permanent, backed up by class |

Incomplete model downloads, duplicate quantizations, unused base weights,
optical-flow caches, and conversion scratch are disposable. Store retention in
versioned policy—not hard-coded application defaults—and revise it from measured
reuse and retained-growth evidence.

Data classes:

- **A — irreplaceable:** photos, personal videos, documents, scans, vault
  recovery, Home Assistant configuration. Primary + redundant local + separate
  local backup + encrypted off-site + restore tests.
- **B — expensive to recreate:** annotations, curated datasets, fine-tuned
  adapters, embeddings, evaluation artifacts, website database/object exports,
  and organized book metadata. Local backup and selective off-site protection.
- **C — reproducible:** public base models, container images, generated
  thumbnails, caches, legally reacquirable media. Preserve catalog, license,
  source revision, and hashes; redownload where economical.

The model-storage resolution differs from the rejected 5090 proposal:

1. Desktop NVMe is Tier 1 for active production models.
2. Laptop NVMe is a bounded, optional mobile cache.
3. The Life Center may hold a validated model archive, but should not serve
   weights directly into latency-sensitive inference over the network.
4. Incomplete downloads, duplicate quantizations, and conversion scratch are
   disposable.

## Reliability gates

### Desktop post-repair baseline

**Status: passed by operator report.** The failed memory was replaced with new
DDR5 and the desktop has been tested as reliable. The desktop may resume its
normal authoritative role. Complete and retain this baseline so a future
regression is detectable:

1. Record the exact installed DIMMs, slots, BIOS, negotiated speed, voltage, and
   XMP state.
2. Preserve the zero-error memory-test result and representative CPU/RAM and
   combined CPU/RAM/GPU stress results.
3. Verify no WHEA errors, crashes, throttling, or data-integrity failures during
   the post-repair sample.
4. Record cooler pump/fan health, SSD health/free space, and negotiated Ethernet.
5. Verify reboot recovery: Docker/WSL, Tailscale, Airflow, Command Center, and
   monitoring return without manual repair.
6. Add a UPS and restore-after-power-loss policy before calling the desktop
   resilient to utility-power loss.
7. Repeat memory and event-log checks after BIOS/memory-profile changes or any
   unexplained crash, checksum mismatch, or model/data corruption.

The i9-12900K's official DDR5 support is lower than the prebuilt's advertised
DDR5-5600 XMP profile. Stable operation is more valuable than a marginal memory
speed increase; do not enable or raise XMP without a fresh validation cycle.

### Laptop gate before sustained GPU work

1. Confirm exact RAM modules, M.2 occupancy, SSD health/free space, and battery
   health.
2. Use `nvidia-smi` or the runtime API—not the 32-bit WMI `AdapterRAM` field—to
   confirm 16 GB VRAM and the configured power limit.
3. Confirm both fans and log temperature, power, clocks, VRAM, and throttling
   during a representative sustained workload.
4. Use the original adapter, a documented performance profile, battery charge
   limit when docked, and a lid/sleep policy that cannot suspend an active job.
5. Bound WSL/Docker memory and disk growth; checkpoint mobile jobs frequently.
6. Re-check the exact MSI support page before firmware changes. Suspend
   BitLocker and preserve recovery information according to MSI/Microsoft
   procedures; do not update firmware while cooling/repair questions remain.

An upgrade to 64 or 96 GB may help Docker/WSL/agents and CPU-offload workflows,
but it does not change the laptop's 16 GB VRAM, mobility, cooling, or availability
role. Upgrade only after confirming MSI-supported modules and the actual slot
configuration.

## Life Center architecture and repository boundary

The Life Center is a separate infrastructure product, not another profile in
this repository's main Compose stack.

The preferred foundation is a minimal, supported **Debian 13** host, Docker
Engine with Compose, an SSD for the OS/appdata, and a mirrored HDD data pool.
Debian 13 is the current stable Debian release. OpenZFS supports Debian 13 and
provides checksums, scrubs, snapshots, and mirror management, but its
`contrib`/DKMS lifecycle adds operational work. Use ZFS when that lifecycle and
restore drills are acceptable; use a simple ext4 mirror/backup design for a
small pilot if it will be operated more reliably. Neither filesystem nor RAID is
a backup. See [Debian 13](https://www.debian.org/releases/trixie/index.en.html)
and the [OpenZFS Debian guide](https://openzfs.github.io/openzfs-docs/Getting%20Started/Debian/index.html).

The mandatory security and verification contract is
[`LIFE_CENTER_SECURITY_BASELINE.md`](LIFE_CENTER_SECURITY_BASELINE.md). No real
personal data or vault migration begins until its applicable gates pass.
The first measured desktop inventory, automated growth tracking, provisional
purchase selections, resolved Spectrum router/separate-modem topology, recovery
targets, and remaining Gate 0 exits are recorded in
[`LIFE_CENTER_GATE0.md`](LIFE_CENTER_GATE0.md).

### `llm_station` owns

- high-level architecture and service inventory;
- typed Life Center board surfaces;
- read-only health summaries and backup-age/SLO alerts;
- proposed maintenance missions and approval evidence;
- allowlisted low-risk requests only after a separate pilot.

It must not receive unrestricted Docker socket access, root SSH, ZFS-destroy
authority, password-vault database credentials, broad Nextcloud administration,
automatic DNS mutation, original-file deletion, or public-exposure authority.

### A future private `life-center-infra` repository owns

- Debian/Compose definitions and pinned versions;
- storage/filesystem layout;
- firewall, Tailscale ACL, and service exposure;
- secrets references (never plaintext secrets);
- backup, restore, retention, and disaster-recovery runbooks;
- health probes and restore-test evidence;
- the optional CasaOS decision.

CasaOS may later be evaluated as a convenience launcher over noncritical test
services. It is not the canonical deployment, backup system, secrets manager,
upgrade authority, or security boundary. Do not place it between operators and
the evidence needed to understand the actual Compose, network, storage, and
backup configuration. Its [official repository](https://github.com/IceWhaleTech/CasaOS)
describes an open-source personal-cloud UI/platform; that convenience does not
replace the narrower least-privilege gateway required here. As checked on
2026-07-13, its [release page](https://github.com/IceWhaleTech/CasaOS/releases)
labels `v0.4.15` latest and `v0.4.17-alpha1` prerelease. That is not evidence of
insecurity; it is another reason to keep a convenience layer replaceable and
outside the canonical security/operations contract.

### Dashboard and Kanban decision

Do **not** build a general CasaOS clone, and do not make CasaOS the management
brain. Extend the existing Command Center cockpit with a narrow **Life Center
surface** backed by a separate status/control gateway on the Life Center host.
That gives one place to understand work without merging trust domains or giving
agents household-admin access.

Initial boards:

- Life Center overview: service availability, storage, backup age, alerts;
- files and cloud: Nextcloud sync, capacity, and recovery state;
- photos: Immich import, duplicate/review, archive, and backup state;
- media: movies, television, music, books, and audiobooks as one
  catalog/requests family;
- project archive: website/database/object snapshots, datasets, releases, and
  restore evidence;
- CV archive: sources, annotations, curated outputs, retention, and capacity;
- models: active/archive inventory, licenses, provenance, hashes, and evals;
- smart home: Home Assistant health and human-authored maintenance items;
- network/privacy: AdGuard status, blocked-query trend, and fallback-DNS state;
- security/recovery: patch, vulnerability, certificate, backup, and restore-test
  work. Never put passwords, recovery keys, personal file contents, or raw
  sensitive logs on a board.

The gateway is read-only first. It publishes typed, redacted health facts and
accepts no arbitrary command, shell string, Docker argument, SQL, path, or URL.
Later actions must be named, schema-validated, allowlisted workflows with a
specific risk tier, approval rule, audit record, timeout, idempotency behavior,
and rollback/recovery procedure. Raw Docker socket access, privileged
containers, root SSH, and broad service administrator tokens are prohibited.

Expose two deliberately separate integration surfaces:

1. `life-center-status` MCP is read-only and returns only `get_overview`,
   `get_service_health`, `get_backup_status`, `get_storage_capacity`,
   `get_model_inventory`, `get_archive_freshness`, `get_security_findings`, and
   `get_pending_maintenance`-class summaries. It has no filesystem browser.
2. `life-center-actions` is **not MCP-exposed initially**. Later it may accept
   fixed identifiers such as `verify_backup`, `refresh_inventory`, or an
   isolated stateless-worker restart. Each action is implemented and admitted
   separately under the security baseline. It never accepts a caller-supplied
   shell command, SQL, Docker arguments, path, URL, container name, or environment
   variable.

Boards provide governance and deep links, not replacements for the native
Immich, Nextcloud, Jellyfin, Home Assistant, or Bitwarden clients.

This keeps the dashboard replaceable: CasaOS can coexist as an optional human
launcher, while Compose, storage, backups, policy, and the gateway remain the
source of truth in `life-center-infra`.

Home services should be introduced in this order: host/storage/network/backup
foundation; Nextcloud with dummy data; Immich with duplicate test photos;
Jellyfin/books; AdGuard with fallback DNS; isolated Home Assistant OS;
read-only Command Center boards; password manager last. Prefer the official
Bitwarden service (including Bitwarden Lite for a supported lightweight option)
or keep Bitwarden cloud until self-host recovery is mature. Vaultwarden is an
optional community implementation, not the highest-assurance default: Bitwarden
does not guarantee official-client compatibility with non-official servers.
Each phase requires a working restore or recovery procedure before advancing.

### Remote and fallback experience

Install Tailscale on approved desktop, laptop, phone, Life Center, and Home
Assistant endpoints. Publish the desktop Command Center privately with
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve),
which shares inside the tailnet. Leave Funnel disabled because it exposes the
service publicly. The phone/browser PWA may review sanitized status, alerts,
agent findings, approvals, and deep links; native applications continue to work
independently.

Host a tiny, read-only fallback status page on the Life Center. It reports local
service/storage/backup health when the desktop cockpit is unavailable, with no
AI, approval, or administrative action path. Thus a desktop reboot removes the
full cockpit but does not remove personal services or basic visibility.

## Networking and trust

- The current Spectrum `SAX1V1R` Wi-Fi 6 router is an interim flat-LAN device
  fed by a separate Spectrum modem. The subscribed tier is Internet Ultra at
  600 Mb/s advertised download; Advanced WiFi is presented as an inactive
  add-on. At Life Center deployment, keep the modem and replace the router with the
  Gate 0-selected UDR7; avoid permanent double NAT. The exact migration and
  five-zone policy are in [`LIFE_CENTER_GATE0.md`](LIFE_CENTER_GATE0.md).
- Keep the UDR7 and Life Center upstairs beside the modem on one BR1000MS. Run
  one direct Cat6 2.5 GbE link to the downstairs desktop. No switch or extra AP
  is an initial purchase; the current cross-floor desktop signal is `-42 dBm`.
- Keep Command Center, administration, metrics, SSH, backups, and the password manager
  tailnet-only by default.
- Household LAN access is limited to services that need it, such as Jellyfin,
  Home Assistant, and AdGuard DNS.
- Database ports, Docker APIs, hypervisor controls, backup repositories, and
  secret-management interfaces remain in a more restricted management zone.
- Do not expose unauthenticated model endpoints broadly. A remote Ollama/model
  worker is optional and must be restricted to the intended caller path.
- The laptop going offline must degrade optional capacity, not break a route or
  household service.

## Current, next, and deferred work

### Current operating posture

- Desktop remains the current no-VPS Command Center/control-plane host.
- Desktop DDR5 repair is complete and operator-tested as reliable; it remains
  the Betts/CV heavy worker, normal authoritative writer, and primary model host.
- Laptop remains the human workstation, read-only candidate lane, and optional
  bounded worker.
- No Life Center production data or critical household service is assigned to
  the laptop.
- The planned Life Center will archive selected website/project data while the
  public application remains at its cloud edge.
- The existing cockpit will gain a narrow Life Center surface; CasaOS is
  optional and non-authoritative.

### Next evidence to collect

- Desktop: archive the exact replacement DIMMs/slots and completed test evidence;
  record BIOS path, memory speed/XMP, SSD identity/health/free space, M.2
  occupancy, cooler pump, UPS/restart behavior, and CUDA/PyTorch/driver state.
- Laptop: actual inventory archive contents, RAM modules, M.2 occupancy, SSD and
  battery health, fan/thermal validation, VRAM/power limit, WSL/Docker limits,
  CUDA/PyTorch state.
- Workloads: representative Betts backfill, CV batch, local-model, and laptop
  interactive benchmarks with throughput, peak RAM/VRAM, temperature, energy,
  and failure behavior.
- Data: present photo/video/document/media/model/site-archive sizes, raw versus
  retained CV output, monthly/yearly growth, retention rules, and accepted
  backup operating cost/downtime.
- Physical: approve the upstairs-to-downstairs Cat6 route and verify that the
  Life Center's noise and heat are acceptable in the upstairs working office.

### Blocking unknowns before real personal data

These are deployment gates, not optional polish:

1. measured current bytes, retained monthly growth, and three-year projection;
2. approved CV/video/model retention and promotion policy;
3. exact serviceable tower, drive bays/controller/cooling, and Linux support;
4. inter-floor Cat6 route plus UDR7 VLAN/firewall/rollback commissioning tests;
5. separate local backup hardware plus selected/costed off-site destination;
6. per-service RPO, RTO, data owner, and acceptable outage;
7. implemented encrypted-secrets workflow and offline key recovery;
8. UPS sizing and tested clean shutdown/restart;
9. status gateway schemas, identity, redaction, and threat-test plan;
10. tool-by-tool agent permissions plus allow/deny tests; and
11. a complete dummy-data backup and restoration with evidence.

### Ordered implementation

| Gate | Work | Exit condition |
| --- | --- | --- |
| 0 — inventory/purchase | desktop baseline, daily growth task, Spectrum 600 Mb/s tier/router topology, two-office layout, recovery targets, and price procedure are captured in `LIFE_CENTER_GATE0.md`; finish cable/noise acceptance, 30-day growth, exact value-tier component SKUs, and purchase-day validation | three-year forecast and bill of materials approved; current default is an upstairs serviceable four-bay Intel-iGPU value-tier tower + `2 x 12 TB` CMR + 16 TB-class separate backup + BR1000MS + one UDR7 + direct Cat6 to downstairs desktop |
| 1 — repository | create private `life-center-infra` with typed host/service/storage contracts, Compose, Tailscale/firewall policy, secret references, backup classes, risk tiers, tests, and runbooks | configuration validates with no real secrets or personal data |
| 2 — foundation | install Debian, storage, Tailscale, firewall, Docker, SMART/scrub monitoring, UPS, backup tooling, encrypted secrets, and digest-pinned test images | security G0–G2 pass; reboot plus dummy backup/restore proven |
| 3 — applications | pilot Nextcloud dummy files, Immich duplicate photos, Jellyfin, Audiobookshelf/Calibre-Web, AdGuard on one test client, then HA OS VM | each service passes its applicable hardening, backup, restore, upgrade, and rollback checks before the next critical admission |
| 4 — archives | add read-only cloud exports, staging validation, versioned manifests, quotas, retention, and restore verification | site/CV/model dummy archive restores and integrity checks pass |
| 5 — read-only experience | add boards, native-app deep links, redacted gateway, status MCP, alerts, and fallback page | security G5 plus schema/redaction/deny tests pass |
| 6 — controlled maintenance | admit one fixed diagnostic/check/restart action at a time | security G6 passes per action; no generic action surface exists |
| 7 — password manager | keep Bitwarden Cloud through earlier stabilization; evaluate official Bitwarden Lite | complete offline recovery and client-access test passes before migration |

Hardware is provisionally selected but not purchased, no `life-center-infra`
repository exists, and no gate above should be described as implemented merely
because its design is documented here.

### Deferred until evidence exists

- BIOS updates on either machine;
- laptop RAM or SSD purchases;
- production scheduling changes based on synthetic specifications alone;
- a Railway/VPS migration for `llm_station`;
- Life Center hardware purchase and final ZFS-versus-ext4 choice, until the
  physical network survey, retained-growth acceptance, exact platform SKUs,
  and same-day seller/warranty/price validation are complete;
- any self-hosted password-vault migration;
- CasaOS installation, unless a disposable noncritical evaluation has a written
  purpose and exit criterion;
- any automatic administrative action from the cockpit.

## Acceptance criteria for the final topology

The architecture is complete only when:

- powering off the laptop affects no household or production dependency;
- desktop authoritative work remains backed by the post-repair memory/stress
  baseline and ongoing error monitoring;
- Betts has one normal production writer and safe staging/idempotent failover;
- active model storage cannot silently exhaust the OS/WSL disk;
- Life Center data survives a single-disk failure and restores from a physically
  separate backup;
- irreplaceable data has encrypted off-site protection;
- website/project archives restore independently of the cloud account and never
  make the residential host a public production dependency;
- the 70% capacity alert, 80% expansion/eviction trigger, per-dataset budgets,
  and retention jobs prevent CV scratch from crowding out irreplaceable data;
- DNS and Home Assistant have documented recovery paths;
- desktop cockpit loss leaves Life Center services and read-only fallback status
  available;
- no model or Command Center path has blanket household-admin authority;
- every Life Center dashboard action is allowlisted, typed, audited, and subject
  to the security baseline's risk/approval policy;
- the laptop remains responsive and presentation-ready for interviews and live
  demonstrations.

# Hardware, workload, and Life Center operating decision

**Status:** adopted architecture; the desktop memory gate is resolved, while
Life Center implementation remains gated by the verification items below.  
**Reviewed:** 2026-07-17 (Open Design dev-lane tool and the one-command
`lc` bootstrap decision).  
**Scope:** the RTX 4090 desktop, MSI RTX 5080 laptop, Betts Basketball/CV
workloads, local models, the proposed personal Life Center, the connected
portable/fixed multi-camera capture program, the Open Design dev-lane creative
tool, and the one-command bootstrap that brings the open-source portfolio up
reproducibly.

This document reconciles two earlier proposals that disagreed about the laptop
and about where the always-on control plane should live. It records verified
facts separately from reported-but-unverified facts and future design choices.

## Decision

Use three primary roles plus one optional recovery/utility tier:

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

Operate the CV program as two connected capture systems rather than one large
rig:

```text
Portable phone-first system
├── starts with three existing phones for local acceptance
├── standardizes on four active cameras plus one spare for partner sessions
├── produces ordinary phone-domain footage for deployment-model evaluation
└── hands validated, consent-classified sessions to desktop processing

Fixed calibrated truth lab
├── targets four synchronized coverage cameras plus one movable 120-fps truth camera
├── produces calibration evidence, multiview labels, and benchmark sessions
├── expands to six/eight full-court cameras only after measured need
└── improves phone-deployed models; it does not replace the phone domain
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

Permanently protect human annotations, gold evaluation assets, final structured
outputs, important detected events, published derivative datasets, evaluation
evidence, hard-to-recreate fine-tunes, and only those irreplaceable source clips
that were explicitly promoted under the recorded permission and partner
agreement. Reproducible bulk artifacts and unpromoted partner raw expire:

| Artifact | Initial retention |
| --- | ---: |
| decoded frame caches | 3–7 days |
| unusable/failed raw and pipeline scratch | 7–14 days |
| temporary transcodes/crops | 14 days |
| analysis-only partner raw | 30 days unless the agreement is shorter |
| training-approved raw | 60–90 days unless explicitly promoted |
| proxies and reproducible intermediates | 90–180 days when they reduce review cost |
| selected truth/review clips | retain only by explicit, consent-compatible promotion |
| gold labels and irreplaceable sources | permanent, backed up by class |

Incomplete model downloads, duplicate quantizations, unused base weights,
optical-flow caches, and conversion scratch are disposable. Store retention in
versioned policy—not hard-coded application defaults—and revise it from measured
reuse and retained-growth evidence. Every session must carry the organization,
venue, participant/permission class, allowed purposes, deletion due date,
publicity flag, and trained-weight treatment. Successful capture never implies
permission for training, research, publication, or publicity.

Data classes:

- **A — irreplaceable:** photos, personal videos, documents, scans, vault
  recovery, Home Assistant configuration. Primary + redundant local + separate
  local backup + encrypted off-site + restore tests.
- **B — expensive to recreate:** annotations, curated datasets, fine-tuned
  adapters, embeddings, evaluation artifacts, website database/object exports,
  organized book metadata, and Open Design `.od/` project files (design systems,
  skills, and templates; the desktop/laptop holds the authoritative copy and the
  Life Center the backup). Local backup and selective off-site protection.
- **C — reproducible:** public base models, container images, generated
  thumbnails, caches, legally reacquirable media. Preserve catalog, license,
  source revision, and hashes; redownload where economical.

### Multi-camera CV lab, field kit, and storage handoff

The production target is a portable deployment-domain system connected to a
fixed truth system. Keep the existing single-view pipeline authoritative while
multiview is additive and under validation.

| Use | Active cameras | Starting standard |
| --- | ---: | --- |
| Local acceptance | 3 | Existing phones; minimum viable overlap |
| Portable adult/team pilot | 4 | Three overlapping coverage views plus one side/truth view |
| Fixed half-court truth lab | 5 | Four fixed synchronized coverage views plus one movable 120-fps truth view |
| Full court | 6 minimum; 8 preferred | Expand only after a proven partner/venue need |
| Fast contact, seam, spin, or rolling-shutter study | 1 temporary specialist | Rent before purchase and retain a simultaneous ordinary-phone view |

For the four-camera field layout, use opposing high diagonal views, one high or
protected baseline view, and one side view. For the fixed half-court lab, use
two high diagonals, two offset baseline/cross-baseline views, and a movable
truth camera. Critical release/rim/paint cells should appear in at least two
portable views and three fixed-lab views. Stands stay outside play and egress,
with sandbags, cable ramps, and safety cables; permanent mounts require facility
approval and secondary retention.

Start with supported iPhone/Galaxy-class phones and the
[Blackmagic Camera app](https://www.blackmagicdesign.com/products/blackmagiccamera)
for locked manual controls, monitoring, multiview, coordinated start, and
external timecode. A common trigger is an operating convenience, not proof of
sensor-level synchronization. Use external timecode plus a visible sync strobe
for portable work. Genlock plus timecode is the later fixed-lab target; rolling
shutter still requires validation. The preferred fixed coverage candidate is
four matched
[Blackmagic Micro Studio Camera 4K G2](https://www.blackmagicdesign.com/products/blackmagicmicrostudiocamera)
bodies/lenses with common timing, plus an FX30-class 4K120 truth rig. Rent a
global-shutter/high-speed camera before buying an industrial or specialist
array.

Freeze a per-session camera preset: one frame-rate family across synchronized
views, 4K where storage and thermal tests pass, locked focus/exposure/white
balance, stabilization and digital zoom off, audio off, constant-frame-rate
recording where supported, and a shutter selected from an on-site flicker/blur
test. Every multiview product records sync mode/residual/drift, shutter type,
intrinsic/extrinsic calibration versions, camera provenance, and uncertainty.
If timing or geometry fails, fall back to independent-view 2D outputs and block
precision 3D claims.

The acceptance lane is:

```text
MC0 authorization, camera roster, cloud-sync disablement, and physical safety
MC1 60–90 minute media/thermal/integrity test and hashes
MC2 visible-strobe/timecode synchronization and drift measurement
MC3 held-out intrinsic calibration with a rigid matte ChArUco board
MC4 measured court/world coordinates and held-out extrinsic validation
MC5 coverage, occlusion, flicker, blur, and one-camera-failure test
MC6 uncertainty-bearing multiview association/3D validation
MC7 manifest -> ingest -> processing -> archive -> restore -> delivery recovery
```

Initial internal thresholds may follow the source proposal—zero corrupt frames,
portable/fixed held-out world-error targets of 15 cm/5 cm, and no unqualified
triangulation—but they remain hypotheses until local evidence sets baselines.
Record and tighten them; never loosen them merely to pass a camera.

Purchase in evidence-gated layers:

| When | Need | Planning posture |
| --- | --- | --- |
| Local proof | three heavy/protected phone rigs, continuous power, recording media, rigid ChArUco board, gray card, measured tape/rangefinder, sync strobe, cases, cable ramps, isolated travel router | Use existing phones; validate before buying dedicated devices |
| Field ingest | one 4–8 TB fast NVMe shuttle plus a second shuttle or other verified independent copy | Do not erase camera media until hashes and two readable copies are verified |
| After local acceptance | fourth phone rig, spare coverage phone, and external timecode only if measured drift requires it | Standard portable partner kit |
| After adult pilots | FX30-class truth rig, flicker-free supplemental light, stronger calibration wand, and more field storage | Buy only if truth quality or annotation effort improves |
| After a committed venue | four matched/genlocked fixed coverage cameras, protected power/SDI/network cabling, approved mounts, monitoring, and professional installation | Half-court first; defer full-court expansion |

The data boundary is:

```text
camera media
  -> encrypted field shuttle
  -> hashes + media check + manifest + proxies
  -> RTX 4090 desktop hot processing and human review
  -> permission-aware promotion
  -> Life Center quota/expiry staging
     + calibration/validation evidence
     + consent-approved source clips
     + gold labels and structured outputs
     + partner delivery packages and restore evidence
```

Multi-camera originals can exceed the starter mirror quickly: five cameras at
200 Mb/s for two hours are about 900 GB before proxies and intermediates. The
Life Center therefore holds curated authority and short raw staging, not every
original forever. Measure actual bitrate, proxy size, promotion rate, processing
time, and deletion completion across ten sessions before resizing storage or
adding 10 GbE.

The truth-system flywheel is: synchronized evidence -> candidate multiview
labels -> human correction -> frozen gold truth -> projection into ordinary
phone views -> phone-model training -> sealed phone-only evaluation. Split
evaluation by organization, venue, and session rather than random frames. A
camera purchase is justified by measured occlusion recovery, phone-model
quality, calibration reliability, annotation-time reduction, or a newly
validated measurement—not by image quality alone.

### Desktop Docker retention audit

**Audit date:** 2026-07-13. **Scope:** Docker Desktop only; no container,
image, volume, cache, network, or project file was changed during the audit.

Docker's logical accounting was **463.5 GB** at the time of inspection:

| Docker class | Used | Docker-reported reclaimable | Interpretation |
| --- | ---: | ---: | --- |
| Images | 274.6 GB | 257.6 GB | Rebuildable only when the image is not needed by a retained container and its Compose/build inputs are available. |
| Container writable layers | 30.47 GB | 19.28 GB | Potentially unsafe: a writable layer can contain uncommitted output even when the image is reproducible. |
| Named volumes | 79.6 GB | 24.64 GB | Treat database/configuration volumes as retained operational state until a verified logical backup exists. |
| Build cache | 79.43 GB | 79.43 GB | Reproducible build acceleration, not a Life Center archive or a blind-prune authorization. |

This logical view is not the same measure as the approximately 533 GiB Docker
Desktop/WSL runtime file reported in Gate 0. The latter includes storage-driver
allocation and overhead. Neither total belongs in the retained-data forecast as
one undifferentiated backup target.

The three largest writable layers were inspected with `docker inspect --size`,
`docker diff`, and their mount maps. `docker diff` identifies changed paths, not
their complete semantic contents or a recovery source, so the classifications
below are conservative.

| Container layer | Writable size | Audit evidence | Retention decision |
| --- | ---: | --- | --- |
| Active `bball_homography_pipeline_env_datascience` | 10.1 GB (9.39 GiB) | 3,323 changed `.venv` paths, 104 `home/astro` paths, temporary cache/compiler paths, and NVIDIA runtime injection. Project videos, models, checkpoints, reports, MLflow state, and source are bind-mounted rather than represented by this layer. | **Active mixed runtime state. Do not remove.** Promote any needed output to a mounted canonical path; make the environment/cache reproducible before replacing it. |
| Stopped `bball_homography_pipeline_env_cv_worker` | 10.1 GB (9.37 GiB) | 1,114 changed `.venv` paths, 93 `home/astro` paths, including Hugging Face model-cache content, plus temporary/compiler and NVIDIA runtime paths. | **Rebuildable cache/environment candidate, pending owner review.** It is not a canonical backup source; retain only an inventory of model revisions/hashes and any explicitly promoted output. |
| Stopped `betts_basketball-datascience-1` | 8.01 GB (7.46 GiB) | 31,793 changed `.venv` paths, 614 PyTensor-cache paths, JAX/pytest/NPM/Jupyter temporary state, and NVIDIA runtime paths. The workspace, MLflow data, Codex state, and UV cache are mounted separately. | **Rebuildable environment/cache candidate, pending owner review.** Preserve source, lockfiles, configuration, and promoted artifacts—not this layer as a backup. |

The stopped-container exit codes do not make their data disposable: `143` is
normally a controlled termination and `137` can be a forced termination or
resource event. A stopped container may be removed only after its owner confirms
the recovery source and the writable-layer review below is complete.

#### Docker retention classes and backup boundary

| Class | Current examples | Backup / Life Center treatment |
| --- | --- | --- |
| **Authoritative data** | Selected project bind-mounted source video, annotations, final reports/results, promoted models, website exports, and user-selected personal data. | Classify the actual host roots in private `backup-scope.json`; retain and back them up according to classes A/B. Do not infer retention from Docker presence. |
| **Operational state** | `betts_basketball_airflow-postgres-data`, `betts_basketball_neo4j-data`, `llm_station_litellm_db_data`, `llm_station_ledger_data`, `llm_station_kuma_data`, and Airflow logs/configuration needed for recovery. | Use application-consistent logical database exports plus versioned configuration and restore tests. Do not copy a live volume as the sole database backup. |
| **Reproducible cache** | Hugging Face/UV/Roboflow/YOLO caches, PyTensor/JAX/Torch compiler cache, `.venv`, build cache, public base-model cache, and temporary transcodes. | Exclude from retained-capacity sizing and routine off-site backup. Keep manifests, lockfiles, pinned image digests, model hashes/licenses, and documented rebuild commands. |
| **Rebuildable images** | Docker images and duplicate application images. | Exclude from backup; retain Compose definitions, Dockerfiles, lockfiles, image digests, and build instructions. |
| **Disposable runtime state** | Failed-run scratch, temporary test output, one-shot init containers, and container writable state with an established recovery source. | Delete only through a reviewed cleanup record; never treat `reclaimable` as sufficient evidence. |

Docker bind mounts are outside the Docker volume total. For this desktop they
include the Betts workspace/DAGs/MLflow locations and homography source, video,
model, checkpoint, report, and serving locations. Those host paths are the
storage-scope and backup decision; the Docker Desktop VHDX, entire repository
envelopes, virtual environments, and caches are not.

#### Reviewed cleanup gate

Before removing any stopped container, image, named volume, or build cache,
create a small review record with all of the following:

1. Owner and purpose, including whether a service is active, paused, or retired.
2. Exact recovery source: Compose/Dockerfile/lockfile/image digest for code, or
   a tested logical export/backup for databases and configuration.
3. Confirmation that important output was promoted from the writable layer to a
   canonical bind-mounted or archived location.
4. For a named volume, a successful application-level restore test where it
   holds database or service state.
5. Rebuild/rollback steps and the expected reclaimed space.
6. Post-change checks for the affected service and a desktop free-space result.

`docker system prune -a` and `docker volume prune` remain prohibited for this
desktop. Start with individually reviewed retired containers and duplicate,
unmounted caches; do not touch the active CV layer, databases, or bind-mounted
project data. The immediate target remains at least 15–20% desktop free space
before any new Lifestyle application pilot.

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
- the one-command `lc` bootstrap, the optional launcher (Dockge), and the
  CasaOS decision.

### One-command bootstrap and optional launcher

The goal is a CasaOS-like experience — one command brings the selected
open-source services up correctly — **without** ceding authority to a launcher
that hides the real Compose, network, storage, and backup configuration. The
mechanism was chosen by comparing how CasaOS performs its one-command setup
against portable alternatives:

| Option | One-command install | Compose stays source of truth | Host takeover | Fit |
| --- | --- | --- | --- | --- |
| CasaOS | `curl \| sudo bash` | No — opaque app-store format | Installs Docker + its own system services | Rejected as authority; optional launcher only |
| Umbrel / Runtipi | OS image or installer | Partial — own app manifests/store | High / medium | App-store convenience, not Compose-transparent |
| Cosmos Cloud | Docker container | Manages Compose plus reverse proxy/SSO/2FA | Low (container on existing OS) | Strong alternative only if built-in HTTPS/auth is wanted; redundant while Tailscale already fronts every service |
| **Dockge** (MIT) | `docker compose up -d` | **Yes** — compose files stay on disk, editable by hand and via `docker compose` | Low (agentless, socket mount) | **Selected optional GUI** |
| **Scripted `lc` bootstrap** | `lc up` / `lc first-boot` | **Yes** — it *is* the Compose | None (idempotent script) | **Selected source of truth** |

**Decision.** The authoritative one-command installer is an idempotent **`lc`
CLI bootstrap** that mirrors this repository's proven `cc` CLI plus `Makefile`
composite-target idiom (`doctor -> setup -> bootstrap -> up -> health`). It
provisions host prerequisites and then brings up Compose **profiles** for the
selected, already-admitted service tier. **Dockge** is the sanctioned optional
"pane of glass": it explicitly does not take ownership of the Compose files, so
the `lc`-managed Compose, secrets, and backups remain the single source of
truth and stay auditable. This is portable to any Docker host — a noncritical
test profile on the desktop today, the Debian 13 Life Center later.

`lc up --profile <tier>` reconciles "one command for everything" with the
admit-one-application-at-a-time rule: the command is reproducible and
idempotent, but each application tier is enabled only after it passes its
admission gate, never all at once by default. The bootstrap, its Compose
profiles, `.env.example` (references only, never secrets), runbooks, and the
Open Design dev-lane bring-up are seeded in the `life-center-infra` skeleton for
later extraction into the separate private repository.

This decision does not change the CasaOS posture recorded in
[`LIFE_CENTER_GATE0.md`](LIFE_CENTER_GATE0.md) (`CasaOS omitted`) or below: CasaOS
remains omitted as an authority and may still be evaluated only as a disposable,
non-authoritative launcher over noncritical test services. Dockge is preferred
over CasaOS for that optional role precisely because it keeps the Compose files
transparent.

### Open-source application portfolio

Adopt one authoritative application per category first. Alternatives remain
replaceable candidates until a representative import, backup, clean restore,
upgrade, rollback, client-access, and data-export test passes. Do not deploy
overlapping applications simply because they are available.

| Function | Initial default | Alternative or boundary | Admission gate |
| --- | --- | --- | --- |
| Files and sync | [Nextcloud](https://nextcloud.com/) | Ordinary folders and collaboration; not the records system or a backup | dummy-data sync and restore |
| Photos | [Immich](https://immich.app/) | Keep originals independently recoverable | duplicate/import and full restore |
| Notes/OneNote replacement | [Joplin](https://joplinapp.org/) clients with Nextcloud WebDAV | TriliumNext/Logseq for a separate knowledge-base use; Saber or Xournal++ only as handwriting/PDF companions; Nextcloud Notes only for scratch notes | representative OneNote migration, encrypted sync, JEX restore |
| Scanned records | [Paperless-ngx](https://docs.paperless-ngx.com/) | Complements Nextcloud; it owns OCR metadata and archival retrieval | dummy originals plus exporter/importer restore |
| Backups | [Restic](https://restic.net/) default candidate | [Kopia](https://kopia.io/) alternative when its GUI/policy model materially improves operation; choose one | encrypted restore from separate media and off-site target |
| Tasks/projects | Nextcloud Deck first | [Vikunja](https://vikunja.io/) if Deck is measurably insufficient; do not run both initially | export/restore and notification test |
| Bookmarks/research archive | [Linkwarden](https://github.com/linkwarden/linkwarden) | Preserve source URL, capture status, and export | archived-page and database restore |
| Budgeting | [Actual Budget](https://actualbudget.org/) | Manual/dummy imports first; no financial detail in Command Center | mature secrets, authentication, encrypted export/restore |
| Video | [Jellyfin](https://jellyfin.org/) | Legally held media; no duplicate media server initially | playback, metadata, and rebuild/restore |
| Audiobooks/books | [Audiobookshelf](https://www.audiobookshelf.org/) and/or [Calibre-Web](https://github.com/janeczku/calibre-web) by distinct format need | Avoid duplicate authority for the same catalog metadata | sample library restore |
| RSS/news | [FreshRSS](https://freshrss.org/) | External feeds remain untrusted input | OPML export/restore and feed-failure handling |
| Recipes/meal planning | [Mealie](https://mealie.io/) | Optional Home Assistant integration after both sides are admitted | database/export restore |
| Household inventory | [Homebox](https://homebox.software/) | Link warranties in Paperless instead of duplicating originals | export/restore |
| PDF utilities | [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF) | Tailnet/LAN only; uploaded files may be sensitive | temporary-file deletion and deny tests |
| Office work | [LibreOffice](https://www.libreoffice.org/) on clients | Nextcloud Office/Collabora only when browser collaboration justifies another service | representative format round-trip |
| Email/calendar/contacts | [Thunderbird](https://www.thunderbird.net/) client plus reliable external mail | Nextcloud may provide CalDAV/CardDAV; do not self-host Internet email initially | client export/recovery |
| Selected working-folder sync | [Syncthing](https://syncthing.net/) | Never point it at live databases, Docker volumes, or Nextcloud appdata; sync is not backup | bounded folder conflict/recovery test |
| Smart home, DNS, passwords | Home Assistant OS, AdGuard Home, official Bitwarden/Bitwarden Lite | Password manager remains last; DNS requires tested bypass/fallback | service-specific security baseline gates |
| Design / creative (dev lane) | [Open Design](https://opendesigner.io/) ([`nexu-io/open-design`](https://github.com/nexu-io/open-design)) | Runs in the desktop/laptop **dev lane**, not on the appliance; the Life Center holds only a backed-up copy of its `.od/` project files. It is never a household-service authority. | agent-detect + a BYOK generation smoke test; `.od/` export and clean-profile restore |

**Open Design** is a local-first, Apache-2.0 design canvas (roughly 79k GitHub
stars) — an open equivalent of the Claude design workflow that keeps model,
usage pool, cost, and underlying system under owner control. Its canvas is
driven by any of 21+ coding agents (Claude Code, Codex, Cursor, Gemini CLI, and
others), and usage can come from an agent subscription already held, a
bring-your-own API key, or a local model — so a session can draft with a cheaper
model, switch to a stronger one for polish, move to Codex when a Claude
allowance runs tight, or stay fully local for private work with no paid tokens.
Projects, skills (`SKILL.md`), templates, and design systems (`DESIGN.md`) live
locally under a `.od/` SQLite directory, so the whole workflow is editable and
portable. It belongs in the **dev lane** rather than the Life Center appliance
because it depends on the coding-agent CLIs and model access that live on the
desktop/laptop, not on the Intel-iGPU storage host; the appliance's only role is
to back up the `.od/` project data as Class B (expensive to recreate). Its
dev-lane bring-up and `.od/` backup hook are seeded in `life-center-infra`
(see [One-command bootstrap and optional launcher](#one-command-bootstrap-and-optional-launcher)).

Notesnook self-hosting should be reconsidered only after its server is declared
production-ready by its maintainers and passes the same migration/restore gates.
Do not replace Joplin with it based on client polish alone.

Use this notes recovery contract:

```text
authoritative working copy: Joplin clients
sync transport: Nextcloud WebDAV with a dedicated app credential
server protection: application-consistent Nextcloud backup
portable recovery copy: scheduled JEX export protected by backup encryption
historical migration copy: immutable OneNote export plus selected PDFs
off-site protection: encrypted-at-rest JEX and original OneNote export
```

The Joplin sync directory is application-managed and must not be reorganized by
hand. Export every OneNote notebook before migration, hash the untouched export,
import one difficult representative notebook, verify hierarchy/links/tables/
attachments/drawings/search/mobile offline behavior, enable Joplin end-to-end
encryption from one device, and run OneNote read-only in parallel for about 30
days. Retire the Microsoft copy only after a JEX restore succeeds in a clean
profile and both local-separate and encrypted off-site copies of the original
export are verified.

Paperless-ngx has a split recovery unit:

```text
/srv/appdata/paperless    database, configuration, index, and queue state
/tank/personal/paperless  originals, archived documents, and versioned exports
```

A database without the originals and originals without the metadata are partial
recoveries. Pause ingestion, run the supported document exporter, protect the
export with the selected backup engine, and prove import into a clean,
version-matched instance before admitting real tax, medical, insurance,
employment, contract, receipt, or warranty records.

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

For the added applications, boards may show Joplin sync/export freshness,
Paperless ingestion failures and backup age, Actual service/backup health,
Linkwarden capture failures, and per-application storage use. They must not
show note titles, document names, financial balances, account/merchant/
transaction details, recipe contents, inventory descriptions, bookmarks,
search text, or document thumbnails.

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

Home services should be introduced in this order: host/storage/network plus one
selected backup engine; Nextcloud with dummy data; the Joplin migration pilot;
Immich with duplicate test photos; Paperless with dummy records; one task
system; Linkwarden/FreshRSS/Mealie/Homebox/Stirling-PDF as individually admitted
optional services; Jellyfin/books; AdGuard with fallback DNS; isolated Home
Assistant OS; Actual Budget after the sensitive-data gate; read-only Command
Center boards; password manager last. Nextcloud Office/Collabora is deferred
until browser collaboration justifies its operating cost.

Prefer the official Bitwarden service (including Bitwarden Lite for a supported
lightweight option) or keep Bitwarden cloud until self-host recovery is mature.
Vaultwarden is an optional community implementation, not the highest-assurance
default: Bitwarden does not guarantee official-client compatibility with
non-official servers. Each phase requires a working restore or recovery
procedure before advancing.

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

## Consent-first video acquisition and partner outreach

The initial offer is a performance-analysis pilot. Model-improvement use is a
separate opt-in, not an implied payment or vague data trade. Teams and
participants never receive direct Life Center access; they receive an approved
export through an authenticated cloud portal or encrypted time-limited
delivery. The portal exposes only that partner's authorized sessions,
participants, clips, reports, data exports, limitations, and deletion/export
request path.

Record four separate permissions:

| Tier | Permission | Default |
| --- | --- | --- |
| A | Capture and analyze for the partner | Required |
| B | Use pseudonymous data for model improvement | Optional/off |
| C | Research or publication | Off |
| D | Public demo, marketing, or social media | Off |

Only admit a crowded drill to training when every visible participant has Tier
B permission. Otherwise it remains analysis-only. Agreements must state raw
retention, deletion handling, whether approved derived labels may persist, and
how trained weights are treated after source deletion. Do not promise model
unlearning until it exists and has been validated.

Start outreach from Sanford/Central Florida in this order:

| Stage | Prospect | Entry condition and contact route |
| --- | --- | --- |
| 1 | Adult church/recreation leagues, private trainers, open adult gyms, former college/pro players, adult clubs | Direct adult consent; closed controlled drills; use the four-camera portable kit only after local MC0–MC7 proof |
| 2 | Private skills/performance facilities and academies | Adult proof package, facility survey, equipment footprint, security/retention summary, insurance information |
| 3 | AAU/travel programs | Organization director, coach, facility manager, parent liaison, and legal/insurance contact; one consented practice group |
| 4 | High schools | Athletic director, district privacy/legal/technology, administration, coach, parent coordinator, and facilities; written institutional approval |
| 5 | Colleges | Basketball operations/video/performance staff plus compliance, legal/privacy, information security, and research/IRB as applicable |

Run three to five adult pilots before involving minors. Youth/institutional work
requires Florida counsel and the institution's privacy/legal review; this is an
operating plan, not legal advice. Photos/videos directly related to a student
may be education records under
[FERPA guidance](https://studentprivacy.ed.gov/faq/faqs-photos-and-videos-under-ferpa),
and the FTC treats a child's image or voice as personal information in covered
[COPPA](https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions)
contexts. Never contact minors directly. Require guardian consent and athlete
assent, a coach/guardian present, a two-adult crew, pseudonymous IDs with the
identity map stored separately, closed drills without spectators/opponents,
background/child-safety requirements, insurance/COI, and an implemented
deletion/incident process. Disable and strip audio by default; any exception
requires written authorization and Florida legal review.

Use this acquisition funnel:

```text
prospect
  -> initial contact
  -> discovery call
  -> facility/camera/safety survey
  -> privacy + legal + insurance review
  -> approved pilot and participant consent
  -> capture scheduled
  -> media validated and permission-classified
  -> analysis delivered
  -> partner feedback
  -> training-use audit
  -> renew, close, export, or delete
```

The board record needs organization/program type, adult/youth status, primary/
legal/privacy contacts, facility and mount options, insurance requirements,
audio policy, participant count, permission tiers, raw-retention and deletion
dates, training/publicity flags, delivery due date, and current status. Agents
may draft outreach and summarize requirements; they may not approve consent,
alter rights/retention, publish footage, or admit a session to training.

The initial pilot offer is a no-cost 60–90 minute closed adult drill with four
cameras, a two-person crew, audio off, no public posting, separate training
opt-in, and delivery in 7–14 days. Provide a camera/quality report, approved
annotated clips, only those metrics that pass that session's validation,
confidence/missing-data indicators, methodology/limitations, secure exports,
and the retention/deletion statement. Do not initially promise injury or
medical predictions, fully solved 3D biomechanics, automated recruiting
grades, perfect identity, or guaranteed improvement.

Starter outreach:

> **Subject: No-cost multi-camera basketball analysis pilot**
>
> I am building a privacy-first basketball computer-vision system for
> controlled practice footage and am looking for a small number of local adult
> teams or trainers for a no-cost pilot. We would place four protected cameras
> outside the playing area, record an approved 60–90 minute closed drill, and
> return annotated clips, a quality report, and only the performance metrics
> that pass our validation checks. Audio is disabled, footage is not posted
> publicly, and model-improvement use is a separate optional permission. I can
> provide the equipment footprint, insurance information, security and
> retention summary, consent forms, and a sample deliverable before scheduling.

Before sending outreach, assemble a one-page offer, equipment/coverage diagram,
sample report made from self/consenting-adult footage, privacy/retention
summary, consent forms reviewed for the intended adult pilot, insurance/COI
facts, and available dates. The first outreach KPI is not raw response volume:
it is three to five safely completed adult sessions with measured setup time,
media failure rate, captured bytes, delivery time, deletion completion, coach
usefulness, and explicit permission outcomes.

### Evidence-gated budget (2026-07-13 retail snapshot)

Do not spend $20,000–$35,000 before contacting anyone. The sensible first
authorization is about **$7,500, with a hard ceiling of $10,000**, to build and
prove the portable phone-based kit and complete the first three adult pilots
using three existing phones, the existing RTX desktop/laptop, and the
already-built CV pipeline. Spend that money on capture reliability, venue
access, safety, insurance, and agreements — not another software platform. The
phone-first system plus a separate professional truth camera remains the
correct architecture; the fixed/full-court tiers below are future purchases,
not outreach prerequisites.

| Program level | What it gets | Expected investment |
| --- | --- | ---: |
| Local technical proof | three existing phones, mounts, storage, power, calibration, safety gear, court tests | $2,500–$6,500 |
| Adult-partner pilot ready | four-camera portable kit, basic business/legal/insurance readiness, three pilots | $5,000–$12,500 |
| Portable professional system | above plus an FX30-class truth camera and large ingest storage | $9,000–$20,000 |
| Youth/institution ready | dedicated sanitized devices, stronger insurance, counsel-reviewed agreements, background/venue requirements | $14,000–$32,000 |
| Fixed five-camera half-court lab | four synchronized coverage cameras, one truth camera, lenses, install, genlock/control | $18,000–$35,000 (lab only) |
| Combined mobile program + fixed lab | portable kit, fixed lab, business/compliance readiness | $30,000–$60,000 |
| Six-to-eight-camera full court | permanent install, processing/storage expansion | $45,000–$100,000 |
| Industrial global-shutter research lab | precision hardware trigger/PTP, dedicated capture server, specialist optics | $75,000–$150,000+ |

Recommended first-$7,500 allocation:

| First-wave item | Target allocation |
| --- | ---: |
| Three complete existing-phone rigs | $1,200–$2,000 |
| External SSDs, power, and cables | $700–$1,100 |
| Calibration boards, sync light, and measurement tools | $350–$750 |
| Sandbags, safety cables, cable ramps, and cases | $500–$900 |
| Court rentals and test-session expenses | $600–$1,000 |
| Initial insurance, agreements, and business reserve | $1,500–$2,500 |
| Assistant, mileage, and consumables | $400–$900 |
| Contingency | $500–$900 |

Price anchors: Seminole State's Raider Center court is
[$100/hour with a four-hour minimum](https://s3.us-east-2.amazonaws.com/sidearm.nextgen.sites/seminolestateraiders.com/documents/2024/6/25/Facility_Use_Fees_2024-26.pdf),
so a first validation booking costs about $400 and the minimum can span
multiple dates. A [Sony FX30 body](https://www.bhphotovideo.com/c/product/1729317-REG/sony_ilme_fx30b_fx30_digital_cinema_camera.html)
lists at $2,098 (UHD 4K up to 120 fps); a complete truth-camera rig with lens,
media, power, cage, support, and tripod runs about $3,600–$4,900. A
[Blackmagic Micro Studio Camera 4K G2](https://www.blackmagicdesign.com/products/blackmagicmicrostudiocamera)
is $1,179 (2160p60, genlock via SDI); four bodies are $4,716 before lenses,
cabling, mounts, media, monitoring, genlock distribution, or install.

Per-pilot cash cost at a rented venue: $200–$400 court, $100–$250 one
assistant, $50–$150 mileage/food/consumables, $0–$100 temporary storage —
**$350–$900 cash per test plus about 8–20 hours of analysis/delivery time**.
Once a partner supplies its own gym, direct cash cost falls to about
$200–$700/session. The first three adult pilots may be free to the partner but
are not free to run — budget $1,000–$2,500 for the full three-pilot sequence.
These figures are a snapshot; re-verify seller, price, and availability before
committing spend.

### Outreach sequence and contacts (Central Florida, Sanford-anchored)

**Stage 0 — prove the equipment before approaching a team.** Seminole State
College Raider Center (H Building/Parking Lot 3, Sanford/Lake Mary campus) is
the court and adult-recreation validation partner, not a varsity target —
its current athletics listing does not show varsity basketball.
Facility contact: Kurt Esser, [esserk@seminolestate.edu](mailto:esserk@seminolestate.edu).
Recreation contact: Geoff Nelson, Coordinator of Intramural and Recreational
Sports, 407-708-2926. Request the four-hour minimum split across two dates: a
two-hour empty-court calibration session and a two-hour adult-volunteer
movement session — never a full game first. Run, in order: empty-court
geometry/lighting; a three-phone 60–90 minute continuous recording; a
start/middle/end sync-light test; intrinsic/extrinsic calibration; a
one-person court walk; five-position shooting; a two-person screen-and-drive;
a four-to-six-adult occlusion test; and a full ingest → processing → report →
restore rehearsal. Do not contact teams until: zero corrupted recordings,
stable 60–90 minute operation, repeatable sync/calibration, safe camera
placement, a sample annotated report, a verified delete/restore workflow, and
a one-page description of what the metrics can and cannot claim.

**Stage 1 — adult, low-complexity pilots.** Send only these three initial
approaches, not a mass cold-email blast:

| Prospect | Contact | Ask |
| --- | --- | --- |
| Seminole State intramural/recreation | Geoff Nelson, 407-708-2926 | one closed 60–90 min pilot with consenting adult students/staff/recreation participants, after Raider Center tests pass |
| Rollins College intramural/club sports | Nate Arrowsmith (Director), 407-691-1275; then Clay Starrett (Assoc. AD Operations) 407-691-1735 and Margie Sullivan (Assoc. AD Compliance) 407-646-2531 once interest exists | adult recreational participants, low-stakes controlled drill — not the varsity head coach first |
| Orlando Club Sport | [info@orlandoclubsport.com](mailto:info@orlandoclubsport.com), 877-820-2582 ext. 8 | introduction to adult captains/prospective players for one closed demo; men's 5-on-5 league was listed "coming soon," so confirm an active season exists first |

Church leagues enter through a warm referral, not a cold approach: ask every
adult pilot organizer to introduce one adult church, recreational, or
community team. The first church-league pilot should come through a known
captain, coach, or recreation director.

Offer per adult pilot: 60–90 min closed practice, four camera positions, audio
disabled, no livestream, no public posting, private annotated clips, a
session-quality report, only validated metrics, a separate opt-in for
model-improvement use, and raw-footage deletion after the agreed period. The
service agreement and the model-training permission must stay separate
documents/checkboxes.

**Stage 2 — private training facilities and academies** (only after three
adult pilots succeed).

- DME Academy, 2441 Bellevue Avenue, Daytona Beach, FL 32114, 386-271-2865
  (route through the site's virtual-meeting contact form, ask for basketball
  operations or performance technology). 47,000+ sq ft fieldhouse with two
  full NBA courts, five youth courts, and a performance center; Dan Panaggio
  heads basketball operations, Matt Panaggio directs High School Basketball.
  First ask is a coaches-only demo, an adult-staff/post-grad pilot, an
  empty-court calibration demo, or a technical review of the adult-pilot
  deliverable — not youth-team access.
- Lake Mary Preparatory School, 650 Rantoul Lane, Lake Mary, FL 32746,
  407-805-0095, [info@lakemaryprep.com](mailto:info@lakemaryprep.com). 24
  sports teams including boys'/girls' basketball. Involves minors — contact
  school administration/athletics, not an individual coach or athlete.
  Request an administrative discovery meeting first, then (only after
  approval) a six-to-eight-athlete closed drill with school-controlled
  parent/guardian communication, no game capture, no spectators, no public
  deliverables, and separate analysis/model-improvement permissions.

**Stage 3 — AAU/travel programs.** Enter through DME's Team Hosting program
(custom dates, training and competitive play for ages 14–19) and ask DME to
identify one visiting team for a closed-practice pilot: one team, one closed
practice, no tournament recording, no opponents/spectators, all permissions
complete before arrival, training use limited to drills where every visible
participant opted in, and a team report delivered before requesting another
session. Lake Mary Prep's athletics/booster network is the second AAU
introduction path — warm referrals over cold athlete outreach.

**Stage 4 — public high schools** (Seminole County Public Schools), only
after three adult pilots, one private-academy/institutional pilot,
counsel-reviewed youth documents, general-liability insurance/COI capability,
background-screening readiness, a written retention/deletion policy, a sample
guardian communication, and a security/incident-response summary:

| Priority | School | Main number |
| ---: | --- | --- |
| 1 | Seminole High School, 2701 Ridgewood Ave, Sanford | 407-320-5050 |
| 2 | Lake Mary High School, 655 Longwood Lake Mary Rd, Lake Mary | 407-320-9550 |
| 3 | Lyman High School, 865 S. Ronald Reagan Blvd, Longwood | 407-746-2050 |
| 4 | Hagerty High School, 3225 Lockwood Blvd, Oviedo | 407-871-0750 |

Process: call the main office and ask for the athletic director; send the
one-page pilot brief; let the school route privacy/legal/technology/risk
review; complete SCPS's vendor process (application, W-9, certificate of
liability insurance) only after the school or district requests it — SCPS
rejects unsolicited vendor applications without pending business. Ask for
off-season/preseason, one closed skill-development session, eight or fewer
approved athletes, no game footage, no spectators, no facial recognition, no
injury/medical predictions, school-controlled parent communication, and
institution-approved storage/deletion.

**Stage 5 — colleges**, approached last and in this order:

1. Stetson University (143 E. Pennsylvania Ave, DeLand, FL 32720; athletics
   386-822-8100). Start with Jon Hansen (Assistant AD Sponsorship & Community
   Outreach, 386-822-6698) or Jacob Gowan (Director of Broadcasting & Video
   Services) or Jack Hudson (Director of Facilities and Operations); bring in
   Brian Maxey (Assoc. AD Compliance, 386-822-7490) once interest exists.
   Do not start with the head basketball coach. Offer a technical demo using
   adult staff/graduate assistants, four-camera capture, one drill, a private
   report — no recruiting or public claims, institution owns final athlete-access
   decisions.
2. Rollins College — reuse the Stage 1 contacts (Arrowsmith → Starrett →
   Sullivan) before approaching varsity basketball.
3. UCF — Jeff Chapman (Director of Men's Basketball Operations,
   [jchapman@athletics.ucf.edu](mailto:jchapman@athletics.ucf.edu)) or Tyler
   Kriminger (Video Coordinator) or Charles Stephenson (Director of Sports
   Performance for Men's Basketball,
   [cstephenson@athletics.ucf.edu](mailto:cstephenson@athletics.ucf.edu)); bring
   in Brittney Anderson-Duzan (senior athletics compliance,
   [banduzan@athletics.ucf.edu](mailto:banduzan@athletics.ucf.edu)) once there
   is operational interest. UCF also has a formal Community Outreach path.
   Approach UCF last, with validated adult pilots and a sample report already
   in hand.

### Outreach package (assemble before Stage 1 sends)

1. One-page pilot brief: what the system does, four-camera footprint,
   setup/teardown time, what the partner receives, what is not claimed,
   audio-off policy, no-public-posting default, retention period, contact info.
2. Two-page privacy/data summary separating four permissions: capture and
   analyze; pseudonymous model-improvement use; research publication; public
   demo/marketing — the last three optional and off by default.
3. Physical setup diagram: four tripod locations, heights, safety boundaries,
   cable-free or ramped cable paths, no blocked exits, no equipment inside the
   playable area.
4. Sample deliverable built from adult validation footage: two annotated
   clips, a quality/confidence report, one movement/shot-form summary, a
   missing-data/limitations section, a data dictionary, a deletion date.
5. Operational proof: equipment checklist, calibration status, backup/restore
   test date, encryption statement, incident contact, certificate of insurance
   when available.

### First 30 days

- **Days 1–3:** email Kurt Esser about Raider Center rental; call Geoff Nelson
  to confirm the initial request is adult-only technical validation; set the
  project budget cap at $7,500; inventory existing phones/storage/tripods/
  power; buy only the missing three-camera validation equipment.
- **Days 4–10:** run continuous 90-minute recordings at home/outdoors; measure
  heat and dropped frames; test storage cables; test synchronized start and
  visual strobe; generate camera IDs/fixed presets; process a dummy capture
  through the existing pipeline end to end.
- **Days 11–17:** Raider Center session one (empty court) — lighting/flicker,
  intrinsics, court coordinates, camera coverage, sync testing; no players
  required.
- **Days 18–23:** Raider Center session two — two to six consenting adults;
  shooting, screens, drives, rebounds; a one-camera-failure test; end-to-end
  ingest; restore test; sample partner report.
- **Days 24–30:** send the adult pilot package in order — Seminole State
  intramural/recreation, then Rollins intramural/club sports, then Orlando
  Club Sport. Do not contact Lake Mary Prep, AAU teams, or SCPS during the
  first 30 days unless they approach first; establish that equipment,
  analysis, permissions, and delivery actually work before advancing stages.

The single immediate next action is the Raider Center email to
[esserk@seminolestate.edu](mailto:esserk@seminolestate.edu) requesting the
four-hour minimum across two dates (one empty-court session, one
adult-volunteer session) — that booking starts physical validation and
produces the first sample report needed for every later outreach stage.

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
- The existing cockpit will gain a narrow Life Center surface; the one-command
  mechanism is the `lc` bootstrap with Dockge as an optional pane, and CasaOS
  stays optional and non-authoritative.
- Joplin/Nextcloud, Paperless-ngx, Restic-or-Kopia selection, tasks, bookmarks,
  and the other application candidates are planned but not yet authoritative.
- Open Design is a dev-lane creative tool on the desktop/laptop; it is not an
  appliance service, and only its `.od/` project files are backed up to the
  Life Center.
- Multi-camera partner capture is not yet admitted. Local work starts with
  three existing phones and consenting adults/self-capture, then must pass
  MC0–MC7 before the four-camera outreach pilot is scheduled.

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
- Applications: representative OneNote export/import inventory, Paperless
  document classes, Deck-versus-Vikunja need, Restic-versus-Kopia restore
  evidence, and per-service sensitivity/RPO/RTO/owner.
- Capture: exact phone/device inventory, available storage and thermal behavior,
  90-minute media integrity, sync drift, lens/intrinsic calibration, venue
  coverage, measured bitrate/promotion rate, shuttle copy time, and sample
  partner deliverable usefulness.

### Blocking unknowns before real personal data

These are deployment gates, not optional polish:

1. measured current bytes, retained monthly growth, and three-year projection;
2. approved CV/video/model retention and promotion policy;
3. exact serviceable tower, drive bays/controller/cooling, and Linux support;
4. inter-floor Cat6 route plus UDR7 VLAN/firewall/rollback commissioning tests;
5. selected backup engine, separate local backup hardware, and a selected/
   costed off-site destination;
6. per-service RPO, RTO, data owner, and acceptable outage;
7. implemented encrypted-secrets workflow and offline key recovery;
8. UPS sizing and tested clean shutdown/restart;
9. status gateway schemas, identity, redaction, and threat-test plan;
10. tool-by-tool agent permissions plus allow/deny tests;
11. a complete dummy-data backup and restoration with evidence; and
12. before partner video: MC0–MC7 local evidence, approved adult consent/
    retention/deletion materials, insurance/COI facts, and a facility-safe
    capture plan.

### Ordered implementation

| Gate | Work | Exit condition |
| --- | --- | --- |
| 0 — inventory/purchase | desktop baseline, daily growth task, Spectrum 600 Mb/s tier/router topology, two-office layout, recovery targets, backup-engine comparison, and price procedure are captured in `LIFE_CENTER_GATE0.md`; finish cable/noise acceptance, 30-day growth, exact value-tier component SKUs, and purchase-day validation | three-year forecast, Restic-or-Kopia decision, and bill of materials approved; current default is an upstairs serviceable four-bay Intel-iGPU value-tier tower + `2 x 12 TB` CMR + 16 TB-class separate backup + BR1000MS + one UDR7 + direct Cat6 to downstairs desktop |
| 1 — repository | extract the `life-center-infra` seed into a private repo with typed host/service/storage contracts, the `lc` bootstrap, per-tier Compose profiles, Tailscale/firewall policy, secret references, backup classes, risk tiers, tests, and runbooks | `lc doctor` and `docker compose config` pass on every profile; configuration validates with no real secrets or personal data |
| 2 — foundation | `lc first-boot`/`lc up --profile foundation` installs Debian, storage, Tailscale, firewall, Docker, SMART/scrub monitoring, UPS, backup tooling, encrypted secrets, and digest-pinned test images | security G0–G2 pass; reboot plus dummy backup/restore proven |
| 3 — applications | admit tiers one at a time with `lc up --profile <tier>`: Nextcloud dummy files and Joplin migration/restore; then Immich, Paperless, one task system, Linkwarden and optional lifestyle tools; then Jellyfin/books, AdGuard, HA OS, and Actual after its sensitive-data gate. Open Design is a dev-lane bring-up on the desktop/laptop, not an appliance profile | each service passes its applicable hardening, backup, restore, export, upgrade, and rollback checks before the next critical admission |
| 4 — archives | add read-only cloud exports, staging validation, versioned manifests, quotas, permission-aware retention, and restore verification | site/CV/model dummy archive restores and integrity checks pass |
| 4A — local camera proof | use three existing phones and consenting adult/self-capture; run MC0–MC7, one-camera failure, two-copy ingest, desktop processing, Life Center dummy promotion, restore, and delivery rebuild | acceptance report passes without partner footage; actual bitrate, setup time, sync/calibration quality, processing time, and deletion are measured |
| 4B — adult partner pilots | add the fourth rig only after 4A; assemble offer/consent/insurance/security package and complete three to five closed adult sessions | every session is permission-classified, delivered, retained/deleted on time, restored where sampled, and reviewed for partner usefulness before youth or fixed-lab work |
| 5 — read-only experience | add boards, native-app deep links, redacted gateway, status MCP, alerts, and fallback page; optionally add Dockge as a non-authoritative Compose pane | security G5 plus schema/redaction/deny tests pass |
| 6 — controlled maintenance | admit one fixed diagnostic/check/restart action at a time | security G6 passes per action; no generic action surface exists |
| 7 — password manager | keep Bitwarden Cloud through earlier stabilization; evaluate official Bitwarden Lite | complete offline recovery and client-access test passes before migration |

Hardware is provisionally selected but not purchased, no private
`life-center-infra` repository exists yet (only an in-tree design **seed**
awaiting extraction), and no gate above should be described as implemented
merely because its design is documented here.

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
  purpose and exit criterion; Dockge is the preferred optional pane because it
  keeps the Compose files transparent, but it too remains non-authoritative;
- extracting the `life-center-infra` seed into its private repository and any
  live `lc` bring-up on a real host, until Gate 0/1 exits pass;
- a fixed four-camera coverage array, FX30-class truth rig, full-court expansion,
  global-shutter/industrial purchase, permanent venue mounts, automatic raw
  cloud upload, or 10 GbE until the preceding measured gate justifies it;
- youth, school, college, spectator, opponent, or game capture until counsel/
  institution, guardian/assent, insurance, safety, deletion, and incident gates
  pass;
- any partner or public access to the private Life Center;
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
- one selected backup engine restores each admitted application's complete
  recovery unit, including Joplin portable export and Paperless metadata plus
  originals;
- each application category has one declared authority, a portable export, and
  a clean restore/upgrade/rollback result before real sensitive data is admitted;
- the three-phone local kit passes MC0–MC7 before outreach, and every partner
  session has camera/media integrity, physical safety, consent, purpose,
  retention/deletion, and delivery evidence;
- camera originals flow through two-copy verified field ingest, bounded desktop
  processing, and permission-aware Life Center promotion without making the
  starter mirror an unlimited raw archive;
- partner access is export-only and never exposes the Life Center, while
  training, research, publicity, and youth capture remain separately gated;
- DNS and Home Assistant have documented recovery paths;
- desktop cockpit loss leaves Life Center services and read-only fallback status
  available;
- no model or Command Center path has blanket household-admin authority;
- every Life Center dashboard action is allowlisted, typed, audited, and subject
  to the security baseline's risk/approval policy;
- every admitted service is brought up reproducibly and idempotently by the `lc`
  bootstrap from version-controlled Compose, and any launcher (Dockge or CasaOS)
  remains a non-authoritative pane over that source of truth;
- the laptop remains responsive and presentation-ready for interviews and live
  demonstrations.

## Horizon thought — optional large-memory AI node

After the Life Center is built, backed up, and proven useful, consider a
DGX Spark-class appliance (or a future equivalent) only as a **separate
large-memory AI node**. It is not part of the Life Center bill of materials and
does not replace the desktop, laptop, cloud burst capacity, or storage host.

Its potential role would be long-context LLM/VLM inference, multiple
always-resident agents, and selective parameter-efficient model work that
regularly exceeds the desktop GPU's practical memory capacity. The desktop
remains the fast CV/video and smaller-model lane; the Life Center remains the
data, application, and recovery lane.

Revisit this only when workload telemetry shows repeated memory-capacity or
CPU-offload constraints—not merely high GPU utilization or slow CV throughput—
and when the required containers and libraries have proven ARM64 compatibility.
Compare the total ownership cost with temporary cloud GPUs and contemporary
high-memory workstation GPUs at that time. This is a future option, not a
current dependency or purchase gate.

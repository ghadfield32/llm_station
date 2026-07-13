# Life Center Gate 0 — measured inventory and purchase decision

**Status:** partially complete; desktop baseline and automated growth tracking
captured, Spectrum 600 Mb/s tier and router/separate-modem topology identified,
two-office physical design selected, and provisional network/storage bill of
materials and recovery targets selected. The 30-day trend, inter-floor cable
route, upstairs acoustic/thermal acceptance, and exact server platform remain
open.  
**Captured:** 2026-07-13.  
**Data handling:** aggregate byte/file counts only; no personal filenames,
contents, credentials, public IP address, or full device identifiers are
recorded here.

## Gate 0 decision

Proceed on this provisional basis:

```text
Life Center chassis    Fractal Design Node 804 (FD-CA-NODE-804-BL-W)
Primary pool           2 x 12 TB new CMR NAS HDD, ZFS mirror
Appdata                2 TB NVMe by default; 1 TB only with a written clean
                       appdata forecast below 400–500 GiB after cleanup
Local backup           initially, a dedicated old-laptop encrypted append-only
                       repository for a measured critical subset below 1.2 TiB;
                       WD Elements 16 TB becomes mandatory at its trigger
Off-site               Backblaze B2, client-side encrypted, initially only
                       the irreplaceable/selected expensive-to-recreate set
UPS                    APC Back-UPS Pro BR1000MS, 1000 VA / 600 W, USB, sine wave
Life Center location   upstairs office beside modem/UDR7, subject to noise/heat test
Network                direct 2.5 GbE UDR7 links to Life Center and downstairs
                       desktop; no switch or second access point initially
Network gateway        UniFi Dream Router 7 (UDR7), replacing—not nesting behind—
                       the basic Spectrum router when the Life Center is built
CasaOS                 omitted
Password manager       Bitwarden Cloud through Gate 7
```

The purchase-day drive-size choice is **12 TB**, provided a new, authorized-
seller, warranty-backed pair remains within 15% of the comparable 10 TB pair.
Compare exact CMR models `ST12000VN0008` (Seagate IronWolf) and `WD120EFGX`
(WD Red Plus); buy the better authorized-retailer/warranty value, ideally from
different shipment batches. Do not buy used, renewed, shucked, or marketplace-
seller drives for the primary pool.

This is a provisional architecture selection, not authorization to order. The
final bill of materials remains blocked on the inter-floor route and upstairs
noise/thermal acceptance, exact motherboard/SATA/PSU/cooling selection, the
first 30-day growth result, and a fresh same-day price/warranty check.

## Desktop evidence

### Disk and immediate risk

| Item | Measured result | Consequence |
| --- | ---: | --- |
| Physical disk | Corsair MP600 CORE XT NVMe, nominal 2 TB, Windows reports healthy | Only physical data disk detected. It is not redundant. |
| C: usable size | about 1.82 TiB | Consistent with a nominal 2 TB drive. |
| C: used | about 1.69 TiB | Approximately 93% occupied. |
| C: free | about 131.5 GiB | Below the plan's 15% free-space comfort floor; active CV/model/Docker growth is an immediate operational risk. |
| Wired adapter | Intel I225-V, 2.5 GbE capable, disconnected | Cable the stationary desktop and Life Center; do not design bulk transfer around Wi-Fi. |
| Current active link | Intel Wi-Fi 6E, negotiated 1.2 Gb/s | Negotiated PHY rate is not measured file-transfer throughput. |

Do not perform a blind Docker prune or delete repositories/caches. Betts and CV
services are live, and reclaimability is not proof that an artifact is safe to
remove. A separate reviewed cleanup/desktop-expansion task should identify
owners, canonical copies, active image digests, and rollback evidence first.

### Major aggregate categories

These categories are intentionally coarse and some are reproducible caches, not
Life Center migration candidates:

| Category | Aggregate size | Classification note |
| --- | ---: | --- |
| Docker local data file | 533.05 GiB | Runtime state; inspect and reduce, do not archive wholesale. |
| VS Code project tree | 153.96 GiB | Includes repos, data, environments, caches, worktrees, and Git history. |
| Ollama models | 53.04 GiB | Reproducible unless locally modified; archive manifests/hashes first. |
| Hugging Face cache | 51.86 GiB | Primarily reproducible; hard-to-recreate fine-tunes are handled separately. |
| OneDrive-synced personal tree | 53.89 GiB | Candidate personal/site-independent backup set after classification. |
| Standard local Documents/Pictures/Videos/Desktop/Downloads | negligible outside synced locations | Does not prove that all personal data is present on this desktop. |

The categories above total about **846 GiB** without double-counting the project
subtrees below. Approximately **885 GiB** of used disk remains Windows,
applications, other user state, filesystem overhead, or not-yet-classified
content. It is not assumed to require Life Center retention.

Docker reported this logical allocation inside its 533 GiB local data file:

| Docker class | Reported size | Reported reclaimable |
| --- | ---: | ---: |
| Images | 274.6 GB | 257.6 GB (93%) |
| Containers | 31.0 GB | 19.28 GB (62%) |
| Local volumes | 79.6 GB | 24.64 GB (30%) |
| Build cache | 78.78 GB | 16.06 GB |

These are Docker's decimal units and may overlap storage-layer overhead. They
show a cleanup opportunity, not permission to delete.

### Basketball/CV project tree

| Aggregate | Size | Gate 0 interpretation |
| --- | ---: | --- |
| Betts Basketball repository/tree | 121.98 GiB | Largest project tree; contains considerable reproducible duplication. |
| Homography repositories combined | 17.09 GiB | Includes about 11.3 GiB of environments and 2.7 GiB of data/weights. |
| Backup Git tree | 11.03 GiB | Determine whether it is a real independent recovery copy or only duplication on the same disk. |
| Betts explicit `data` | 21.24 GiB | Includes 14.76 GiB CV plus smaller news/fatigue/odds/bronze/silver sets. |
| Betts `serving` | 14.42 GiB | Mostly serving artifacts; retain only versioned promoted artifacts. |
| Betts `cache` | 10.76 GiB | Reproducible/temporary by default; policy and promotion decide exceptions. |
| Betts `reports` | 4.82 GiB | Mostly CV and odds reports; select final evidence, not every run. |
| Betts `models` | 1.57 GiB | Classify locally trained artifacts separately from public bases. |
| Betts `.r2_mirror` + staging | about 1.09 GiB | Staging is not authoritative; validate local mirror purpose/retention. |
| Betts `.claude` worktrees | 22.02 GiB | Duplicated working state, not archive data. |
| Betts `.git`, environments, type caches, temporary trees | more than 12 GiB | Reproducible development state; preserve source/remotes/locks, not bulk copies. |

The API source tree also contains about 28 GiB and needs its own ownership check;
its size alone is not evidence that it is canonical data. No deletion or archive
classification is made from directory names alone.

## Capacity conclusion

The current measured durable candidates are far below the **8.73 TiB planning
ceiling** of a 12 TB mirror. Even copying the entire currently used desktop disk
would fit, although doing so would preserve large amounts of reproducible and
unclassified state unnecessarily.

Therefore:

- `2 x 12 TB` is the correct starting pool;
- `2 x 16 TB` is not justified by the current snapshot;
- select 16 TB instead only if retained inventory exceeds roughly 5 TB or the
  first measured retained-growth rate exceeds roughly 1.5 TB/year;
- reserve at least 20%, alert at 70% pool usage, and require an expansion or
  eviction plan before 80%; and
- keep active models, Docker, current CV batches, and frame scratch on desktop
  NVMe; archive only selected sources/results/models to the Life Center.

## Growth measurement

There is no older comparable byte manifest, so **retained growth is not yet
known**, but measurement is now running. File modification dates cannot honestly
substitute for net retained growth because files can be rewritten, moved,
compressed, or deleted.

The aggregate-only tracker
[`scripts/measure_life_center_growth.ps1`](../../scripts/measure_life_center_growth.ps1)
was validated and the Windows task `LLMStation-LifeCenterGrowth` was registered
for 7:30 PM daily with `StartWhenAvailable`. It writes ignored local evidence to
`generated/life-center-growth/`; it records target labels, byte/file counts, and
enumeration error counts, never filenames or contents. The targets overlap and
**must not be added together**.

First valid automated snapshot, `20260713-135526`:

| Measurement target | Class | Size | Errors | Interpretation |
| --- | --- | ---: | ---: | --- |
| Personal synced tree | retained review | 53.89 GiB | 0 | classify for personal/site-independent backup |
| Projects envelope | envelope only | 153.98 GiB | 8 | capacity signal only; not a complete retained total |
| Betts data | retained review | 21.24 GiB | 0 | classify raw, curated, and reproducible data |
| Betts models | retained review | 1.57 GiB | 0 | promote only hard-to-recreate/versioned models |
| Betts reports | retained review | 4.82 GiB | 0 | retain final evidence, not every run |
| Betts serving | retained review | 14.42 GiB | 0 | retain promoted serving artifacts only |
| Betts R2 mirror | retained review | 0.99 GiB | 0 | verify authority and retention purpose |
| Homography data | retained review | 1.46 GiB | 0 | classify sources, labels, weights, and scratch |
| Homography runs | retained review | under 0.01 GiB | 0 | currently negligible |
| Ollama models | reproducible | 53.04 GiB | 0 | preserve manifests/hashes, not all blobs by default |
| Hugging Face cache | reproducible | 51.86 GiB | 0 | preserve non-public fine-tunes separately |
| Docker runtime file | runtime envelope | 532.83 GiB | 0 | inspect services/volumes; never treat wholesale as backup |
| System volume used/free | envelope | 1,728.81 / 133.12 GiB | 0 | immediate desktop capacity signal |

Review task health weekly with:

```powershell
Get-ScheduledTask -TaskName "LLMStation-LifeCenterGrowth"
Get-ScheduledTaskInfo -TaskName "LLMStation-LifeCenterGrowth"
```

Use this snapshot as baseline `G0-DATA-20260713`. Produce the first trend report
on **2026-08-13** (more than 30 days), then retain monthly comparisons for at
least three months. Record:

- personal/synced files;
- permitted photo/video originals;
- website DB/object exports;
- curated CV source, annotations, final results, and promoted clips;
- hard-to-recreate models/evals;
- legally held media;
- appdata/database backups; and
- reproducible cache/scratch separately, never blended into retained growth.

Compute `net retained growth = current classified bytes - previous classified
bytes`, while also recording new ingestion and policy-driven deletion. Do not
annualize a single unusual ingest month without labeling the uncertainty.

## Spectrum router and network decision

The gateway hostname observed from the desktop is `SAX1V1R`, identifying the
Spectrum Wi-Fi 6 router family. Despite appearing to be the only gateway, this
is **not a combined modem/router**: Spectrum's own `SAX1V1X` family guide labels
its Internet port as Ethernet WAN and says to connect it to a modem. Follow the
WAN cable to locate and label the separate Spectrum modem; do not record its
serial number or MAC address in this repository. The exact modem model is not
needed to select the architecture.

The Spectrum account reports **Internet Ultra — 600 Mbps**, lists **Internet
Modem** equipment, and offers **Advanced WiFi** as `Add`, so Advanced WiFi is not
treated as an active subscribed add-on. The observed `SAX1V1R` remains a
transitional flat-home router, not the Life Center security boundary. Because
the account equipment list and observed LAN identity do not establish ownership
or return obligations, confirm with Spectrum before returning the router.

Observed safely from the desktop:

| Check | Result |
| --- | --- |
| Router family | Spectrum `SAX1V1R`, Wi-Fi 6 / 802.11ax |
| ISP topology | separate Spectrum modem feeding the router's Ethernet WAN port; no bridge mode is expected to be necessary |
| Subscribed tier | Spectrum Internet Ultra, 600 Mb/s advertised download; provisioned upload was not shown and is not inferred |
| Account add-on state | Advanced WiFi presented as `Add`, so it is not recorded as active |
| Physical placement | modem/router upstairs office; desktop downstairs in a different office |
| LAN | one visible flat `192.168.1.0/24` network |
| Gateway/DHCP/DNS | the same local gateway provides all three |
| Router web UI | gateway responds to ICMP but TCP 80 and 443 were closed from this client |
| Current desktop Wi-Fi | 5 GHz, Wi-Fi 6, `-42 dBm` / 95% signal and 1,201 Mb/s negotiated PHY; SSID/BSSID omitted |
| Tailscale | active on the desktop; specific node addresses intentionally omitted |
| Spectrum management | provider-managed through the My Spectrum app; exact controls vary by router/generation |
| VLANs / isolated management-services-IoT routing | not documented or proven |
| LAN ports | three 1 GbE LAN ports documented for the Spectrum Wi-Fi 6 family |
| DHCP reservations / DNS override and rollback | not relied on for the target design |

Spectrum documents device viewing/control in the My Spectrum app. The official
[Spectrum Wi-Fi 6 guide](https://drupal-cms.spectrum.net/sites/default/files/2023-10/20230621%20WiFi%206%20User%20Guide.pdf)
documents this router family's separate modem connection, app management,
concurrent 2.4/5 GHz Wi-Fi 6 radios, and three Gigabit LAN ports. Spectrum's
Wi-Fi 6E guide also documents port forwarding, UPnP on/off, and configurable
DNS. Those are useful household controls, but Spectrum does not document the multiple
802.1Q VLANs, per-zone DHCP/subnets, SSID-to-VLAN mapping, and default-deny
inter-zone firewall policy required here. See
[Spectrum Advanced WiFi](https://www.spectrum.com/internet/wifi-service/spectrum-advanced-wifi)
and the [Spectrum Wi-Fi 6E guide](https://drupal-cms.spectrum.net/sites/default/files/2024-09/20240729%20WiFi%206E%20User%20Guide%5B1%5D.pdf).

Tailscale grants and host firewalls protect management paths, but they do not
replace local-LAN segmentation. The Spectrum router may remain in service until
the Life Center network is staged; do not place real Life Center data or IoT
trust assumptions behind unproven segmentation.

### Selected replacement: UniFi Dream Router 7

Select the **UniFi Dream Router 7 (`UDR7`)**, currently listed at $279, as the
smallest single-appliance replacement that meets this plan without requiring a
separate firewall, controller, switch, and access point on day one. It provides:

- integrated Wi-Fi 7;
- four 2.5 GbE RJ45 ports, including the default WAN assignment and one PoE port;
- a 10 GbE SFP+ port;
- approximately 2.3 Gb/s IDS/IPS routing;
- 802.1Q VLAN/subnet segmentation, guest isolation, customizable DHCP, IPv6,
  WireGuard, and zone-based firewalling; and
- a local UniFi control plane; optional paid threat-signature/support services
  are not required for the initial design.

Its approximately 2.3 Gb/s IDS/IPS capacity provides ample headroom over the
600 Mb/s Internet Ultra download tier. The purchase is for segmentation,
security policy, local control, 2.5 GbE LAN, and future growth—not because the
current internet tier requires a multi-gigabit router.

Official references: [UDR7 store page](https://store.ui.com/us/en/products/udr7),
[technical specifications](https://techspecs.ui.com/unifi/cloud-gateways/udr7),
and [VLAN guidance](https://help.ui.com/hc/en-us/articles/9761080275607-Creating-Virtual-Networks-VLANs).

The UDR7's three immediately available 2.5 GbE LAN connections are enough for
the Life Center, the direct inter-floor desktop run, and one disabled spare or
future wired access point. No managed switch belongs in the initial purchase.
Add one only when device count or a changed physical layout requires it; an
unmanaged switch must not carry mixed trust zones.

### Target network

```text
Spectrum coax/fiber handoff
└── Upstairs office
    ├── Spectrum modem (keep; ISP demarcation only)
    ├── UDR7 WAN
    │   ├── LAN A: Life Center, native VLAN 10 + tagged VLAN 20
    │   ├── LAN B: Cat6 inter-floor run, access VLAN 30 → desktop
    │   └── LAN C: disabled spare; future wired AP if measurement requires it
    ├── Life Center
    └── BR1000MS UPS: modem + UDR7 + Life Center

Logical zones
├── VLAN 10 Management  10.10.10.0/24  admin devices/interfaces only
├── VLAN 20 Services    10.10.20.0/24  Life Center service listeners
├── VLAN 30 Trusted     10.10.30.0/24  personal phones/computers
├── VLAN 40 IoT         10.10.40.0/24  TVs, speakers, sensors
└── VLAN 50 Guest       10.10.50.0/24  internet only
```

Use three Wi-Fi identities: Trusted, IoT, and Guest, each mapped to its VLAN.
Management is wired or available only to specifically approved administrator
devices; Services is primarily wired. SSID names and credentials are secrets and
never enter this repository.

Initial wired port profiles:

| UDR7 LAN role | Native/untagged network | Tagged networks | Enforcement |
| --- | --- | --- | --- |
| Life Center | Management / VLAN 10 | Services / VLAN 20 only | Debian host management is untagged; service bridge is tagged; reject every other VLAN |
| Downstairs desktop | Trusted / VLAN 30 | none | access port; block tagged traffic |
| Spare / future AP | disabled | none | enable only from an approved port profile; an AP uplink later carries only required SSID VLANs |

Do not enable jumbo frames initially. Keep RSTP/loop protection and rogue-DHCP
detection enabled. Save the port profiles before migration and test both allowed
and denied flows from each connected device.

Initial firewall policy:

- deny inter-VLAN initiation by default;
- Management may reach explicitly listed administration ports;
- Trusted may reach approved user-facing Services ports;
- IoT may reach internet, approved DNS/NTP, and only the exact Home Assistant
  integration flows required; IoT cannot initiate to Management or Trusted;
- Guest may reach internet and approved DNS only;
- Services cannot initiate arbitrary connections to Trusted/Management;
- databases, Docker, backup administration, hypervisor, metrics-admin, and
  secret-management listeners remain unexposed outside Management/private
  container networks;
- UPnP is disabled; no public port forwarding or Tailscale Funnel; and
- mDNS reflection is off initially, then enabled only for named services/VLANs
  needed for casting, printing, or Home Assistant discovery.

### Spectrum-to-UDR7 migration

1. Follow the `SAX1V1R` Internet/WAN Ethernet cable and locate the separate
   Spectrum modem. Photograph the wiring only for private reference; record no
   serial, MAC, public IP, SSID, or password in repository evidence.
2. Record the confirmed Internet Ultra 600 Mb/s tier, connected-device
   inventory, and any port-forward/DNS settings. The account currently presents
   Advanced WiFi as an add-on rather than active service; confirm router
   ownership/return requirements with Spectrum. Connect UDR7 directly to the
   modem during migration; no permanent Spectrum-router hop belongs between the
   modem and UDR7.
3. Avoid permanent double NAT. It complicates inbound state, troubleshooting,
   gaming/casting, VPNs, and DNS behavior.
4. Configure/update UDR7 offline first; create zones, networks, DHCP, SSIDs,
   administrator MFA/local recovery, configuration backup, and deny tests.
5. Power-cycle the Spectrum modem when moving its Ethernet handoff, then connect
   one test client. Validate IPv4/IPv6, DNS, speed, Tailscale, isolation, and
   emergency rollback before migrating other devices.
6. Wire desktop and Life Center with Cat6. Measure real bidirectional throughput;
   link negotiation alone is not evidence.
7. Keep the Spectrum router powered off but available through the acceptance
   window. Return it only after stability and after checking whether the bill
   includes a removable Spectrum Wi-Fi/router charge.
8. Back up the sanitized UDR7 configuration and a printed/offline recovery path.

The modem, UDR7, and Life Center share the upstairs BR1000MS. This is why the
Life Center defaults upstairs: placing it downstairs would require a second
network UPS upstairs plus a managed switch downstairs. Internet service may
still fail upstream; the UPS preserves safe local operation and shutdown, not
guaranteed internet continuity.

### Internet tier, physical paths, and Wi-Fi coverage

The tier question is closed at **Internet Ultra, 600 Mb/s advertised download**.
The account excerpt did not state upload speed, so upload remains informational
and must not be guessed. After the wired path exists, run a quiet-network test
from the desktop and record redacted download, upload, latency, and timestamp;
performance evidence does not change the subscribed-tier record.

The Spectrum router is upstairs in the office and the desktop is downstairs in
a different office. The desktop nevertheless has excellent `-42 dBm` 5 GHz
signal. That cross-floor evidence supports buying **one UDR7 and no extra access
point initially**, retaining the current upstairs router position. It is only
one point, not whole-home proof. Keep the UDR7 open and raised—not in a rack,
closed cabinet, behind a TV, or inside the server chassis. Before final
acceptance, measure every required room and outdoor work area with the same
phone/laptop in its normal position:

- `-65 dBm` or better is preferred and `-70 dBm` is the stable minimum;
- record signal, latency, and download/upload in each location at two busy-day
  times on both a trusted client and representative 2.4 GHz IoT device;
- add a **wired** UniFi access point only if a required location remains below
  `-70 dBm`, unstable, or materially below its application requirement after
  reasonable UDR7 placement/channel adjustment; and
- do not plan a wireless mesh hop for the desktop or Life Center.

Physical design and remaining acceptance:

| Item | Selected design | Acceptance evidence |
| --- | --- | --- |
| Spectrum modem → UDR7 | upstairs office, short Cat6 patch | label privately and confirm stable WAN after modem power-cycle |
| UDR7 → Life Center | upstairs office, short Cat6, 2.5 GbE trunk profile | 2.5 GbE negotiation, VLAN allow/deny test, sustained transfer test |
| UDR7 → desktop | one dedicated Cat6 inter-floor run, 2.5 GbE access VLAN 30 | route approved, both ends certified/labeled, sustained transfer test |
| Wi-Fi | one upstairs UDR7 | room-by-room survey after placement; wired AP only on measured failure |
| Power | one upstairs BR1000MS for modem/UDR7/Life Center | measured load/runtime plus USB shutdown/restart test |

Use solid-copper Cat6—not copper-clad aluminum—with code-appropriate riser or
plenum rating, Cat6 keystones/wall plates, a maximum 100 m channel, strain
relief, fire-stopping where required, and separation from mains wiring. Label
both ends without personal room names and validate wiremap plus 2.5 GbE under
load. Use a qualified low-voltage installer if floor/wall penetrations or local
code require one.

The Life Center default is the upstairs office beside the network equipment.
Place it on a stable raised surface in conditioned space with unobstructed intake
and exhaust, not carpet or a sealed cabinet. Before final commitment, accept a
24-hour noise/temperature test in that working office. If noise or heat fails,
the fallback is Life Center downstairs plus a `USW-Flex-2.5G-5` managed switch
and a separate small network UPS upstairs; do not improvise an extension cord
between floors.

## Selected hardware and services

### Chassis

Select **Fractal Design Node 804**, product code `FD-CA-NODE-804-BL-W`, if it is
available new from a reputable seller at purchase time. It supports micro-ATX,
eight dedicated 3.5-inch positions, two 2.5-inch positions, additional flexible
positions, ATX power supplies, and extensive fan placement. This supplies more
than the required four bays without proprietary drive trays or an appliance OS.
See the [official specifications](https://www.fractal-design.com/products/cases/node/node-804/black/).

Before order, lock a compatible Intel-iGPU micro-ATX platform with:

- 32 GB RAM;
- 2.5 GbE;
- at least four native SATA ports and two M.2 positions;
- direct SMART/ZFS visibility (no hardware RAID abstraction);
- an ATX PSU with enough independent SATA power connectors and spin-up margin;
- drive-side intake/exhaust cooling; and
- Intel Quick Sync support. An i5-12500/UHD 770-class used platform is sufficient;
  do not pay for another discrete GPU.

### UPS

Select **APC BR1000MS**: 1000 VA/600 W, sine-wave output, AVR, USB monitoring,
and user-replaceable battery. Its capacity is appropriate for a low-power server,
network equipment, and controlled shutdown without paying for a GPU-sized UPS.
See [Schneider Electric's product page](https://www.se.com/us/en/product/BR1000MS/apc-backups-pro-1000va-600w-tower-120v-10x-nema-515r-outlets-sine-wave-avr-usb-type-a-%2B-c-ports-lcd-user-replaceable-battery/).

Acceptance is conditional on a Linux USB/NUT or APCUPSD detection test, a real
load/runtime measurement, low-battery shutdown, restart behavior, battery-date
record, and annual test. The CyberPower `CP1000PFCLCDa` is the fallback only if
it has materially better local price/support and passes the same test.

### Backup destinations

1. **Separate local:** a healthy old 2 TB laptop may initially hold only the
   measured critical subset below 1.2 TiB as a dedicated encrypted append-only
   repository. It is not a worker, cache, browser, or general desktop. It must
   pass SMART short/long tests, a sustained write plus read/surface test,
   encryption/recovery-key verification, append-only delete-denial, and sample
   file/database restores. WD Elements Desktop 16 TB, `WDBWLG0160HBK-NESN`, is
   the encrypted disconnected full-pool target when any trigger in
   [`LIFE_CENTER_IMPLEMENTATION_READINESS.md`](LIFE_CENTER_IMPLEMENTATION_READINESS.md)
   is met. USB is acceptable for backup, not for the primary ZFS mirror.
2. **Off-site:** Backblaze B2 pay-as-you-go with client-side encryption and a
   narrowly scoped append/write credential. Protect deletion/retention with a
   separate operator identity and enable object immutability where compatible
   with the selected backup tool. Use a 0.5–1 TB highest-value starting set
   (roughly $3.48–$6.95/month at the cited $6.95/TB-month planning rate, before
   tax/future pricing). Do not send reproducible Docker images, public base
   models, frame caches, or replaceable media off-site by default. See
   [official B2 pricing](https://www.backblaze.com/cloud-storage/pricing).

The external disk and B2 are independent recovery layers, not mirrors managed by
the production host. A backup is not accepted until a restore is proven.

### Selected recovery objectives

`RPO` is the maximum acceptable loss of recent changes; `RTO` is the target time
to restore usable access. These are initial targets, not proven guarantees:

| Data/service class | RPO | RTO | Required recovery layers |
| --- | ---: | ---: | --- |
| Recovery keys, sanitized network/infra config, service manifests | after every change, no more than 24 h | 4 h | encrypted local backup + encrypted off-site + offline recovery copy |
| Website DB/object exports and operational structured data | 24 h | 8 h | application-consistent export, Life Center snapshot, daily encrypted off-site |
| Home Assistant config/history needed for operation | 24 h | 8 h | daily application backup, separate local, selected encrypted off-site; manual controls remain available |
| Personal documents and permitted photo/video originals | 24 h | 48 h | snapshots, separate local, daily encrypted off-site for irreplaceable set |
| CV annotations, curated source, promoted models/evals/results | 24 h | 72 h | versioned manifest, separate local, encrypted off-site when expensive/irreplaceable |
| Replaceable media, public base models, caches, derived frames | 7 days or re-download | 14 days / best effort | local catalog/checksums; off-site excluded by default |

Use six-hour local snapshots for rapid rollback, nightly application-aware
exports, daily encrypted off-site backup for the high-priority set, and a weekly
encrypted disconnected-disk cycle. Snapshots on the production pool do not
satisfy independent backup. Verify jobs daily, perform quarterly sampled
file/database restores, and perform an annual bare-host recovery drill. Change
these targets only with a documented impact/cost decision.

### Drive-price checkpoint — 2026-07-13

This is a research snapshot, not an order authorization:

| Exact new CMR model | Current observed US price | Pair | Decision today |
| --- | ---: | ---: | --- |
| Seagate IronWolf 12 TB `ST12000VN0008` | $429.99 at B&H and Newegg | $859.98 | current value leader, conditional on authorized sale and full warranty |
| WD Red Plus 12 TB `WD120EFGX` | $538.99 new price shown by B&H | $1,077.98 | technically qualified but not the current value choice |

WD documents `WD120EFGX` as 12 TB, 7,200 RPM, CMR, 512 MB cache with a three-year
limited warranty. The B&H IronWolf listing identifies `ST12000VN0008` as CMR and
12 TB. At current pricing, buy neither early; re-run the comparison on order day.
Reject third-party marketplace, OEM/international-no-warranty, renewed, used,
and recertified listings even when much cheaper.

Purchase-day procedure:

1. Compare exact 10/12/16 TB CMR models at the manufacturer and at least two
   reputable authorized US sellers; filter for seller-of-record, not marketplace.
2. Verify new condition, US warranty eligibility, return window, stock, shipping
   packaging, model suffix, SATA interface, CMR, and total after tax/shipping.
3. Prefer two separately shipped/packaged units or different lot codes without
   sacrificing seller/warranty quality.
4. Keep 12 TB when its qualified pair is within 15% of the comparable 10 TB pair.
   Move to 16 TB only if the measured retention/growth thresholds in this plan
   are crossed or its qualified per-TB value is materially better.
5. Save a redacted purchase record and validate both serial warranties privately
   on arrival; record only internal asset aliases in the repository.

## Budget envelope

Use a planning range, not a quote:

| Component group | Planning range before tax |
| --- | ---: |
| Node 804 host platform, 32 GB, 2 TB NVMe, PSU/cooling/cables | $700–$1,000 |
| Two new 12 TB CMR NAS drives | $800–$860 target |
| Dedicated old-laptop critical backup | reuse only after every qualification gate passes |
| Separate 16 TB local backup | deferred $300–$500 until full-pool trigger |
| 1000 VA sine-wave UPS | $150–$250 |
| UDR7 network gateway | $279 current list price |
| Direct Cat6 inter-floor run, terminations, patching | $50–$600 DIY-to-professional allowance |
| **Initial hardware total without deferred USB backup** | **$1,979–$2,989** |
| B2 for 0.5–1 TB selected off-site data | **about $3.48–$6.95/month** |

No switch or extra access point is in the initial total. The downstairs-server
fallback adds a UniFi Flex Mini 2.5G (`USW-Flex-2.5G-5`, currently $49) and an
approximately $80–$150 upstairs network UPS before tax/installation. The switch
has five managed 2.5 GbE ports and can use USB-C or PoE input; it does not supply
PoE to an access point. See the [official store page](https://store.ui.com/us/en/category/switching-utility/products/usw-flex-2-5g-5)
and [technical specifications](https://techspecs.ui.com/unifi/switching/usw-flex-2-5g-5).

Re-price exact SKUs from authorized sellers on order day. If a qualified reused
Intel tower already satisfies bays, cooling, SATA visibility, power, and 2.5 GbE,
it may reduce the host-platform line; do not sacrifice those gates merely to
reuse a machine.

## Remaining Gate 0 exits

Gate 0 is complete only after:

- the exact inter-floor Cat6 route/installation allowance is accepted;
- the upstairs Life Center location passes its acoustic/thermal review, or the
  documented downstairs switch/second-UPS fallback is selected;
- the motherboard, CPU, RAM, NVMe, PSU, fans, and SATA cabling are exact SKUs;
- the dedicated-laptop critical-backup conditions pass, or the full-pool USB
  backup is included in the purchase; and the off-site budget is accepted;
- the 2026-08-13 growth report exists (or the owner explicitly accepts the
  uncertainty for a 12 TB purchase);
- the selected RPO/RTO targets and backup operating cost are accepted; and
- every purchase price, seller authorization, warranty, return policy, and exact
  drive recording technology is revalidated the same day.

"""Life Center service catalog (schema v2) — typed, version-controlled, stable
facts only.

Backs `lc catalog`/`lc links`/`lc link-check`/`lc open` (never prints secret
values, only credential *reference* names) and is the intended future source
of truth for a Kanban "Service Catalog" projection. Changing facts (health,
backup age, restore-test age) belong in `lc verify` / a future status
exporter, not here — this file is stable facts, not a status feed.

Stdlib only (dataclasses/hashlib/json), matching lc.py's own constraint.

CAVEAT: `auth`/`setup` fields below are a first pass authored from each
project's general documentation, not independently re-verified against every
app's current release. Verify against the actual app before anything in the
`automation` section is wired to a real action broker.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

SCHEMA_VERSION = "life-center.catalog.v2"


@dataclass(frozen=True)
class Links:
    app: str | None = None       # host-test URL (loopback); tailnet URL comes later
    setup: str | None = None     # first-run/setup route, often same as `app`
    docs: str = ""
    runbook: str = ""
    status: str | None = None    # per-service monitor deep link — none until Uptime Kuma monitors exist
    native: str | None = None    # native client info page — unpopulated pending device/client decisions


@dataclass(frozen=True)
class Auth:
    mode: str = "local"                          # local | oidc | token | none | host-level
    username_ref: str | None = None
    credential_ref: str | None = None             # env var NAME only — never a value
    password_manager_item_ref: str | None = None  # set once real vault items exist
    supports_oidc: bool = False
    supports_scoped_token: bool = False


@dataclass(frozen=True)
class Setup:
    wizard_required: bool = False
    registration_must_close: bool = False
    default_credentials_must_rotate: bool = False
    note: str = ""


@dataclass(frozen=True)
class Recovery:
    canonical_data_location: str = ""
    complete_backup_unit: str = ""
    export_method: str = ""
    restoration_proof: str = ""
    backup_slo_hours: int | None = None
    restore_test_slo_days: int | None = None


@dataclass(frozen=True)
class Automation:
    health_probe_id: str | None = None
    read_capabilities: tuple[str, ...] = ()
    admitted_action_ids: tuple[str, ...] = ()   # empty everywhere: no action broker exists yet


@dataclass(frozen=True)
class ServiceEntry:
    service_id: str
    application: str
    category: str
    authority: str          # what this service IS the authority for
    lifecycle: str           # keep | conditional | add | gate-later | privileged-admin-only | client | host-level | n/a
    profile: str             # lc --profile tier name, or "client"/"desktop"/"host" for non-compose items
    links: Links
    auth: Auth
    setup: Setup
    recovery: Recovery
    automation: Automation
    dependencies: tuple[str, ...] = ()
    risk_tier: str = "low"    # low | moderate | sensitive | privileged


SERVICES: tuple[ServiceEntry, ...] = (
    ServiceEntry(
        service_id="uptime-kuma", application="Uptime Kuma", category="foundation",
        authority="endpoint/probe health — Command Center projects its sanitized results",
        lifecycle="keep", profile="foundation",
        links=Links(app="http://127.0.0.1:${UPTIME_KUMA_PORT:-3011}",
                     setup="http://127.0.0.1:${UPTIME_KUMA_PORT:-3011}",
                     docs="https://github.com/louislam/uptime-kuma", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", supports_oidc=False, supports_scoped_token=False),
        setup=Setup(wizard_required=True, note="first visit creates the owner account"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/uptime-kuma",
                           complete_backup_unit="appdata/uptime-kuma (sqlite)",
                           export_method="Settings > Backup (JSON export)",
                           restoration_proof="import JSON into a clean instance"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="restic", application="Restic", category="foundation",
        authority="the one backup engine (3-2-1) — do not run Kopia in parallel",
        lifecycle="keep", profile="foundation",
        links=Links(docs="https://restic.readthedocs.io/", runbook="runbooks/backup-restore.md"),
        auth=Auth(mode="token", credential_ref="RESTIC_PASSWORD"),
        setup=Setup(),
        recovery=Recovery(canonical_data_location="${LC_BACKUP_TARGET} (local) + B2 off-site",
                           complete_backup_unit="the repo itself",
                           export_method="n/a — restic IS the export/backup mechanism",
                           restoration_proof="`lc restore-test` clean-instance restore drill, dated"),
        automation=Automation(), risk_tier="privileged",
    ),
    ServiceEntry(
        service_id="tailscale", application="Tailscale", category="foundation",
        authority="private network transport for every loopback-bound service",
        lifecycle="host-level", profile="host",
        links=Links(docs="https://tailscale.com/kb/",
                     runbook="docs/operations/HARDWARE_AND_LIFE_CENTER_PLAN.md"),
        auth=Auth(mode="host-level"),
        setup=Setup(note="host-level daemon; not part of this compose stack"),
        recovery=Recovery(canonical_data_location="host tailscale state (not in this repo)",
                           complete_backup_unit="n/a (re-authenticates)", export_method="n/a",
                           restoration_proof="re-join tailnet on a fresh host"),
        automation=Automation(), risk_tier="moderate",
    ),
    ServiceEntry(
        service_id="nextcloud", application="Nextcloud", category="core",
        authority="ordinary files, folder sync, Calendar/Contacts, Joplin WebDAV transport",
        lifecycle="keep", profile="files",
        links=Links(app="http://127.0.0.1:${NEXTCLOUD_PORT:-8085}",
                     docs="https://docs.nextcloud.com/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", username_ref="admin", credential_ref="NEXTCLOUD_ADMIN_PASSWORD",
                   supports_scoped_token=True),  # built-in "create app password" for WebDAV/API clients
        setup=Setup(default_credentials_must_rotate=False,
                     note="admin password is a fresh generated secret (lc setup), not a hardcoded default"),
        recovery=Recovery(canonical_data_location="${LC_DATA}/personal",
                           complete_backup_unit="LC_DATA/personal + nextcloud_db_data volume",
                           export_method="occ export / raw file copy + pg_dump",
                           restoration_proof="clean-instance restore + WebDAV client re-sync"),
        automation=Automation(), dependencies=("nextcloud-db",), risk_tier="moderate",
    ),
    ServiceEntry(
        service_id="immich", application="Immich", category="core",
        authority="sole mobile photo-upload destination + photo/video library (viewer/organizer, not sole copy)",
        lifecycle="keep", profile="photos",
        links=Links(app="http://127.0.0.1:${IMMICH_PORT:-2283}",
                     docs="https://immich.app/docs/overview/introduction", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", credential_ref="IMMICH_DB_PASSWORD", supports_scoped_token=True),
        setup=Setup(wizard_required=True, registration_must_close=True,
                     note="claim the first admin account, then close public registration"),
        recovery=Recovery(canonical_data_location="${LC_DATA}/photos",
                           complete_backup_unit="LC_DATA/photos + immich_db_data volume",
                           export_method="bulk download / immich-go",
                           restoration_proof="clean-instance restore + duplicate/import drill"),
        automation=Automation(), dependencies=("immich-db", "immich-redis"), risk_tier="moderate",
    ),
    ServiceEntry(
        service_id="paperless-ngx", application="Paperless-ngx", category="core",
        authority="OCR, classification, correspondence, scanned-records retrieval",
        lifecycle="keep", profile="docs",
        links=Links(app="http://127.0.0.1:${PAPERLESS_PORT:-8000}",
                     docs="https://docs.paperless-ngx.com/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", username_ref="admin", credential_ref="PAPERLESS_SECRET_KEY",
                   supports_scoped_token=True),
        setup=Setup(default_credentials_must_rotate=True,
                     note="trial superuser created via non-interactive CLI with a KNOWN throwaway "
                          "password (PaperlessTrial123!) — rotate before any real data"),
        recovery=Recovery(canonical_data_location="${LC_DATA}/personal/paperless/{media,consume,export}",
                           complete_backup_unit="above + paperless_db_data + paperless_data volumes",
                           export_method="document_exporter (supported clean-restore path)",
                           restoration_proof="document_importer into a clean, version-matched instance"),
        automation=Automation(), dependencies=("paperless-db", "paperless-redis"), risk_tier="sensitive",
    ),
    ServiceEntry(
        service_id="joplin", application="Joplin", category="core",
        authority="notes (Nextcloud only transports encrypted sync — never opens notes itself)",
        lifecycle="add", profile="client",
        links=Links(docs="https://joplinapp.org/help/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="client-side setup; point sync target at Nextcloud WebDAV"),
        recovery=Recovery(canonical_data_location="client-local + Nextcloud WebDAV sync target",
                           complete_backup_unit="scheduled JEX export", export_method="File > Export > JEX",
                           restoration_proof="import JEX into a clean profile"),
        automation=Automation(), dependencies=("nextcloud",), risk_tier="moderate",
    ),
    ServiceEntry(
        service_id="jellyfin", application="Jellyfin", category="media", authority="movies and television",
        lifecycle="keep", profile="media",
        links=Links(app="http://127.0.0.1:${JELLYFIN_PORT:-8096}",
                     docs="https://jellyfin.org/docs/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="finish the setup wizard; use a sample/dummy library"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/jellyfin (config/cache) + ${LC_DATA}/media (ro)",
                           complete_backup_unit="appdata/jellyfin config only (media is not Jellyfin's to back up)",
                           export_method="n/a — config export via Dashboard",
                           restoration_proof="rebuild library from config + sample media restore"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="audiobookshelf", application="Audiobookshelf", category="media",
        authority="audiobooks and podcasts (progress sync, mobile clients)", lifecycle="keep", profile="media",
        links=Links(app="http://127.0.0.1:${AUDIOBOOKSHELF_PORT:-13378}",
                     docs="https://audiobookshelf.org/docs/documentation/introduction/",
                     runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="finish the setup wizard; use a sample/dummy library"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/audiobookshelf",
                           complete_backup_unit="appdata/audiobookshelf (config+metadata)",
                           export_method="Settings > Backups", restoration_proof="restore backup into a clean instance"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="calibre-web", application="Calibre-Web", category="ebooks",
        authority="ebooks — Calibre DB, OPDS, metadata editing, conversion (disabled by default)",
        lifecycle="conditional", profile="ebooks",
        links=Links(app="http://127.0.0.1:${CALIBRE_WEB_PORT:-8083}",
                     docs="https://github.com/janeczku/calibre-web/blob/master/README.md",
                     runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", username_ref="admin"),
        setup=Setup(default_credentials_must_rotate=True,
                     note="default admin/admin123 — no CLI path found; rotate via Settings > Edit User in-app"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/calibre-web + ${LC_DATA}/media/books",
                           complete_backup_unit="appdata/calibre-web (Calibre DB) + media/books",
                           export_method="raw file copy of the Calibre library",
                           restoration_proof="clean-instance restore + OPDS/reader re-check"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="linkwarden", application="Linkwarden", category="lifestyle",
        authority="durable web archive — promote worth-keeping material from FreshRSS here",
        lifecycle="keep", profile="lifestyle",
        links=Links(app="http://127.0.0.1:${LINKWARDEN_PORT:-3010}",
                     docs="https://docs.linkwarden.app/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", credential_ref="LINKWARDEN_NEXTAUTH_SECRET"),
        setup=Setup(wizard_required=True, registration_must_close=True,
                     note="create the owner account, then close open registration"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/linkwarden/data",
                           complete_backup_unit="appdata/linkwarden + linkwarden_db_data volume",
                           export_method="built-in export", restoration_proof="clean-instance restore"),
        automation=Automation(), dependencies=("linkwarden-db",), risk_tier="low",
    ),
    ServiceEntry(
        service_id="freshrss", application="FreshRSS", category="lifestyle",
        authority="temporary reading inbox (RSS) — not a durable archive", lifecycle="keep", profile="lifestyle",
        links=Links(app="http://127.0.0.1:${FRESHRSS_PORT:-8082}",
                     docs="https://freshrss.github.io/FreshRSS/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="first visit creates the admin account"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/freshrss", complete_backup_unit="appdata/freshrss",
                           export_method="OPML export", restoration_proof="import OPML into a clean instance"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="mealie", application="Mealie", category="lifestyle",
        authority="recipes and meal planning (the only recipe database)", lifecycle="conditional", profile="lifestyle",
        links=Links(app="http://127.0.0.1:${MEALIE_PORT:-9925}",
                     docs="https://docs.mealie.io/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", username_ref="changeme@example.com", supports_scoped_token=True),
        setup=Setup(default_credentials_must_rotate=True,
                     note="default changeme@example.com / MyPassword — rotate via user profile"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/mealie/data", complete_backup_unit="appdata/mealie/data",
                           export_method="built-in backup export", restoration_proof="clean-instance restore"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="homebox", application="Homebox", category="lifestyle",
        authority="household inventory (item/location/model/replacement info)", lifecycle="conditional",
        profile="lifestyle",
        links=Links(app="http://127.0.0.1:${HOMEBOX_PORT:-7745}",
                     docs="https://homebox.software/en/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, registration_must_close=True,
                     note="HBOX_OPTIONS_ALLOW_REGISTRATION=false is already set; if that blocks the very "
                          "first signup, temporarily flip it true, create your account, then set back to false"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/homebox/data",
                           complete_backup_unit="appdata/homebox/data (sqlite)",
                           export_method="built-in CSV export", restoration_proof="clean-instance restore"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="stirling-pdf", application="Stirling-PDF", category="lifestyle",
        authority="on-demand PDF utility — owns NO canonical data", lifecycle="conditional", profile="lifestyle",
        links=Links(app="http://127.0.0.1:${STIRLING_PDF_PORT:-8084}",
                     docs="https://docs.stirlingpdf.com/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="none"),
        setup=Setup(note="no login by default; verify temp files under /tmp/stirling-pdf get cleaned up"),
        recovery=Recovery(canonical_data_location="none canonical — save finals to Nextcloud/Paperless",
                           complete_backup_unit="n/a", export_method="n/a", restoration_proof="n/a (stateless)"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="actual", application="Actual Budget", category="finance",
        authority="personal finance — Kanban gets health/recovery status only, never balances",
        lifecycle="gate-later", profile="finance",
        links=Links(app="http://127.0.0.1:${ACTUAL_PORT:-5006}",
                     docs="https://actualbudget.org/docs/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", credential_ref="ACTUAL_PASSWORD"),
        setup=Setup(note="password is set directly from ACTUAL_PASSWORD — no separate wizard step"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/actual/data", complete_backup_unit="appdata/actual/data",
                           export_method="Settings > Export data (portable, optional E2E encryption)",
                           restoration_proof="export -> restore into a clean instance, proven before real finance data"),
        automation=Automation(), risk_tier="sensitive",
    ),
    ServiceEntry(
        service_id="adguard", application="AdGuard Home", category="network",
        authority="the only DNS filter (do not add Pi-hole)", lifecycle="gate-later", profile="network",
        links=Links(app="http://127.0.0.1:${ADGUARD_PORT:-3000}",
                     docs="https://github.com/AdguardTeam/AdGuardHome/wiki", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="setup wizard creates the admin user; evaluate only, "
                                                  "do not become the household resolver yet"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/adguard", complete_backup_unit="appdata/adguard (work+conf)",
                           export_method="built-in config export",
                           restoration_proof="tested bypass/fallback resolver proven before household DNS cutover"),
        automation=Automation(), risk_tier="sensitive",
    ),
    ServiceEntry(
        service_id="home-assistant", application="Home Assistant", category="smart-home",
        authority="smart-home (production target is Home Assistant OS, NOT this container)",
        lifecycle="gate-later", profile="smart-home",
        links=Links(app="http://127.0.0.1:8123",
                     docs="https://www.home-assistant.io/installation/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="onboarding creates the first user; evaluate only — "
                                                  "no essential automations in this container"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/homeassistant/config",
                           complete_backup_unit="appdata/homeassistant/config",
                           export_method="Settings > System > Backups",
                           restoration_proof="restore into HA OS on a VM/dedicated device before real automations"),
        automation=Automation(), risk_tier="sensitive",
    ),
    ServiceEntry(
        service_id="vaultwarden", application="Vaultwarden", category="vault",
        authority="password manager (dummy-data evaluation only; Bitwarden Lite is the deployment target)",
        lifecycle="gate-later", profile="vault",
        links=Links(app="http://127.0.0.1:${VAULTWARDEN_PORT:-8222}",
                     docs="https://bitwarden.com/help/self-host-bitwarden/", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local", credential_ref="VAULTWARDEN_ADMIN_TOKEN"),
        setup=Setup(wizard_required=True, registration_must_close=True,
                     note="dummy credentials ONLY in this trial vault"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/vaultwarden", complete_backup_unit="appdata/vaultwarden",
                           export_method="client-side vault export (encrypted json)",
                           restoration_proof="offline recovery + every client proven before migrating a real vault"),
        automation=Automation(), risk_tier="privileged",
    ),
    ServiceEntry(
        service_id="dockge", application="Dockge", category="admin-gui",
        authority="human-only Compose administration pane — NOT an authority, NOT a harmless viewer",
        lifecycle="privileged-admin-only", profile="admin-gui",
        links=Links(app="http://127.0.0.1:${DOCKGE_PORT:-5001}",
                     docs="https://github.com/louislam/dockge", runbook="runbooks/app-admission.md"),
        auth=Auth(mode="local"),
        setup=Setup(wizard_required=True, note="creates the first admin account; start on demand, stop after use"),
        recovery=Recovery(canonical_data_location="${LC_APPDATA}/dockge(-stacks)",
                           complete_backup_unit="n/a (Compose files on disk are the source of truth)",
                           export_method="n/a", restoration_proof="n/a — start on demand, stop after use"),
        automation=Automation(), risk_tier="privileged",
    ),
    ServiceEntry(
        service_id="open-design", application="Open Design", category="dev-lane",
        authority="AI-assisted design canvas — desktop/laptop dev lane, NOT a household appliance service",
        lifecycle="add", profile="desktop",
        links=Links(docs="https://opendesigner.io/", runbook="dev-lane/open-design/README.md"),
        auth=Auth(mode="local"),
        setup=Setup(),
        recovery=Recovery(canonical_data_location="dev-lane/open-design/open-design/.od/",
                           complete_backup_unit=".od/ projects+skills+templates+design systems",
                           export_method="`.od/` backup hook (see dev-lane script)",
                           restoration_proof="restore .od/ into a fresh clone"),
        automation=Automation(), risk_tier="low",
    ),
    ServiceEntry(
        service_id="command-center-work-graph", application="Command Center Work Graph/Kanban", category="tasks",
        authority="the sole task/project/life-operations authority — do not add Deck or Vikunja",
        lifecycle="keep", profile="n/a (llm_station main stack, not life-center-infra)",
        links=Links(docs="../docs/MASTER.md", runbook="../docs/engineering/REUSABLE_ENGINEERING_STANDARDS.md"),
        auth=Auth(mode="n/a"),
        setup=Setup(),
        recovery=Recovery(canonical_data_location="Ledger (llm_station main stack)",
                           complete_backup_unit="see llm_station Ledger backup policy",
                           export_method="see Ledger", restoration_proof="see Ledger"),
        automation=Automation(), risk_tier="low",
    ),
)


def by_profile(profile: str | None) -> tuple[ServiceEntry, ...]:
    if not profile:
        return SERVICES
    return tuple(s for s in SERVICES if s.profile == profile)


def by_id(service_id: str) -> ServiceEntry | None:
    for s in SERVICES:
        if s.service_id == service_id:
            return s
    return None


def to_dict(entries: tuple[ServiceEntry, ...] | None = None) -> dict:
    """Deterministic, credential-value-free dict for `lc catalog --json`."""
    data = [asdict(s) for s in (entries if entries is not None else SERVICES)]
    return {"schema_version": SCHEMA_VERSION, "services": data}


def digest(entries: tuple[ServiceEntry, ...] | None = None) -> str:
    canonical = json.dumps(to_dict(entries), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

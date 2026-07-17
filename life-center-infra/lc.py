#!/usr/bin/env python3
"""lc - the Life Center one-command bootstrap CLI.

Authoritative, idempotent installer for the open-source Life Center portfolio.
Mirrors the llm_station `cc` CLI idiom: a COMMANDS dict-dispatch that shells out
to `docker compose`. Docker Compose + secrets + backups remain the source of
truth; Dockge (admin-gui tier) is privileged, human-only, on-demand admin —
NOT foundation and NOT a read-only viewer (Docker socket access).

Stdlib only. Cross-platform (Linux/macOS/Windows). See README.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets as _secrets
import shutil
import subprocess
import sys
from pathlib import Path

import catalog

ROOT = Path(__file__).resolve().parent
COMPOSE_DIR = ROOT / "compose"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# Compose file per tier. `foundation` is always included in an `up`.
# Sensitive/conditional/privileged tiers must be named explicitly and are
# excluded from `--profile all`, matching the plan's admission-gate rule:
#   ebooks     conditional — off by default, admit only when justified
#   finance    sensitive (budgeting/financial data)
#   network    household DNS dependency
#   smart-home physical-home dependency
#   vault      critical identity dependency, admitted last
#   admin-gui  privileged host administration (Docker socket access)
TIERS = {
    "foundation": "foundation.yml",
    "files": "files.yml",
    "photos": "photos.yml",
    "docs": "docs.yml",
    "media": "media.yml",
    "ebooks": "ebooks.yml",
    "lifestyle": "lifestyle.yml",
    "finance": "finance.yml",
    "network": "network.yml",
    "smart-home": "smart-home.yml",
    "vault": "vault.yml",
    "admin-gui": "admin-gui.yml",
}
NON_SENSITIVE = ["files", "photos", "docs", "media", "lifestyle"]
# `core` bundles the three primary personal-data authorities — the recommended
# everyday production command; `files`/`photos`/`docs` remain individually
# admissible too (the plan's "admit one at a time" gate).
CORE = ["files", "photos", "docs"]
SECRET_KEYS = [
    "NEXTCLOUD_ADMIN_PASSWORD", "NEXTCLOUD_DB_PASSWORD", "IMMICH_DB_PASSWORD",
    "PAPERLESS_SECRET_KEY", "PAPERLESS_DB_PASSWORD", "LINKWARDEN_NEXTAUTH_SECRET",
    "LINKWARDEN_DB_PASSWORD", "ACTUAL_PASSWORD", "VAULTWARDEN_ADMIN_TOKEN",
    "RESTIC_PASSWORD",
]


def _print(msg: str) -> None:
    print(f"[lc] {msg}")


def run(cmd: list[str], check: bool = True) -> int:
    _print("$ " + " ".join(cmd))
    return subprocess.run(cmd, check=check).returncode


def _have(exe: str) -> bool:
    return shutil.which(exe) is not None


def _compose_base() -> list[str]:
    """Return the `docker compose` invocation prefix (v2 plugin)."""
    return ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(ENV_FILE)]


ALL_APP_TIERS = [t for t in TIERS if t != "foundation"]


def _resolve_tiers(profile: str | None, include_foundation: bool = True) -> list[str]:
    """Resolve a --profile value to the ordered list of tiers to operate on.

    include_foundation controls whether `foundation` is force-included: `up`/
    `bootstrap`/`config`/`backup` want it (foundation's monitoring/pane should
    exist alongside anything else); `down`/`health` must NOT force it in, or
    e.g. `lc down --profile files` would silently also stop Dockge/uptime-kuma.
    """
    base = ["foundation"] if include_foundation else []
    if not profile or profile == "foundation":
        return base if base else ["foundation"]
    if profile == "core":
        return [*base, *CORE] if include_foundation else CORE
    if profile == "all":
        return [*base, *NON_SENSITIVE] if include_foundation else NON_SENSITIVE
    if profile == "everything":
        return [*base, *ALL_APP_TIERS] if include_foundation else ALL_APP_TIERS
    if profile not in TIERS:
        sys.exit(
            f"[lc] unknown profile: {profile!r}. "
            f"Known: {', '.join(TIERS)}, core, all, everything"
        )
    if profile == "foundation":
        return ["foundation"]
    return [*base, profile] if profile not in base else base


def _compose_files(tiers: list[str]) -> list[str]:
    args: list[str] = []
    for t in tiers:
        f = COMPOSE_DIR / TIERS[t]
        if not f.exists():
            sys.exit(f"[lc] missing compose file: {f}")
        args += ["-f", str(f)]
    return args


_SERVICE_KEY_RE = re.compile(r"^  (\S+):\s*$")


def _service_names(tiers: list[str]) -> list[str]:
    """Top-level service names defined by a tier's compose file(s).

    `docker compose ps`/`logs` with no service args list the WHOLE project
    (matched by project name), not just what the `-f` files passed in this
    invocation define — passing service names explicitly is what actually
    scopes the output to one tier.
    """
    names: list[str] = []
    for t in tiers:
        p = COMPOSE_DIR / TIERS[t]
        if not p.exists():
            continue
        in_services = False
        for line in p.read_text(encoding="utf-8").splitlines():
            if line == "services:":
                in_services = True
                continue
            if not in_services:
                continue
            if line and not line.startswith(" "):
                break  # next top-level key: services: block ended
            m = _SERVICE_KEY_RE.match(line)
            if m:
                names.append(m.group(1))
    return names


def _read_env_file() -> dict[str, str]:
    """Parse .env into a dict — `docker compose --env-file` reads it directly,
    but nothing exports those values into THIS process's os.environ."""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return env


_TEMPLATE_VAR_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _resolve_template(template: str, env: dict[str, str]) -> str:
    """Expand `${NAME}` / `${NAME:-default}` using .env, falling back to the
    literal default — os.path.expandvars does NOT understand `:-default`."""
    def sub(m: re.Match) -> str:
        name, default = m.group(1), m.group(2)
        return env.get(name, default if default is not None else "")
    return _TEMPLATE_VAR_RE.sub(sub, template)


# ── commands ─────────────────────────────────────────────────────────────────

def c_doctor(_args) -> int:
    ok = True
    for exe in ("docker",):
        if _have(exe):
            _print(f"OK   {exe} found")
        else:
            _print(f"FAIL {exe} not found on PATH")
            ok = False
    if _have("docker"):
        rc = subprocess.run(["docker", "compose", "version"], capture_output=True).returncode
        _print("OK   docker compose v2 available" if rc == 0 else "FAIL docker compose v2 missing")
        ok = ok and rc == 0
    env_note = "present" if ENV_FILE.exists() else "missing (run: lc setup)"
    _print(f"{'OK  ' if ENV_FILE.exists() else 'WARN'} .env {env_note}")
    for t, f in TIERS.items():
        p = COMPOSE_DIR / f
        _print(f"{'OK  ' if p.exists() else 'FAIL'} compose/{f}")
        ok = ok and p.exists()
    _print("doctor: PASS" if ok else "doctor: issues found (see above)")
    return 0 if ok else 1


def _gen_secret(n: int = 32) -> str:
    return _secrets.token_urlsafe(n)


def c_setup(_args) -> int:
    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        _print(f"created {ENV_FILE.name} from .env.example")
        # Append generated secrets (idempotent: only if not already ASSIGNED).
        # Commented placeholders in .env.example must not count as assignments.
        existing = ENV_FILE.read_text(encoding="utf-8")
        assigned = {
            ln.split("=", 1)[0].strip()
            for ln in existing.splitlines()
            if "=" in ln and not ln.lstrip().startswith("#")
        }
        lines = ["", "# ── generated secrets (do not commit) ──"]
        for key in SECRET_KEYS:
            if key not in assigned:
                lines.append(f"{key}={_gen_secret()}")
        ENV_FILE.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
        _print(f"generated {len(SECRET_KEYS)} local secrets into {ENV_FILE.name}")
    else:
        _print(f"{ENV_FILE.name} already exists — leaving it untouched")
    for d in ("appdata", "backups", "secrets", "restore-tmp"):
        (ROOT / d).mkdir(exist_ok=True)
    _print("setup: PASS")
    return 0


def c_up(args) -> int:
    if not ENV_FILE.exists():
        c_setup(args)
    tiers = _resolve_tiers(getattr(args, "profile", None))
    _print("bringing up tiers: " + ", ".join(tiers))
    return run(_compose_base() + _compose_files(tiers) + ["up", "-d"])


def c_down(args) -> int:
    profile = getattr(args, "profile", None)
    if not profile:
        sys.exit("[lc] down requires --profile (omit to avoid accidentally "
                  "stopping foundation); use --profile foundation explicitly "
                  "to stop monitoring/backups too")
    tiers = _resolve_tiers(profile, include_foundation=False)
    _print("stopping tiers: " + ", ".join(tiers))
    return run(_compose_base() + _compose_files(tiers) + ["down"])


def c_bootstrap(args) -> int:
    """Foundation only: monitoring + backups. Dockge is a separate tier."""
    args.profile = "foundation"
    return c_up(args)


def c_health(args) -> int:
    profile = getattr(args, "profile", None)
    tiers = _resolve_tiers(profile, include_foundation=not profile)
    # `ps` with no service args lists the WHOLE project, not just this tier —
    # pass explicit service names so `lc health --profile files` doesn't show
    # every other admitted tier's containers too.
    return run(_compose_base() + _compose_files(tiers) + ["ps"] + _service_names(tiers))


def c_first_boot(args) -> int:
    for step in (c_doctor, c_setup, c_bootstrap, c_health):
        rc = step(args)
        if rc != 0:
            _print(f"first-boot halted at {step.__name__} (rc={rc})")
            return rc
    _print("first-boot: PASS — foundation is up. Admit app tiers with `lc up --profile <tier>`.")
    return 0


def c_config(args) -> int:
    """Lint the merged Compose for a profile (docker compose config)."""
    tiers = _resolve_tiers(getattr(args, "profile", None))
    return run(_compose_base() + _compose_files(tiers) + ["config"], check=False)


def c_backup(_args) -> int:
    """Trigger the restic backup one-shot (foundation tier defines it).

    Runs `restic backup /appdata /data` inside the backup container. The repo must
    be initialised once first (`docker compose ... run --rm backup init`) and
    RESTIC_PASSWORD must be set in .env. See runbooks/backup-restore.md.
    """
    return run(_compose_base() + ["-f", str(COMPOSE_DIR / "foundation.yml"),
                                  "run", "--rm", "backup",
                                  "backup", "/appdata", "/data",
                                  "--tag", "life-center"], check=False)


def c_restore_test(_args) -> int:
    _print("Restore-test is a guided drill — see runbooks/backup-restore.md")
    return 0


def c_gui(args) -> int:
    """Open Dockge (admin-gui: privileged, human-only, on demand — not foundation)."""
    args.profile = "admin-gui"
    rc = c_up(args)
    port = os.environ.get("DOCKGE_PORT", "5001")
    _print(f"Dockge (privileged admin pane): http://127.0.0.1:{port}")
    _print("This has Docker socket access — root-equivalent host control. "
           "Stop it when done: `lc down --profile admin-gui`")
    return rc


def _resolved_links(s: "catalog.ServiceEntry", env: dict[str, str]) -> dict[str, str | None]:
    return {
        "app": _resolve_template(s.links.app, env) if s.links.app else None,
        "setup": _resolve_template(s.links.setup, env) if s.links.setup else None,
        "docs": s.links.docs,
        "runbook": s.links.runbook,
        "status": _resolve_template(s.links.status, env) if s.links.status else None,
        "native": s.links.native,
    }


def c_links(args) -> int:
    """Print each admitted service's URL/docs/runbook/credential *name* only.

    Never prints a credential value — only the .env variable name to look up.
    """
    profile = getattr(args, "profile", None)
    entries = catalog.by_profile(profile)
    if not entries:
        _print(f"no catalog entries for profile {profile!r}")
        return 1
    env = _read_env_file()
    if getattr(args, "json", False):
        out = []
        for s in entries:
            d = {
                "service_id": s.service_id, "application": s.application,
                "profile": s.profile, "risk_tier": s.risk_tier,
                "authority": s.authority, "links": _resolved_links(s, env),
                "credential_ref": s.auth.credential_ref,
                "recovery": {
                    "canonical_data_location": s.recovery.canonical_data_location,
                    "complete_backup_unit": s.recovery.complete_backup_unit,
                    "restoration_proof": s.recovery.restoration_proof,
                },
            }
            out.append(d)
        print(json.dumps({"schema_version": catalog.SCHEMA_VERSION, "services": out}, indent=2))
        return 0
    for s in entries:
        links = _resolved_links(s, env)
        _print(f"{s.service_id} ({s.application}) — profile={s.profile} risk={s.risk_tier}")
        if links["app"]:
            print(f"    url:       {links['app']}")
        print(f"    authority: {s.authority}")
        print(f"    docs:      {links['docs']}")
        print(f"    runbook:   {links['runbook']}")
        if s.auth.credential_ref:
            print(f"    credential: see {s.auth.credential_ref} in .env (never printed here)")
        print(f"    data:      {s.recovery.canonical_data_location}")
        print(f"    backup:    {s.recovery.complete_backup_unit}")
        print(f"    restore proof required: {s.recovery.restoration_proof}")
    return 0


def c_catalog(args) -> int:
    """Dump the full typed catalog (or one --service) as JSON — no secret values."""
    service_id = getattr(args, "service", None)
    if service_id:
        s = catalog.by_id(service_id)
        if not s:
            _print(f"unknown service_id: {service_id!r}")
            return 1
        payload = catalog.to_dict((s,))
    else:
        payload = catalog.to_dict()
    payload["catalog_digest"] = catalog.digest()
    print(json.dumps(payload, indent=2, default=str))
    return 0


def c_link_check(args) -> int:
    """HTTP-reachability check only (a focused subset of `lc verify`)."""
    profile = getattr(args, "profile", None)
    tiers = _resolve_tiers(profile, include_foundation=not profile)
    env = _read_env_file()
    results = []
    for s in (catalog.by_profile(profile) if profile else catalog.SERVICES):
        if s.profile not in tiers or not s.links.app:
            continue
        url = _resolve_template(s.links.app, env)
        status = _http_probe(url)
        results.append({"service_id": s.service_id, "url": url, "status": status})
        if not getattr(args, "json", False):
            _print(f"  {s.service_id}: {url} -> {status}")
    if getattr(args, "json", False):
        print(json.dumps({"schema_version": catalog.SCHEMA_VERSION, "results": results}, indent=2))
    return 0


_OPEN_TARGETS = ("app", "setup", "docs", "runbook", "status")


def c_open(args) -> int:
    """Open one service's link in the default browser (local action only)."""
    import webbrowser

    service_id = getattr(args, "service", None)
    target = getattr(args, "target", "app") or "app"
    if target not in _OPEN_TARGETS:
        sys.exit(f"[lc] unknown --target {target!r}. Known: {', '.join(_OPEN_TARGETS)}")
    s = catalog.by_id(service_id) if service_id else None
    if not s:
        sys.exit(f"[lc] unknown service_id: {service_id!r}. See `lc catalog --json` for valid ids.")
    env = _read_env_file()
    links = _resolved_links(s, env)
    url = links.get(target)
    if target == "runbook" and url:
        url = (ROOT / url).resolve().as_uri()
    if not url:
        _print(f"{service_id} has no '{target}' link in the catalog")
        return 1
    if getattr(args, "dry_run", False):
        _print(f"would open: {url}")
        return 0
    _print(f"opening: {url}")
    webbrowser.open(url)
    return 0


def c_setup_session(_args) -> int:
    """Write ONE local setup-checklist page and open it — not 15 browser tabs."""
    import tempfile
    import webbrowser

    env = _read_env_file()
    rows = []
    for s in catalog.SERVICES:
        if not s.setup.wizard_required and not s.setup.default_credentials_must_rotate:
            continue
        links = _resolved_links(s, env)
        url = links.get("setup") or links.get("app") or ""
        checks = []
        if s.setup.wizard_required:
            checks.append("finish first-run wizard / create owner account")
        if s.setup.registration_must_close:
            checks.append("close open registration afterward")
        if s.setup.default_credentials_must_rotate:
            checks.append("rotate default credentials")
        note = f" — {s.setup.note}" if s.setup.note else ""
        link_html = f'<a href="{url}" target="_blank">{s.application}</a>' if url else s.application
        rows.append(
            f"<li>{link_html} (risk: {s.risk_tier})<ul><li>" +
            "</li><li>".join(checks) + f"</li></ul><p>{note}</p></li>"
        )
    html = (
        "<html><head><title>Life Center setup session</title></head><body>"
        "<h1>Life Center — pending setup steps</h1>"
        "<p>Click each link, complete it in the tab it opens, then check it off yourself. "
        "Nothing here auto-submits credentials.</p><ol>" + "".join(rows) + "</ol></body></html>"
    )
    path = Path(tempfile.gettempdir()) / "lc-setup-session.html"
    path.write_text(html, encoding="utf-8")
    _print(f"wrote {path}")
    webbrowser.open(path.resolve().as_uri())
    return 0


def _exposure_checks(tiers: list[str]) -> list[dict]:
    """Every host port-binding line found, each judged loopback-only or not."""
    checks = []
    for t in tiers:
        p = COMPOSE_DIR / TIERS[t]
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if not (s.startswith("- \"") and ":" in s and s.rstrip('"').split(":")[-1].isdigit()):
                continue
            loopback = "127.0.0.1:" in s
            checks.append({
                "check_id": f"exposure:{TIERS[t]}:{i}", "service_id": t,
                "status": "pass" if loopback else "fail",
                "evidence": s,
                "remediation": "" if loopback else "bind to 127.0.0.1, not a wildcard/public address",
            })
    return checks


def _http_probe(url: str, timeout: float = 4.0) -> str:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 - loopback only
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - report, don't crash the verify pass
        return f"unreachable ({e.__class__.__name__})"


def _compose_ps_json(tiers: list[str]) -> list[dict]:
    """`docker compose ps --format json`, tolerant of NDJSON vs. a JSON array
    (compose v2 has shipped both across releases)."""
    cmd = _compose_base() + _compose_files(tiers) + ["ps", "--format", "json"] + _service_names(tiers)
    # Explicit encoding, NOT text=True's locale default: on Windows that's the
    # legacy console codepage (cp1252), which can't decode UTF-8 bytes compose
    # emits (e.g. the "…" ellipsis in truncated Command fields) — the decode
    # crashes the subprocess reader thread and silently leaves stdout as None.
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False)
    out = (proc.stdout or "").strip()
    if not out:
        return []
    try:
        parsed = json.loads(out)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows


_VERIFY_SCHEMA_VERSION = "life-center.verify.v1"
_NOT_AUTOMATED = (
    "default credentials still present",
    "registration closed where the app supports it",
    "application export freshness",
    "last successful backup age",
    "last clean-restore-test age",
)


def _build_verification_report(profile: str | None) -> dict:
    """One canonical report; both the human and JSON renderers read from it —
    they must never drift into computing their own answers independently."""
    import datetime

    tiers = _resolve_tiers(profile, include_foundation=not profile)
    checks: list[dict] = []

    for row in _compose_ps_json(tiers):
        name = row.get("Service") or row.get("Name", "?")
        health = (row.get("Health") or "").lower()
        state = (row.get("State") or "").lower()
        if health == "healthy" or (not health and state == "running"):
            status = "pass"
        elif health == "starting":
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "check_id": f"container_health:{name}", "service_id": name, "status": status,
            "evidence": f"state={state} health={health or 'n/a'}", "remediation": "",
        })

    env = _read_env_file()
    for s in catalog.by_profile(profile) if profile else catalog.SERVICES:
        if s.profile not in tiers or not s.links.app:
            continue
        url = _resolve_template(s.links.app, env)
        probe = _http_probe(url)
        status = "pass" if probe.startswith("HTTP 2") or probe.startswith("HTTP 3") else \
                 "warn" if probe.startswith("HTTP") else "fail"
        checks.append({
            "check_id": f"http_reachability:{s.service_id}", "service_id": s.service_id,
            "status": status, "evidence": f"{url} -> {probe}", "remediation": "",
        })

    for t in tiers:
        p = COMPOSE_DIR / TIERS[t]
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s2 = line.strip()
            if not s2.startswith("image:"):
                continue
            ref = s2.split("#", 1)[0].strip()
            pinned = "@sha256" in ref
            checks.append({
                "check_id": f"image_pin:{TIERS[t]}:{i}", "service_id": t,
                "status": "pass" if pinned else "warn", "evidence": s2,
                "remediation": "" if pinned else "pin by @sha256 digest before real-data admission",
            })

    checks.extend(_exposure_checks(tiers))

    for item in _NOT_AUTOMATED:
        checks.append({
            "check_id": f"not_automated:{item.replace(' ', '_')}", "service_id": None,
            "status": "unknown", "evidence": "not automated — see runbooks/app-admission.md",
            "remediation": "", "human_evidence_required": True,
        })

    overall = "fail" if any(c["status"] == "fail" for c in checks) else \
              "warn" if any(c["status"] in ("warn", "unknown") for c in checks) else "pass"

    return {
        "schema_version": _VERIFY_SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "catalog_schema_version": catalog.SCHEMA_VERSION,
        "catalog_digest": catalog.digest(),
        "profile": profile,
        "tiers": tiers,
        "overall": overall,
        "checks": checks,
    }


def _render_verification_human(report: dict) -> None:
    _print(f"verify: profile={report['profile'] or '(foundation)'} tiers={', '.join(report['tiers'])}")
    by_kind: dict[str, list[dict]] = {}
    for c in report["checks"]:
        kind = c["check_id"].split(":", 1)[0]
        by_kind.setdefault(kind, []).append(c)
    titles = {
        "container_health": "container health", "http_reachability": "HTTP reachability (loopback only)",
        "image_pin": "image digest pinning (@sha256)", "exposure": "exposure policy (loopback-only bind)",
        "not_automated": "NOT automated (see runbooks/app-admission.md for the drill)",
    }
    for kind, items in by_kind.items():
        _print(f"-- {titles.get(kind, kind)} --")
        for c in items:
            marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL", "unknown": "[ ]"}.get(c["status"], "?")
            _print(f"  {marker} {c['service_id'] or c['check_id']}: {c['evidence']}")
    _print(f"overall: {report['overall']}")


def c_verify(args) -> int:
    """Genuinely-checkable posture for a profile: health, HTTP, pinning, exposure.

    Anything NOT actually automated (default-credential detection, whether a
    first-run wizard/registration was closed, export freshness, backup age,
    last clean-restore-test age) is reported as `unknown` with
    human_evidence_required=true, never faked as a pass. Human and JSON output
    render from the SAME in-memory report — they cannot drift from each other.
    See runbooks/app-admission.md for the human drill covering the unknowns.
    """
    report = _build_verification_report(getattr(args, "profile", None))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _render_verification_human(report)
    return 0 if report["overall"] != "fail" else 1


COMMANDS = {
    "doctor": (c_doctor, "preflight: docker, compose, .env, compose files"),
    "setup": (c_setup, "create .env + generated secrets + data dirs (idempotent)"),
    "bootstrap": (c_bootstrap, "bring up the foundation tier only"),
    "up": (c_up, "bring up foundation + --profile <tier> (default: foundation)"),
    "down": (c_down, "stop foundation + --profile <tier>"),
    "health": (c_health, "show container status for a profile"),
    "first-boot": (c_first_boot, "doctor -> setup -> bootstrap -> health"),
    "config": (c_config, "lint merged compose for a profile"),
    "backup": (c_backup, "run the restic backup one-shot"),
    "restore-test": (c_restore_test, "print the restore-test drill pointer"),
    "gui": (c_gui, "bring up + print the privileged Dockge admin-gui URL"),
    "links": (c_links, "print URL/docs/runbook/credential-name per service (never a value)"),
    "verify": (c_verify, "health + HTTP + image-pinning + exposure posture for a profile"),
    "catalog": (c_catalog, "dump the typed service catalog as JSON (no secret values)"),
    "link-check": (c_link_check, "HTTP-reachability check only, for a profile"),
    "open": (c_open, "open one service's link in the default browser (local action only)"),
    "setup-session": (c_setup_session, "write + open ONE local setup-checklist page for pending first-run steps"),
}

# Commands that take --profile (most do; `catalog`/`open`/`setup-session` operate
# on a single service or the whole catalog, not a compose tier).
_NO_PROFILE_COMMANDS = {"catalog", "open", "setup-session"}
_JSON_COMMANDS = {"links", "link-check", "verify"}


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage; catalog.py uses em-dashes
    # and other non-ASCII punctuation in prose that gets printed (`lc links`,
    # `lc verify`). Without this, those print as mangled replacement chars.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="lc", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd")
    for name, (_fn, help_) in COMMANDS.items():
        p = sub.add_parser(name, help=help_)
        if name not in _NO_PROFILE_COMMANDS:
            p.add_argument("--profile", default=None,
                           help="tier: " + ", ".join(TIERS) + ", core, all, everything")
        if name in _JSON_COMMANDS:
            p.add_argument("--json", action="store_true", help="machine-readable JSON output")
        if name == "catalog":
            p.add_argument("--service", default=None, help="service_id to dump (default: all)")
        if name == "open":
            p.add_argument("service", help="service_id (see `lc catalog --json`)")
            p.add_argument("--target", default="app",
                           help="app | setup | docs | runbook | status (default: app)")
            p.add_argument("--dry-run", action="store_true", help="print the URL, don't open a browser")
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    fn = COMMANDS[args.cmd][0]
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

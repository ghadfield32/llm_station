"""
Life Center catalog/verification → Command Center Kanban cards.

Turns life-center-infra's version-controlled service catalog and its `lc verify`
health output into cards on three governed first-party boards, so the desktop
Life Center trial is tracked inside the one task authority (Command Center
Kanban) without life-center-infra depending on this repo.

life-center-infra is a self-contained "design seed" (see its README) meant to be
extracted into its own private repo later, so its facts are read ONLY by shelling
out to its `lc.py` CLI (``run_lc``) — never by importing anything under it. That
subprocess boundary is the seam that survives the extraction.

The three sync functions are pure and take an injected ``upsert_card`` callable
(plus, where a lane decision depends on prior existence, an ``existing_ids`` set),
so they are fully testable offline with a fake recorder. The
``command_center_*_binder()`` factories bind the live CommandCenterBoardProvider,
mirroring ``command_center_card_drafter``.

Board ownership (configs/domain_surfaces.yaml + configs/kanban_boards.yaml):

  - ``life_center_services``   admission lifecycle; the lane + owner/notes are
                               HUMAN-owned. Sync only refreshes the join keys
                               {service_id, catalog_digest}; it never creates a
                               second card and never moves an existing lane.
  - ``life_center_operations`` actionable setup/incident work; ``card_id`` is the
                               idempotency key, so reruns refresh evidence, never
                               duplicate, and never move a human-moved lane.
  - ``life_center_overview``   machine-owned health projection (allowed_actions:
                               [], editable: false). Every field and the lane are
                               always safe to overwrite; this is the ONLY board
                               whose cards move between lanes every run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# life-center-infra/lc.py, a sibling of the repo root (parents: discovery →
# improvement → command_center → src → repo root), invoked as a subprocess.
LC_CLI = Path(__file__).resolve().parents[4] / "life-center-infra" / "lc.py"

BOARD_SERVICES = "life_center_services"
BOARD_OPERATIONS = "life_center_operations"
BOARD_OVERVIEW = "life_center_overview"

# Verification verdict → the internal status key the board's status_mapping
# resolves to a lane: ready→Healthy, blocked→Attention, rejected→Retired
# (configs/kanban_boards.yaml life_center_overview.status_mapping). pass/warn/fail
# and ready/blocked/rejected are 1:1, so the folded status IS the health verdict.
_OVERALL_TO_LANE = {"pass": "ready", "warn": "blocked", "fail": "rejected"}


def run_lc(*args: str, allowed_returncodes: tuple[int, ...] = (0,)) -> dict:
    """Run life-center-infra's ``lc.py`` CLI as a subprocess and parse its JSON.

    A subprocess, never an import: life-center-infra is a self-contained seed
    (its README) destined for its own repo; importing its modules from
    ``src/command_center`` would couple the two and break on extraction. Python
    puts the script's own directory on ``sys.path[0]``, so ``lc.py``'s
    ``import catalog`` resolves with no cwd dependency.

    ``check=True`` semantics by default (any non-zero exit raises
    ``CalledProcessError``). ``allowed_returncodes`` widens that ONLY for
    callers with a documented non-error non-zero exit: ``lc verify`` returns 1
    when ``overall == "fail"`` yet still prints a valid report — exactly the
    "a service is unhealthy" case the Overview sync must act on — so the verify
    caller passes ``allowed_returncodes=(0, 1)``. A real error (argparse exit 2,
    a crash, non-JSON stdout) still raises.
    """
    proc = subprocess.run(
        [sys.executable, str(LC_CLI), *args],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode not in allowed_returncodes:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
    return json.loads(proc.stdout)


# ── pure sync functions (injected upsert_card; fully testable offline) ─────────

def sync_services_from_catalog(
    services: list[dict], *, upsert_card: Callable[..., object],
    existing_ids: set[str], catalog_digest: str,
) -> list[dict]:
    """One permanent card per catalog service on ``life_center_services``.

    The lane is a HUMAN admission decision and owner/notes/decision are
    human-owned (domain_surfaces.yaml life_center_services.intake.editable=true),
    so the sync is deliberately minimal:

      - NEW card: seed {service_id, catalog_digest, admission_status="Backlog",
        owner, human_notes, decision_explanation} and create it in "Backlog".
      - EXISTING card: refresh ONLY the join keys {service_id, catalog_digest}
        (status=None → fields-only, no event). Admission status, owner, notes and
        the lane are never touched.

    ``card_id == service_id``, making reruns idempotent.
    """
    out: list[dict] = []
    for svc in services:
        service_id = str(svc["service_id"])
        card_id = service_id
        if card_id in existing_ids:
            upsert_card(card_id,
                        {"service_id": service_id, "catalog_digest": catalog_digest},
                        status=None)
            out.append({"card_id": card_id, "service_id": service_id, "action": "updated"})
        else:
            upsert_card(card_id, {
                "service_id": service_id,
                "catalog_digest": catalog_digest,
                "admission_status": "Backlog",
                "owner": "",
                "human_notes": "",
                "decision_explanation": "",
            }, status="Backlog")
            out.append({"card_id": card_id, "service_id": service_id, "action": "created"})
    return out


def _setup_evidence(setup: dict) -> str:
    """Human-readable evidence string derived from a catalog service's `setup`."""
    parts: list[str] = []
    if setup.get("wizard_required"):
        parts.append("first-run wizard / owner account required")
    if setup.get("registration_must_close"):
        parts.append("close open registration afterward")
    if setup.get("default_credentials_must_rotate"):
        parts.append("rotate default credentials")
    note = str(setup.get("note") or "").strip()
    if note:
        parts.append(f"note: {note}")
    return "; ".join(parts) if parts else "initial setup required"


def seed_operations_from_setup(
    services: list[dict], *, upsert_card: Callable[..., object],
    existing_ids: set[str],
) -> list[dict]:
    """Seed one setup task per service that needs first-run setup on
    ``life_center_operations``.

    A card is seeded only when the catalog says ``setup.wizard_required`` or
    ``setup.default_credentials_must_rotate``. ``card_id`` is
    ``f"{service_id}:setup:initial"`` and doubles as the idempotency key, so a
    rerun refreshes an existing card rather than duplicating it. No action broker
    exists, so these are proposals/evidence, never executed mutations.

      - NEW card: full field set in "Backlog" (finding_key/requested_action_id/
        approval_id left None — no broker yet).
      - EXISTING card: refresh ONLY {evidence_refs, risk_tier}; the lane is left
        alone (a human may already have moved it to In Progress/Done).
    """
    out: list[dict] = []
    for svc in services:
        setup = svc.get("setup") or {}
        if not (setup.get("wizard_required") or setup.get("default_credentials_must_rotate")):
            continue
        service_id = str(svc["service_id"])
        card_id = f"{service_id}:setup:initial"
        evidence = _setup_evidence(setup)
        risk_tier = str(svc.get("risk_tier", ""))
        if card_id in existing_ids:
            upsert_card(card_id, {"evidence_refs": evidence, "risk_tier": risk_tier},
                        status=None)
            out.append({"card_id": card_id, "service_id": service_id, "action": "updated"})
        else:
            upsert_card(card_id, {
                "service_id": service_id,
                "operation_type": "setup",
                "risk_tier": risk_tier,
                "idempotency_key": card_id,
                "finding_key": None,
                "requested_action_id": None,
                "approval_id": None,
                "evidence_refs": evidence,
            }, status="Backlog")
            out.append({"card_id": card_id, "service_id": service_id, "action": "created"})
    return out


def sync_overview_from_verification(
    checks: list[dict], generated_at: str, *, upsert_card: Callable[..., object],
) -> list[dict]:
    """Project ``lc verify`` health onto ``life_center_overview``, moving each
    card into its current-health lane every run.

    Per-service checks are grouped by ``service_id``; entries with
    ``service_id is None`` are profile-wide "not_automated" disclaimers, not
    per-service evidence, and are skipped. Per service the verdict is:
    ``fail`` if any check failed, else ``warn`` if any check is not ``pass``,
    else ``pass``; mapped to lane ready/blocked/rejected → Healthy/Attention/
    Retired.

    Lane MOVEMENT mechanism: ``upsert_card`` is called with ``status=lane`` every
    run. ``CommandCenterBoardProvider.upsert_card`` always emits an
    ``add_mission_card`` → ``kanban.card.created`` event when ``status`` is set,
    REGARDLESS of whether the card already exists, and ``project_cards`` folds the
    event log last-writer-wins per card_id — so a fresh created event with the new
    ``status_after`` moves the existing card into the new lane. This board is
    machine-owned (allowed_actions: [], editable: false), so overwriting every
    field and the lane on every run is always safe. ready/blocked/rejected are
    granted (non-human-owned) statuses, so the governance wall passes.
    """
    by_service: dict[str, list[dict]] = {}
    for check in checks:
        service_id = check.get("service_id")
        if service_id is None:
            continue
        by_service.setdefault(str(service_id), []).append(check)

    out: list[dict] = []
    for service_id in sorted(by_service):  # deterministic order
        statuses = [c.get("status") for c in by_service[service_id]]
        if any(s == "fail" for s in statuses):
            overall = "fail"
        elif any(s != "pass" for s in statuses):
            overall = "warn"
        else:
            overall = "pass"
        lane = _OVERALL_TO_LANE[overall]
        card_id = f"overview:{service_id}"
        # `status` here is popped by upsert_card (the fold owns status); the
        # status=lane kwarg is what drives the fold + status_mapping placement,
        # and overall↔lane are 1:1 so the surfaced badge equals the verdict.
        upsert_card(card_id, {
            "service": service_id,
            "status": overall,
            "last_check": generated_at,
        }, status=lane)
        out.append({"card_id": card_id, "service": service_id,
                    "status": overall, "lane": lane})
    return out


# ── live-board binders (mirror command_center_card_drafter) ────────────────────

def _provider(default_board_id: str, board_id: str | None = None):
    """Build the live CommandCenterBoardProvider for a Life Center board, using
    the same KANBAN_EVENT_LOG / KANBAN_BOARD_STORE env-var conventions as
    ``command_center_card_drafter``."""
    import os

    from command_center.boards.command_center_provider import CommandCenterBoardProvider
    from command_center.kanban_sync.events import EventLog

    target = board_id or default_board_id
    event_path = os.environ.get("KANBAN_EVENT_LOG", "generated/kanban-events.jsonl")
    store_path = os.environ.get("KANBAN_BOARD_STORE", "generated/boards")
    return CommandCenterBoardProvider(
        board_id=target, event_log=EventLog(event_path), store_dir=Path(store_path))


def _existing_ids(provider) -> set[str]:
    return {str(card["card_id"]) for card in provider.list_cards()
            if card.get("card_id") is not None}


def command_center_services_binder(
    *, board_id: str | None = None,
) -> Callable[[list[dict], str], list[dict]]:
    """Bind ``sync_services_from_catalog`` to the live services board. The
    returned callable takes ``(services, catalog_digest)`` and computes
    ``existing_ids`` against the live board so existing admission cards keep their
    human-owned lane/owner/notes."""
    provider = _provider(BOARD_SERVICES, board_id)

    def run(services: list[dict], catalog_digest: str) -> list[dict]:
        return sync_services_from_catalog(
            services, upsert_card=provider.upsert_card,
            existing_ids=_existing_ids(provider), catalog_digest=catalog_digest)

    return run


def command_center_operations_binder(
    *, board_id: str | None = None,
) -> Callable[[list[dict]], list[dict]]:
    """Bind ``seed_operations_from_setup`` to the live operations board. The
    returned callable takes ``(services)`` and computes ``existing_ids`` so reruns
    refresh, never duplicate, and never move a human-moved lane."""
    provider = _provider(BOARD_OPERATIONS, board_id)

    def run(services: list[dict]) -> list[dict]:
        return seed_operations_from_setup(
            services, upsert_card=provider.upsert_card,
            existing_ids=_existing_ids(provider))

    return run


def command_center_overview_binder(
    *, board_id: str | None = None,
) -> Callable[[list[dict], str], list[dict]]:
    """Bind ``sync_overview_from_verification`` to the live overview board. The
    returned callable takes ``(checks, generated_at)`` and tags each result with
    created/updated by diffing pre-existing card ids (the pure function itself is
    existence-agnostic — it always moves the card to its current-health lane)."""
    provider = _provider(BOARD_OVERVIEW, board_id)

    def run(checks: list[dict], generated_at: str) -> list[dict]:
        before = _existing_ids(provider)
        results = sync_overview_from_verification(
            checks, generated_at, upsert_card=provider.upsert_card)
        for result in results:
            result["action"] = "updated" if result["card_id"] in before else "created"
        return results

    return run

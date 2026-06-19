#!/usr/bin/env python3
"""Publish approved, due LinkedIn content rows from the AppFlowy content boards.

The mechanical end of the content pipeline (no LLM here):

    In Queue  --(you drag it)-->  In Progress  --(this, at ScheduledFor)-->  Completed

Default mode is read-only dry-run: it prints exactly the rows that WOULD post.
`--apply` publishes each approved, due row to LinkedIn's official Posts API and
stamps PostURN + PublishedAt + Status=Completed back onto the same row. `--login`
runs the one-time OAuth.

Honesty/safety contract:
  - Only rows in the configured `approved` status (a human dragged them there)
    are eligible - the agent never self-approves.
  - Temporal safety: a row publishes only when ScheduledFor <= now.
  - No double-post: a durable PublishLedger records each Key BEFORE/AFTER the
    POST (generated/linkedin-published.json), so a successful post whose AppFlowy
    writeback failed is RECONCILED, never re-sent; an ambiguous send (timeout) is
    surfaced as RECONCILE_REQUIRED and never auto-retried. A single-process lock
    stops two scheduler runs touching the same row.
  - No silent fallback: a definitive publish failure leaves the row In Progress
    (retries); a media/non-text row is refused loudly; no row is marked Completed
    without a real PostURN.
"""
from __future__ import annotations

import argparse
import contextlib
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from command_center.schemas import ContentConfig
from command_center.linkedin import LinkedInClient, LinkedInError, TokenStore
from command_center.linkedin.ledger import (
    PublishLedger, ProcessLock, AlreadyRunning, PUBLISHED, PUBLISHING,
    RECONCILE_REQUIRED,
)
from command_center.cli.kanban_bridge import (
    read_yaml, merged_env, cell, rows_from_appflowy, appflowy_ctx,
)


def date_start(value) -> str:
    """AppFlowy date cells read back as a dict with an ISO `start`; text/select
    cells read back as plain scalars. Normalise both to an ISO string."""
    if isinstance(value, dict):
        return value.get("start") or ""
    return str(value) if value else ""


def post_text(cells) -> str:
    """The text actually published: the Hook (the all-important first line on
    LinkedIn) followed by the Body. Either alone if the other is empty."""
    hook = cell(cells, "Hook")
    body = cell(cells, "Body")
    if hook and body:
        return f"{hook}\n\n{body}"
    return hook or body


def token_warning(tok, warn_days: int) -> str | None:
    """A dated re-login reminder when the access token is expired or within
    `warn_days` of expiry. None when comfortably valid. LinkedIn issues no
    refresh token to standard apps, so the only renewal is a human --login."""
    if not tok.expires_at:
        return None
    days = (tok.expires_at - time.time()) / 86400
    when = time.strftime("%Y-%m-%d", time.localtime(tok.expires_at))
    if days <= 0:
        return f"LinkedIn token EXPIRED ({when}) - run `cc linkedin-publish --login`"
    if days <= warn_days:
        return (f"LinkedIn token expires in {int(days)}d ({when}) - re-run "
                "`cc linkedin-publish --login` to renew (no auto-refresh available)")
    return None


def account_source(src, board: str) -> SimpleNamespace:
    """A per-account view of the AppFlowy source for the bridge's row helpers
    (which key off `.database`). Same env-key names as the kanban source."""
    return SimpleNamespace(
        kind="appflowy", growthos_root=src.growthos_root, database=board,
        database_map_path=src.database_map_path, base_url_env=src.base_url_env,
        workspace_id_env=src.workspace_id_env, email_env=src.email_env,
        password_env=src.password_env,
    )


def due_rows(rows: list[dict], statuses, now: datetime) -> list[tuple[str, dict]]:
    """(Key, cells) for rows that are approved, scheduled, due, and unpublished."""
    out: list[tuple[str, dict]] = []
    for row in rows:
        cells = row.get("cells", row)
        if cell(cells, "Status") != statuses.approved:
            continue
        if cell(cells, "PostURN"):                      # already published
            continue
        sched = date_start(cells.get("ScheduledFor"))
        if not sched:
            print(f"  ! skip (no ScheduledFor): {cell(cells, 'Hook')[:60]}")
            continue
        if datetime.fromisoformat(sched) > now:         # not due yet
            continue
        key = cell(cells, "Key")
        if not key:
            print(f"  ! skip (no Key, cannot stamp back): {cell(cells, 'Hook')[:60]}")
            continue
        out.append((key, cells))
    return out


def stamp_completed(ctx: dict, key: str, post_urn: str, done_status: str) -> None:
    fields = ctx["fields"]
    cells = {fields["PostURN"]: post_urn,
             fields["Status"]: done_status,
             fields["PublishedAt"]: datetime.now(timezone.utc).date().isoformat()}
    r = httpx.put(
        f"{ctx['base']}/api/workspace/{ctx['workspace']}/database/{ctx['db_id']}/row",
        headers={"Authorization": f"Bearer {ctx['token']}"},
        json={"pre_hash": key, "cells": cells, "document": None}, timeout=30)
    r.raise_for_status()
    if r.json().get("code") != 0:
        raise RuntimeError(f"writeback failed: {r.text[:200]}")


def author_urn(client: LinkedInClient, acct, env: dict[str, str]) -> str:
    if acct.author == "member":
        return client.resolve_member_urn()
    urn = env.get(acct.org_urn_env, "")
    if not urn:
        raise LinkedInError(
            f"account '{acct.board}': {acct.org_urn_env} is unset; cannot post to "
            "the organization. Set the Page URN in .env after the Page is admin-linked.")
    return urn


def publish_row(client, acct, env, ctx, key, cells, statuses, ledger) -> str:
    """Publish one due row through the ledger state machine. Returns a short
    outcome string for the run summary."""
    st = ledger.state(key)
    if st == PUBLISHED:
        # Posted on a prior run; only the AppFlowy stamp didn't land. Reconcile,
        # never re-post.
        try:
            stamp_completed(ctx, key, ledger.urn(key), statuses.done)
            print(f"  reconciled (already posted {ledger.urn(key)}) -> {statuses.done}")
            return "reconciled"
        except Exception as exc:
            print(f"  RECONCILE still failing for {key}: {exc}")
            return "reconcile_failed"
    if st in (PUBLISHING, RECONCILE_REQUIRED):
        prior = ledger.records.get(key, {}).get("error", "")
        print(f"  ! RECONCILE_REQUIRED ({st}) {key}: prior send outcome unknown; "
              f"resolve by hand, NOT auto-retried. {prior}")
        return "needs_reconcile"

    fmt = cell(cells, "Format") or "Text"
    if fmt != "Text" or cell(cells, "Media"):
        print(f"  ! skip (media/non-text not wired yet): {cell(cells, 'Hook')[:60]}")
        return "skipped_media"
    try:
        author = author_urn(client, acct, env)       # resolve before we mark intent
    except LinkedInError as exc:
        print(f"  FAILED (config): {exc}")
        return "failed"

    text = post_text(cells)
    ledger.mark_publishing(key, acct.board, text)     # durable intent, before the POST
    try:
        urn = client.create_text_post(author, text)
    except LinkedInError as exc:                       # definitive non-2xx: no post made
        ledger.mark_failed(key, str(exc))
        print(f"  FAILED (stays In Progress, retries): {exc}")
        return "failed"
    except (httpx.TimeoutException, httpx.TransportError) as exc:   # ambiguous outcome
        ledger.mark_reconcile(key, str(exc))
        print(f"  AMBIGUOUS send {key} ({exc}); RECONCILE_REQUIRED, will NOT auto-retry")
        return "needs_reconcile"

    ledger.mark_published(key, urn)                   # durable success, BEFORE AppFlowy
    try:
        stamp_completed(ctx, key, urn, statuses.done)
    except Exception as exc:
        print(f"  published {urn} BUT AppFlowy writeback failed: {exc} "
              "-> reconciled next run")
        return "published_unstamped"
    print(f"  published {urn} -> {statuses.done}")
    return "published"


def preflight(cfg, env, api) -> int:
    """Offline readiness report: reads real local state (env presence, token
    store, databases.json), prints NO secrets, and names the single next action.
    Makes the setup runbook self-verifying. Returns 0 when fully ready, else 1."""
    import json

    checks: list[tuple[str, bool, str]] = []

    # 1. version is set (the value itself must be verified vs LinkedIn's Latest)
    checks.append(("LinkedIn-Version set", bool(api.version),
                   f"{api.version} - verify it is LinkedIn's current Latest (YYYYMM)"))

    # 2. boards exist in databases.json
    db_path = Path(cfg.source.growthos_root) / cfg.source.database_map_path
    db_map = json.loads(db_path.read_text(encoding="utf-8")) if db_path.exists() else {}
    for acct in cfg.accounts:
        checks.append((f"board {acct.board}", acct.board in db_map,
                       "present in databases.json" if acct.board in db_map
                       else "run growth-os/scripts/new_content_board.py"))

    # 3. app credentials present (presence only — never print the values)
    for key in (api.client_id_env, api.client_secret_env, api.redirect_uri_env):
        checks.append((key, bool(env.get(key)), "set in .env" if env.get(key)
                       else "create the LinkedIn app, put this in .env"))

    # 4. token store present, valid, member URN resolved
    tok = TokenStore.load(api.token_store)
    exp = (time.strftime("%Y-%m-%d", time.localtime(tok.expires_at))
           if tok.expires_at else "(none)")
    checks.append(("OAuth token", tok.valid,
                   f"valid until {exp}" if tok.valid
                   else "run `cc linkedin-publish --login`"))
    checks.append(("member URN cached", bool(tok.member_urn),
                   tok.member_urn or "resolved on --login"))

    # 5. org URN present for each organization account
    for acct in cfg.accounts:
        if acct.author == "organization":
            ok = bool(env.get(acct.org_urn_env))
            checks.append((f"{acct.org_urn_env} ({acct.board})", ok,
                           "set in .env" if ok
                           else "after Page admin + Community Management API approval"))

    print("LinkedIn pipeline preflight (local state only; no secrets shown):")
    for label, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'MISSING'}] {label}: {detail}")
    warn = token_warning(tok, api.token_warn_days)
    if warn:
        print(f"  [WARN] {warn}")
    nxt = next((c for c in checks if not c[1]), None)
    if nxt is None:
        print("READY - approve drafts (drag In Queue -> In Progress), then "
              "`cc linkedin-publish` (dry-run) and `--apply`.")
        return 0
    print(f"NOT READY - next: {nxt[0]} -> {nxt[2]}")
    return 1


def run(cfg, env, api, args, now, ledger) -> int:
    client: LinkedInClient | None = None
    if args.apply:
        client = LinkedInClient(api, env)
        warn = token_warning(client.tokens, api.token_warn_days)
        if warn:
            print(f"WARNING: {warn}")
        elif client.tokens.expires_at:
            print("LinkedIn token valid until "
                  f"{time.strftime('%Y-%m-%d', time.localtime(client.tokens.expires_at))}")
    total_due = total_published = 0
    for acct in cfg.accounts:
        if args.account and acct.board != args.account:
            continue
        source = account_source(cfg.source, acct.board)
        due = due_rows(rows_from_appflowy(source, env)[: args.limit], cfg.statuses, now)
        total_due += len(due)
        for key, cells in due:
            sched = date_start(cells.get("ScheduledFor"))[:10]
            flag = f" [{ledger.state(key)}]" if ledger and ledger.state(key) else ""
            print(f"- [{acct.board}] {sched} :: {cell(cells, 'Hook')[:66]}{flag}")
            if not args.apply:
                continue
            ctx = appflowy_ctx(source, env)
            if publish_row(client, acct, env, ctx, key, cells, cfg.statuses, ledger) \
                    in ("published", "reconciled"):
                total_published += 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"linkedin-publish: {mode} ({total_due} due row(s)"
          + (f", {total_published} shipped)" if args.apply else ")"))
    if total_due and not args.apply:
        print("dry-run only; rerun with --apply to publish")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/content.yaml")
    ap.add_argument("--account", default="", help="limit to one board name")
    ap.add_argument("--apply", action="store_true", help="actually post to LinkedIn")
    ap.add_argument("--login", action="store_true", help="one-time OAuth authorize")
    ap.add_argument("--preflight", action="store_true",
                    help="report setup readiness (offline) and the next step")
    ap.add_argument("--orgs", action="store_true",
                    help="list the LinkedIn Page (organization) URNs you admin "
                         "(needs org scope) - copy the WMS one into LINKEDIN_WMS_ORG_URN")
    ap.add_argument("--include-org", action="store_true",
                    help="with --login: also request organization scopes (needs the "
                         "Community Management API product approved)")
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    cfg = ContentConfig.model_validate(read_yaml(args.config))
    env = merged_env(Path(".env"), Path(cfg.source.growthos_root) / ".env")
    api = cfg.linkedin

    if args.preflight:
        return preflight(cfg, env, api)

    if args.orgs:
        orgs = LinkedInClient(api, env).list_admined_orgs()
        if not orgs:
            print("No administered Pages found - are you a Page admin and is the "
                  "Community Management API approved?")
            return 1
        print("LinkedIn Pages you administer (put the WMS one in LINKEDIN_WMS_ORG_URN):")
        for u in orgs:
            print(f"  {u}")
        return 0

    if args.login:
        scopes = list(api.member_scopes)
        if args.include_org:
            scopes += [s for s in api.organization_scopes if s not in scopes]
        LinkedInClient(api, env).login(scopes)
        return 0

    now = datetime.now(timezone.utc)
    ledger = PublishLedger(api.publish_ledger)
    # A live run takes the single-process lock so two scheduled instances can't
    # post the same row; dry-run needs no lock (read-only).
    lock = ProcessLock(api.lock_path) if args.apply else contextlib.nullcontext()
    try:
        with lock:
            return run(cfg, env, api, args, now, ledger)
    except AlreadyRunning as exc:
        print(f"linkedin-publish: {exc}; another run is active, exiting cleanly")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

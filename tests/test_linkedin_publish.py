"""Safety tests for the LinkedIn publisher: the approval gate, temporal safety,
and the anti-double-post ledger/lock. These guard the only component allowed to
publish externally, so the invariants are worth pinning."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from command_center.schemas import ContentStatuses
import time

from command_center.cli.linkedin_publish import (
    date_start, due_rows, preflight, token_warning, post_text)
from command_center.cli.env_utils import read_yaml
from command_center.schemas import ContentConfig
from command_center.linkedin.ledger import (
    ProcessLock, PublishLedger, AlreadyRunning,
)

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
ST = ContentStatuses()  # In Queue / Scheduled / Published


def _row(**cells):
    return {"cells": cells}


def _date(iso):
    return {"start": iso, "include_time": False}


def test_date_start_handles_dict_and_scalar():
    assert date_start(_date("2026-06-14T00:00:00+00:00")) == "2026-06-14T00:00:00+00:00"
    assert date_start("plain") == "plain"
    assert date_start(None) == ""
    assert date_start({}) == ""


def test_due_rows_only_approved_due_unpublished_with_key():
    rows = [
        # eligible: approved, due, no PostURN, has Key
        _row(Status="Scheduled", Key="a", Hook="A",
             ScheduledFor=_date("2026-06-13T00:00:00+00:00")),
        # not approved (still In Queue) -> the human gate
        _row(Status="In Queue", Key="b", Hook="B",
             ScheduledFor=_date("2026-06-13T00:00:00+00:00")),
        # approved but scheduled in the FUTURE -> temporal safety
        _row(Status="Scheduled", Key="c", Hook="C",
             ScheduledFor=_date("2026-06-20T00:00:00+00:00")),
        # approved + due but already has a PostURN -> already published
        _row(Status="Scheduled", Key="d", Hook="D", PostURN="urn:li:share:1",
             ScheduledFor=_date("2026-06-13T00:00:00+00:00")),
        # approved + due but no Key -> cannot stamp back, skipped
        _row(Status="Scheduled", Hook="E",
             ScheduledFor=_date("2026-06-13T00:00:00+00:00")),
        # approved but no schedule at all -> skipped
        _row(Status="Scheduled", Key="f", Hook="F"),
    ]
    keys = [k for k, _ in due_rows(rows, ST, NOW)]
    assert keys == ["a"]


def test_ledger_blocks_repost_and_is_durable(tmp_path):
    p = tmp_path / "led.json"
    led = PublishLedger(p)
    assert led.state("k") is None and not led.blocks_repost("k")

    led.mark_publishing("k", "acct", "body text")
    assert led.blocks_repost("k")            # in-flight -> never repost

    led.mark_published("k", "urn:li:share:9")
    assert led.blocks_repost("k") and led.urn("k") == "urn:li:share:9"

    # survives a crash: a fresh reader sees the same durable state
    assert PublishLedger(p).state("k") == "PUBLISHED"


def test_ledger_failed_is_eligible_again(tmp_path):
    led = PublishLedger(tmp_path / "led.json")
    led.mark_publishing("k", "acct", "x")
    led.mark_failed("k", "HTTP 500")
    # a definitive non-2xx (no post created) may be retried
    assert not led.blocks_repost("k")


def test_ledger_reconcile_required_blocks_repost(tmp_path):
    led = PublishLedger(tmp_path / "led.json")
    led.mark_publishing("k", "acct", "x")
    led.mark_reconcile("k", "read timeout")
    # ambiguous outcome -> never auto-retry
    assert led.blocks_repost("k")


def test_preflight_not_ready_without_creds(tmp_path, capsys):
    # Real config + boards, but no credentials and an absent token store -> not
    # ready, and it must surface the missing creds (no false "READY").
    cfg = ContentConfig.model_validate(read_yaml("configs/content.yaml"))
    api = cfg.linkedin.model_copy(update={"token_store": str(tmp_path / "none.json")})
    rc = preflight(cfg, env={}, api=api)
    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT READY" in out
    assert "LINKEDIN_CLIENT_ID" in out


def test_post_text_joins_hook_and_body():
    assert post_text({"Hook": "Big claim.", "Body": "The detail."}) == \
        "Big claim.\n\nThe detail."
    assert post_text({"Hook": "Just a hook"}) == "Just a hook"
    assert post_text({"Body": "Just a body"}) == "Just a body"


class _Tok:
    def __init__(self, expires_at):
        self.expires_at = expires_at


def test_token_warning_windows():
    day = 86400
    # comfortably valid (30d out, 14d window) -> no warning
    assert token_warning(_Tok(time.time() + 30 * day), 14) is None
    # within the window (5d out) -> warns
    w = token_warning(_Tok(time.time() + 5 * day), 14)
    assert w and "expires in" in w and "--login" in w
    # already expired -> warns EXPIRED
    e = token_warning(_Tok(time.time() - day), 14)
    assert e and "EXPIRED" in e
    # no expiry recorded -> nothing to warn about
    assert token_warning(_Tok(0), 14) is None


def test_process_lock_is_exclusive_then_reusable(tmp_path):
    lock = tmp_path / "p.lock"
    with ProcessLock(lock):
        with pytest.raises(AlreadyRunning):
            with ProcessLock(lock):
                pass
    # released on exit -> acquirable again
    with ProcessLock(lock):
        pass

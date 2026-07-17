"""Typed chat attachments — safety checks (plan §4 + the attachments/privacy
test matrix). Path-backed attachments are clamped to the context root, secret
paths and escapes are refused, oversized files are refused, digests are
computed, and blocked attachments are REPORTED not dropped.
"""
from __future__ import annotations

from command_center.agent_sessions.attachments import (
    resolve_attachment,
    summarize_attachments,
)


def _resolve(tmp, rel, *, kind="file", external_egress=False):
    return resolve_attachment(
        attachment_id="a1", kind=kind, rel_path=rel, resource_id=None,
        display_name=rel or "x", context_root=tmp, external_egress=external_egress)


def test_normal_file_resolves_with_digest_and_size(tmp_path):
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    res = _resolve(tmp_path, "notes.md")
    assert res.attachment is not None and res.refusal is None
    a = res.attachment
    assert a.path_ref == "notes.md"
    assert a.size_bytes == 5
    assert a.content_digest and a.content_digest.startswith("sha256:")
    assert a.egress_allowed is True            # local harness → stays on box


def test_secret_path_is_refused(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("KEY", encoding="utf-8")
    res = _resolve(tmp_path, ".ssh/id_rsa")
    assert res.attachment is None
    assert "secret" in res.refusal.reason
    # .env too
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    assert _resolve(tmp_path, ".env").refusal is not None


def test_path_escape_is_refused(tmp_path):
    res = _resolve(tmp_path, "../outside.txt")
    assert res.attachment is None
    assert "escape" in res.refusal.reason


def test_missing_path_is_refused(tmp_path):
    res = _resolve(tmp_path, "nope.txt")
    assert res.attachment is None
    assert "no such path" in res.refusal.reason


def test_oversized_file_is_refused(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 2_000_001)
    res = _resolve(tmp_path, "big.bin")
    assert res.attachment is None
    assert "cap" in res.refusal.reason


def test_external_egress_marks_attachment_not_egress_allowed(tmp_path):
    (tmp_path / "f.txt").write_text("data", encoding="utf-8")
    res = _resolve(tmp_path, "f.txt", external_egress=True)
    assert res.attachment.egress_allowed is False   # must be acked at send time


def test_non_path_kind_resolves_by_resource_id():
    res = resolve_attachment(
        attachment_id="a2", kind="work_item", rel_path=None,
        resource_id="W-123", display_name="Fix header",
        context_root=None, external_egress=False)
    assert res.attachment is not None
    assert res.attachment.resource_id == "W-123"
    assert res.attachment.path_ref is None


def test_non_path_kind_requires_resource_id():
    res = resolve_attachment(
        attachment_id="a3", kind="work_item", rel_path=None, resource_id=None,
        display_name="x", context_root=None, external_egress=False)
    assert res.refusal is not None


def test_unknown_kind_is_refused(tmp_path):
    res = resolve_attachment(
        attachment_id="a4", kind="malware", rel_path="x", resource_id=None,
        display_name="x", context_root=tmp_path, external_egress=False)
    assert res.refusal is not None and "unknown attachment kind" in res.refusal.reason


def test_summary_reports_blocked_not_dropped(tmp_path):
    (tmp_path / "ok.txt").write_text("hi", encoding="utf-8")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("k", encoding="utf-8")
    resolutions = [_resolve(tmp_path, "ok.txt"), _resolve(tmp_path, ".ssh/id_rsa")]
    summary = summarize_attachments(resolutions)
    assert summary["count"] == 1
    assert summary["total_bytes"] == 2
    assert len(summary["blocked"]) == 1           # surfaced, not hidden
    assert summary["blocked"][0]["kind"] == "file"

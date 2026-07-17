"""Typed chat attachments — the composer's context references, resolved and
safety-checked BEFORE anything is sent to an assistant.

The plan (§4) is explicit: attachments must be TYPED references, not
concatenated blobs, and every path-backed one must be validated against the
selected context root, refusing `..`/symlink escapes and denied secret paths
(the SAME denylist the OpenRouter egress wall and Home workspace use —
secret_paths.is_secret_path). A blocked or oversized attachment is REPORTED,
never silently dropped.

Pure functions over the filesystem — no network, no session state — so the
safety checks are hermetically testable.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, model_validator

from ..schemas.base import Strict
from .secret_paths import is_secret_path

# A single file/attachment cap so one turn can't ship a huge blob off-box.
_MAX_ATTACHMENT_BYTES = 2_000_000
_DIGEST_READ_BYTES = 5_000_000            # hash at most this much

AttachmentKind = Literal[
    "file", "folder", "image", "url", "capture", "work_item",
    "board_card", "packet", "repo_file", "conversation_excerpt",
]
# Kinds that resolve to a filesystem path (clamped + secret-checked). The rest
# resolve by resource_id and never touch the filesystem.
_PATH_KINDS = frozenset({"file", "folder", "image", "repo_file"})


class ContextAttachment(Strict):
    """A typed, resolved attachment reference (never raw concatenated content)."""
    attachment_id: str
    kind: AttachmentKind
    display_name: str
    resource_id: str | None = None
    path_ref: str | None = None            # repo-relative, POSIX
    content_digest: str | None = None
    size_bytes: int | None = None
    provenance: str
    sensitivity: Literal["normal", "sensitive"] = "normal"
    egress_allowed: bool = False           # may this leave the machine as-is?


class AttachmentRefusal(Strict):
    """A requested attachment that was REFUSED — surfaced to the user, never
    dropped silently."""
    requested: str
    kind: str
    reason: str


class AttachmentResolution(Strict):
    """The result of resolving one requested attachment: exactly one of
    `attachment` / `refusal` is set."""
    model_config = ConfigDict(extra="forbid")
    attachment: ContextAttachment | None = None
    refusal: AttachmentRefusal | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AttachmentResolution":
        if (self.attachment is None) == (self.refusal is None):
            raise ValueError("exactly one of attachment/refusal must be set")
        return self


def _clamp(root: Path, rel: str) -> Path:
    """Resolve `rel` inside `root`, refusing any path that escapes it via `..`
    or a symlink. Same teeth as the read-only tool wall."""
    target = (root / rel).resolve()
    root_r = root.resolve()
    if target != root_r and root_r not in target.parents:
        raise ValueError(f"path {rel!r} escapes the context root")
    return target


def resolve_attachment(
    *,
    attachment_id: str,
    kind: str,
    rel_path: str | None,
    resource_id: str | None,
    display_name: str,
    context_root: Path | None,
    external_egress: bool,
) -> AttachmentResolution:
    """Resolve and safety-check ONE requested attachment.

    Path-backed kinds (file/folder/image/repo_file) are clamped to
    `context_root`, refused if they hit the secret denylist, escape the root,
    don't exist, or exceed the size cap; otherwise hashed (digest) + sized.
    Non-path kinds resolve by `resource_id`. `egress_allowed` is True only when
    the target harness is local (external egress requires the per-turn
    acknowledgement enforced at send time)."""
    def _refuse(reason: str) -> AttachmentResolution:
        return AttachmentResolution(refusal=AttachmentRefusal(
            requested=rel_path or resource_id or display_name,
            kind=str(kind), reason=reason))

    if kind not in AttachmentKind.__args__:   # type: ignore[attr-defined]
        return _refuse(f"unknown attachment kind {kind!r}")

    if kind in _PATH_KINDS:
        if not rel_path:
            return _refuse("a path is required for this attachment kind")
        if is_secret_path(rel_path):
            return _refuse("secret/credential path — never attachable")
        if context_root is None:
            return _refuse("no context root selected to resolve the path against")
        try:
            target = _clamp(context_root, rel_path)
        except ValueError as exc:
            return _refuse(str(exc))
        # a secret can also sit at the resolved absolute path
        if is_secret_path(str(target)):
            return _refuse("secret/credential path — never attachable")
        if not target.exists():
            return _refuse(f"no such path: {rel_path}")
        digest: str | None = None
        size: int | None = None
        if target.is_file():
            size = target.stat().st_size
            if size > _MAX_ATTACHMENT_BYTES:
                return _refuse(
                    f"file is {size} bytes — over the {_MAX_ATTACHMENT_BYTES} "
                    f"attachment cap")
            digest = "sha256:" + hashlib.sha256(
                target.read_bytes()[:_DIGEST_READ_BYTES]).hexdigest()
        return AttachmentResolution(attachment=ContextAttachment(
            attachment_id=attachment_id, kind=kind, display_name=display_name,
            path_ref=rel_path.replace("\\", "/"), content_digest=digest,
            size_bytes=size, provenance=f"context_root:{context_root}",
            sensitivity="normal", egress_allowed=not external_egress))

    # non-path kinds: a typed reference by resource_id, no filesystem read
    if not resource_id:
        return _refuse("a resource_id is required for this attachment kind")
    return AttachmentResolution(attachment=ContextAttachment(
        attachment_id=attachment_id, kind=kind, display_name=display_name,
        resource_id=resource_id, provenance=f"resource:{kind}",
        sensitivity="normal", egress_allowed=not external_egress))


def summarize_attachments(
    resolutions: list[AttachmentResolution],
) -> dict[str, object]:
    """A pre-send summary the composer shows: how many resolved, total bytes,
    and the blocked ones (surfaced, never hidden)."""
    ok = [r.attachment for r in resolutions if r.attachment is not None]
    blocked = [r.refusal for r in resolutions if r.refusal is not None]
    total = sum(a.size_bytes or 0 for a in ok)
    return {
        "count": len(ok),
        "total_bytes": total,
        "blocked": [b.model_dump() for b in blocked],
        "any_leaves_machine": any(not a.egress_allowed for a in ok),
    }

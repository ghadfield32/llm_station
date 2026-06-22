"""The canonical LinkedIn post object + its lints.

A `Draft` (draft.py) is the engine's internal hook/body pair; a `LinkedInPost`
is the reviewable, render-ready thing a human approves before it ships. Keeping
it a plain dataclass (like Candidate/Draft) so the renderers and the preview CLI
share one shape and the publisher can adopt it later without a pydantic import.

Everything here is deterministic and offline - no model calls. The point is to
make a generated post *reviewable*: where LinkedIn will cut it ("see more"), what
the above-the-fold hook actually is, and what will silently not render.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# LinkedIn text posts are capped at 3,000 characters. Only the first ~2 lines
# show in-feed before the "...see more" fold, and that cut is shorter on mobile
# than desktop - so the opening characters are the high-value hook zone, not the
# total length. These are the documented approximate cutoffs (they drift; treat
# as guidance, not a contract) and are named here so no renderer holds a literal.
LINKEDIN_MAX_CHARS = 3000
DESKTOP_SEE_MORE_CHARS = 210
MOBILE_SEE_MORE_CHARS = 140

_HASHTAG = re.compile(r"(?<!\w)#([A-Za-z][\w]*)")
# Markdown LinkedIn will NOT render (it ships as literal characters): ATX
# headings, **bold** / *italic* / `code`, and [text](url) links.
_MD_HEADING = re.compile(r"^#{1,6}\s", re.M)
_MD_EMPHASIS = re.compile(r"(\*\*|__|`)")
_MD_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")


@dataclass
class PostMedia:
    """An attached image/video/document. `path` is local; nothing is uploaded
    here - this only describes what the preview should show."""
    kind: str = "image"          # image | video | document
    path: str = ""
    alt: str = ""
    title: str = ""


@dataclass
class LinkPreview:
    """An unfurled link card (what LinkedIn shows when a post contains a URL)."""
    url: str
    title: str = ""
    description: str = ""
    image_path: str = ""
    source: str = ""             # display domain, e.g. "arxiv.org"


@dataclass
class PostWarning:
    """One pre-publish lint result. `level` is error|warn|info; errors mean the
    post should not ship as-is (e.g. over the hard character cap)."""
    level: str
    code: str
    message: str


@dataclass
class LinkedInPost:
    author_name: str
    body: str
    author_headline: str | None = None
    author_avatar_path: str | None = None
    media: list[PostMedia] = field(default_factory=list)
    link_preview: LinkPreview | None = None
    hashtags: list[str] = field(default_factory=list)
    visibility: str = "public"   # public | connections
    created_at: datetime | None = None
    id: str = ""                 # stable id (= Draft.key, when built from one)

    # ---- derived views -----------------------------------------------------
    def char_count(self) -> int:
        return len(self.body)

    def hook(self) -> str:
        """The above-the-fold first line - everything up to the first blank line
        (the most important text on LinkedIn). Falls back to the first sentence."""
        para = self.body.lstrip().split("\n\n", 1)[0].strip()
        first_line = para.split("\n", 1)[0].strip()
        return first_line or para

    def see_more_cut(self, device: str = "desktop") -> tuple[str, str]:
        """Split the body into (visible_before_see_more, hidden_remainder) at the
        device's fold, on a word boundary. Empty remainder => nothing is hidden."""
        limit = MOBILE_SEE_MORE_CHARS if device == "mobile" else DESKTOP_SEE_MORE_CHARS
        body = self.body
        if len(body) <= limit:
            return body, ""
        cut = body.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        return body[:cut].rstrip(), body[cut:].strip()

    def extracted_hashtags(self) -> list[str]:
        """Hashtags to display separately: the explicit `hashtags` list if set,
        else the #tags parsed out of the body (deduped, order-preserving)."""
        if self.hashtags:
            return list(dict.fromkeys(self.hashtags))
        return list(dict.fromkeys(_HASHTAG.findall(self.body)))

    def lint(self) -> list[PostWarning]:
        """Pre-publish checks. Surfaced in every preview so a post is reviewed,
        not just rendered. Order: hard errors first, then warnings, then info."""
        out: list[PostWarning] = []
        n = self.char_count()
        if n > LINKEDIN_MAX_CHARS:
            out.append(PostWarning("error", "over_length",
                                   f"body is {n} chars; LinkedIn caps text posts at "
                                   f"{LINKEDIN_MAX_CHARS}"))

        # A hook only exists if there's a deliberate break after the opening line.
        if "\n\n" not in self.body.strip() and "\n" not in self.body.strip():
            out.append(PostWarning("warn", "no_hook_break",
                                   "no line break after the opening - the hook and "
                                   "the body share one block; add a blank line"))
        if len(self.hook()) > DESKTOP_SEE_MORE_CHARS:
            out.append(PostWarning("warn", "weak_hook",
                                   f"hook is {len(self.hook())} chars and spills past "
                                   f"the desktop fold (~{DESKTOP_SEE_MORE_CHARS}); "
                                   "tighten the first line"))
        if "?" not in self.body:
            out.append(PostWarning("warn", "no_cta",
                                   "no question/CTA found - posts that end with a "
                                   "genuine question get more replies"))

        md = []
        if _MD_HEADING.search(self.body):
            md.append("# headings")
        if _MD_EMPHASIS.search(self.body):
            md.append("**bold**/`code`")
        if _MD_LINK.search(self.body):
            md.append("[text](url) links")
        if md:
            out.append(PostWarning("warn", "markdown_wont_render",
                                   "contains markdown LinkedIn renders literally: "
                                   + ", ".join(md)))

        _, hidden = self.see_more_cut("mobile")
        if hidden:
            out.append(PostWarning("info", "mobile_fold",
                                   "post is truncated on mobile; the hook carries it"))
        tags = self.extracted_hashtags()
        if tags:
            out.append(PostWarning("info", "hashtags",
                                   f"{len(tags)} hashtag(s) shown separately: "
                                   + " ".join("#" + t for t in tags)))
        return out


def from_draft(draft, author_name: str, author_headline: str | None = None,
               visibility: str = "public", hashtags: list[str] | None = None,
               link_preview: LinkPreview | None = None) -> LinkedInPost:
    """Build a render-ready post from an engine Draft. The hook becomes the
    above-the-fold first line; the body follows after a blank line."""
    body = f"{draft.hook.strip()}\n\n{draft.body.strip()}"
    return LinkedInPost(author_name=author_name, author_headline=author_headline,
                        body=body, visibility=visibility,
                        hashtags=list(hashtags or []), link_preview=link_preview,
                        id=getattr(draft, "key", ""))


def from_dict(d: dict) -> LinkedInPost:
    """Reconstruct a post from a stored dict (generated/content-posts.json). Media
    and link-preview nest as dicts; everything else is scalar."""
    media = [PostMedia(**m) for m in d.get("media", []) or []]
    lp = d.get("link_preview")
    return LinkedInPost(
        author_name=d["author_name"], body=d["body"],
        author_headline=d.get("author_headline"),
        author_avatar_path=d.get("author_avatar_path"),
        media=media, link_preview=LinkPreview(**lp) if lp else None,
        hashtags=list(d.get("hashtags", []) or []),
        visibility=d.get("visibility", "public"), id=d.get("id", ""))


def load_posts(store: str) -> list[LinkedInPost]:
    """Read the posts store. Accepts a bare list or {"posts": [...]}. A missing
    store is not an error - callers may be previewing inline text instead."""
    p = Path(store)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("posts", data) if isinstance(data, dict) else data
    return [from_dict(d) for d in items]

"""Render a LinkedInPost three ways:

  markdown_preview  -> terminal / logs (what you read in the CLI)
  html_preview      -> a self-contained, offline HTML file that looks like the
                       LinkedIn feed card (inline CSS, no JS, no network)
  export_text       -> the exact copy/paste text that goes to LinkedIn

All deterministic. The HTML deliberately simulates BOTH the desktop and the
mobile "...see more" fold so you can see the hook the way each reader will.
"""
from __future__ import annotations

import html

from ..post_model import (
    LinkedInPost, DESKTOP_SEE_MORE_CHARS, MOBILE_SEE_MORE_CHARS,
)

_LEVEL_MARK = {"error": "✗", "warn": "!", "info": "·"}


# ── copy-ready text ─────────────────────────────────────────────────────────
def export_text(post: LinkedInPost) -> str:
    """Exactly what to paste into LinkedIn. The body verbatim, with any
    separately-tracked hashtags appended only if they aren't already inline."""
    text = post.body.rstrip()
    tags = post.hashtags
    if tags and not any(f"#{t}" in text for t in tags):
        text += "\n\n" + " ".join(f"#{t}" for t in tags)
    return text


# ── terminal markdown ───────────────────────────────────────────────────────
def markdown_preview(post: LinkedInPost, device: str = "desktop") -> str:
    visible, hidden = post.see_more_cut(device)
    headline = post.author_headline or ""
    dot = "🌐 Anyone" if post.visibility == "public" else "👥 Connections"
    lines = [
        f"### {post.author_name}",
        f"_{headline}_" if headline else "",
        f"`{dot}` · `{post.char_count()}/{3000} chars` · hook fold: {device}",
        "",
        "**Above the fold (what shows before “…see more”):**",
        "> " + visible.replace("\n", "\n> "),
    ]
    if hidden:
        lines += ["", "**…see more (hidden until expanded):**",
                  "> " + hidden.replace("\n", "\n> ")]
    tags = post.extracted_hashtags()
    if tags:
        lines += ["", "**Hashtags:** " + " ".join("#" + t for t in tags)]
    if post.link_preview:
        lp = post.link_preview
        lines += ["", f"**Link card:** {lp.title or lp.url}  ({lp.source or lp.url})"]
    if post.media:
        lines += ["", "**Media:** " + ", ".join(f"{m.kind}:{m.path}" for m in post.media)]

    warns = post.lint()
    lines += ["", "**Pre-publish checks:**"]
    if not warns:
        lines.append("- ✓ clean")
    for w in warns:
        lines.append(f"- {_LEVEL_MARK.get(w.level, '·')} [{w.level}] {w.message}")
    return "\n".join(line for line in lines if line is not None)


# ── LinkedIn-styled HTML ────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return html.escape(s or "")


def _body_html(text: str) -> str:
    """LinkedIn renders plain text with line breaks - no markdown. Mirror that:
    escape everything, turn newlines into <br>, blank lines into paragraph gaps."""
    paras = text.split("\n\n")
    return "".join(f"<p>{_esc(p).replace(chr(10), '<br>')}</p>" for p in paras)


def _avatar(post: LinkedInPost) -> str:
    if post.author_avatar_path:
        return f'<img class="avatar" src="{_esc(post.author_avatar_path)}" alt="">'
    initials = "".join(w[0] for w in post.author_name.split()[:2]).upper() or "?"
    return f'<div class="avatar avatar-initials">{_esc(initials)}</div>'


def _card(post: LinkedInPost, device: str) -> str:
    visible, hidden = post.see_more_cut(device)
    limit = MOBILE_SEE_MORE_CHARS if device == "mobile" else DESKTOP_SEE_MORE_CHARS
    label = f"{device.title()} · fold ≈ {limit} chars"
    more = (f'<span class="seemore">…see more</span>'
            f'<div class="hidden-body">{_body_html(hidden)}</div>') if hidden else ""
    width = "320px" if device == "mobile" else "555px"
    return f"""
    <div class="feed">
      <div class="card-label">{_esc(label)}</div>
      <article class="post" style="max-width:{width}">
        <header>
          {_avatar(post)}
          <div class="who">
            <div class="name">{_esc(post.author_name)}</div>
            <div class="headline">{_esc(post.author_headline or '')}</div>
            <div class="meta">now · {'🌐' if post.visibility == 'public' else '👥'}</div>
          </div>
          <div class="more-dots">···</div>
        </header>
        <div class="body">
          {_body_html(visible)}{more}
        </div>
        {_media_html(post)}
        {_link_html(post)}
        {_hashtags_html(post)}
        <div class="counts">👍❤️💡 128 · 14 comments · 6 reposts</div>
        <div class="actions">
          <span>👍 Like</span><span>💬 Comment</span>
          <span>🔁 Repost</span><span>➤ Send</span>
        </div>
      </article>
    </div>"""


def _media_html(post: LinkedInPost) -> str:
    if not post.media:
        return ""
    m = post.media[0]
    return (f'<div class="media"><div class="media-kind">{_esc(m.kind)}</div>'
            f'<div class="media-path">{_esc(m.title or m.path)}</div></div>')


def _link_html(post: LinkedInPost) -> str:
    lp = post.link_preview
    if not lp:
        return ""
    return (f'<a class="linkcard" href="{_esc(lp.url)}">'
            f'<div class="lc-img">{_esc(lp.source or "link")}</div>'
            f'<div class="lc-title">{_esc(lp.title or lp.url)}</div>'
            f'<div class="lc-desc">{_esc(lp.description)}</div></a>')


def _hashtags_html(post: LinkedInPost) -> str:
    tags = post.extracted_hashtags()
    if not tags:
        return ""
    chips = "".join(f'<span class="chip">#{_esc(t)}</span>' for t in tags)
    return f'<div class="hashtags">{chips}</div>'


def _warnings_html(post: LinkedInPost) -> str:
    warns = post.lint()
    if not warns:
        return '<div class="warn ok">✓ Pre-publish checks: clean</div>'
    rows = "".join(
        f'<div class="warn {_esc(w.level)}"><b>{_esc(w.level)}</b> '
        f'{_esc(w.message)}</div>' for w in warns)
    return f'<div class="warnings"><h3>Pre-publish checks</h3>{rows}</div>'


_CSS = """
:root{--ln:#0a66c2;--bd:#e0e0e0;--txt:#1d1d1d;--mut:#666;--bg:#f4f2ee}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--txt);margin:0;padding:24px}
h1{font-size:18px;font-weight:600;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
.row{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}
.card-label{font-size:12px;color:var(--mut);margin:0 0 6px 2px}
.post{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:12px 16px;
  box-shadow:0 0 0 1px rgba(0,0,0,.02)}
.post header{display:flex;align-items:center;gap:8px}
.avatar{width:48px;height:48px;border-radius:50%;flex:0 0 48px;object-fit:cover}
.avatar-initials{background:var(--ln);color:#fff;display:flex;align-items:center;
  justify-content:center;font-weight:600;font-size:18px}
.who{flex:1;min-width:0}.name{font-weight:600;font-size:14px}
.headline{font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}.meta{font-size:12px;color:var(--mut)}
.more-dots{color:var(--mut);font-size:18px}
.body{font-size:14px;line-height:1.45;margin:10px 0 4px;white-space:normal}
.body p{margin:0 0 8px}
.seemore{color:var(--mut);cursor:default}
.hidden-body{border-left:3px solid var(--bd);padding-left:8px;margin-top:6px;
  color:#444;background:#fafafa}
.media{margin:8px 0;border:1px solid var(--bd);border-radius:6px;height:120px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  background:#f3f6f8;color:var(--mut)}.media-kind{font-weight:600;text-transform:uppercase;
  font-size:11px;letter-spacing:.05em}
.linkcard{display:block;border:1px solid var(--bd);border-radius:6px;margin:8px 0;
  text-decoration:none;color:inherit;overflow:hidden}
.lc-img{background:#eef3f8;color:var(--mut);padding:18px;font-size:12px;text-align:center}
.lc-title{font-weight:600;font-size:13px;padding:8px 10px 0}
.lc-desc{font-size:12px;color:var(--mut);padding:2px 10px 10px}
.hashtags{margin:8px 0}.chip{color:var(--ln);font-size:13px;margin-right:8px}
.counts{font-size:12px;color:var(--mut);border-top:1px solid var(--bd);margin-top:10px;
  padding-top:8px}
.actions{display:flex;justify-content:space-around;color:var(--mut);font-size:13px;
  font-weight:600;padding-top:6px}
.warnings{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:12px 16px;
  margin-top:8px;max-width:555px}
.warnings h3{margin:0 0 8px;font-size:14px}
.warn{font-size:13px;padding:6px 8px;border-radius:4px;margin-bottom:4px}
.warn.error{background:#fde7e9;color:#8a1f2b}.warn.warn{background:#fff4e5;color:#8a5a00}
.warn.info{background:#eef3f8;color:#33526e}.warn.ok{background:#e6f4ea;color:#1d6b35}
.export{background:#fff;border:1px solid var(--bd);border-radius:8px;padding:12px 16px;
  margin-top:8px;max-width:555px}
.export h3{margin:0 0 8px;font-size:14px}
.export pre{white-space:pre-wrap;font-family:inherit;font-size:13px;background:#f7f7f7;
  border:1px solid var(--bd);border-radius:6px;padding:10px;margin:0}
"""


def html_preview(post: LinkedInPost, device: str = "desktop") -> str:
    """A standalone HTML document - open it in any browser, no server needed.
    Shows the desktop and mobile cards, the see-more fold, hashtags, media/link
    card, the reaction row, pre-publish checks, and the copy-ready text."""
    title = f"LinkedIn preview · {post.author_name}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{_CSS}</style></head><body>
<h1>{_esc(title)}</h1>
<div class="sub">{post.char_count()}/3000 chars · offline preview · the two cards
 show how the same post folds on desktop vs mobile</div>
<div class="row">
  {_card(post, "desktop")}
  {_card(post, "mobile")}
</div>
{_warnings_html(post)}
<div class="export"><h3>Copy-ready text</h3><pre>{_esc(export_text(post))}</pre></div>
</body></html>"""

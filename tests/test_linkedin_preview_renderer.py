"""The LinkedIn preview contract: a generated post is reviewable before it ships.
Pins the post model's derived views (hook, see-more fold, hashtags), the lints
(over-length, weak hook, missing CTA, markdown-that-won't-render), and that all
three renderers produce the expected, offline output."""
from __future__ import annotations

from command_center.content.post_model import (
    LinkedInPost, PostMedia, LinkPreview, from_draft, from_dict,
    LINKEDIN_MAX_CHARS, DESKTOP_SEE_MORE_CHARS, MOBILE_SEE_MORE_CHARS,
)
from command_center.content.renderers import markdown_preview, html_preview, export_text


def _post(body, **kw):
    kw.setdefault("author_name", "Geoff Hadfield")
    return LinkedInPost(body=body, **kw)


# ── model: hook / fold / hashtags ───────────────────────────────────────────
def test_hook_is_first_line_before_blank():
    p = _post("The one line that matters.\n\nThen the rest of the post body here.")
    assert p.hook() == "The one line that matters."


def test_see_more_cut_splits_on_word_boundary_desktop():
    body = "word " * 100  # 500 chars, well past the desktop fold
    p = _post(body.strip())
    visible, hidden = p.see_more_cut("desktop")
    assert len(visible) <= DESKTOP_SEE_MORE_CHARS
    assert not visible.endswith(" ")        # trimmed on a boundary
    assert hidden                            # remainder is hidden
    assert (visible + " " + hidden).split() == body.split()  # nothing lost


def test_mobile_fold_is_shorter_than_desktop():
    body = "word " * 100
    p = _post(body.strip())
    assert len(p.see_more_cut("mobile")[0]) <= MOBILE_SEE_MORE_CHARS
    assert MOBILE_SEE_MORE_CHARS < DESKTOP_SEE_MORE_CHARS


def test_short_post_has_no_hidden_remainder():
    p = _post("Short and sweet. Thoughts?")
    assert p.see_more_cut("desktop")[1] == ""


def test_hashtags_parsed_from_body_when_not_explicit():
    p = _post("A post about #PyMC and #Bayesian methods. #PyMC again?")
    assert p.extracted_hashtags() == ["PyMC", "Bayesian"]   # deduped, ordered


def test_explicit_hashtags_win_over_body():
    p = _post("Body with #Inline tag?", hashtags=["Curated", "Tags"])
    assert p.extracted_hashtags() == ["Curated", "Tags"]


# ── lints ───────────────────────────────────────────────────────────────────
def _codes(p):
    return {w.code for w in p.lint()}


def test_over_length_is_an_error():
    p = _post("x" * (LINKEDIN_MAX_CHARS + 1) + "?\n\nmore")
    errs = [w for w in p.lint() if w.level == "error"]
    assert any(w.code == "over_length" for w in errs)


def test_weak_hook_and_missing_cta_warn():
    long_first_line = "x" * (DESKTOP_SEE_MORE_CHARS + 20)
    p = _post(long_first_line + "\n\nbody with no question")
    codes = _codes(p)
    assert "weak_hook" in codes
    assert "no_cta" in codes


def test_markdown_that_wont_render_warns():
    p = _post("# Heading\n\nSome **bold** and a [link](http://x). Thoughts?")
    assert "markdown_wont_render" in _codes(p)


def test_clean_post_has_no_warnings_or_errors():
    p = _post("A tight hook line.\n\nA short, plain body that asks a real question?")
    assert not [w for w in p.lint() if w.level in ("error", "warn")]


# ── constructors ────────────────────────────────────────────────────────────
class _Draft:
    key = "cand-abc123"
    hook = "Hook line."
    body = "Body paragraph. Worth a look?"


def test_from_draft_joins_hook_and_body():
    p = from_draft(_Draft(), author_name="Geoff", author_headline="ML eng")
    assert p.body == "Hook line.\n\nBody paragraph. Worth a look?"
    assert p.id == "cand-abc123"
    assert p.hook() == "Hook line."


def test_from_dict_roundtrip_with_media_and_link():
    d = {"author_name": "WMS", "body": "Body?", "id": "p1",
         "media": [{"kind": "image", "path": "a.png"}],
         "link_preview": {"url": "http://x", "title": "T", "source": "x"}}
    p = from_dict(d)
    assert isinstance(p.media[0], PostMedia) and p.media[0].path == "a.png"
    assert isinstance(p.link_preview, LinkPreview) and p.link_preview.title == "T"


# ── renderers ───────────────────────────────────────────────────────────────
def test_export_text_appends_separate_hashtags_once():
    p = _post("Body without tags?", hashtags=["AI", "MLOps"])
    out = export_text(p)
    assert out.endswith("#AI #MLOps")
    # if a tag is already inline, it is not appended again
    p2 = _post("Body with #AI inline?", hashtags=["AI"])
    assert export_text(p2).count("#AI") == 1


def test_markdown_preview_shows_fold_and_checks():
    p = _post("word " * 100 + "?")
    md = markdown_preview(p, "desktop")
    assert "Above the fold" in md
    assert "see more" in md
    assert "Pre-publish checks" in md


def test_html_preview_is_self_contained_and_escaped():
    p = _post("Tag <script>alert(1)</script> & co?", author_headline="x")
    h = html_preview(p)
    assert h.startswith("<!doctype html>")
    assert "<style>" in h                       # inline CSS, no external sheet
    assert "<link" not in h and "src=\"http" not in h  # nothing fetched from network
    assert "<script>alert(1)" not in h          # body is escaped
    assert "&lt;script&gt;" in h
    # both device cards are rendered
    assert h.count("class=\"post\"") == 2

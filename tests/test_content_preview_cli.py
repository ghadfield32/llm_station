"""The content-preview CLI: inline preview, exact-id lookup with an HTML file
written out, the over-length hard-fail exit code, and that the fuzzy `--post`
path delegates to the reference resolver (the no-exact-name-required entry).
Pins the user-facing surface of Steps 1 + 3."""
from __future__ import annotations

import json

from command_center.cli import content_preview as cp
from command_center.content.post_model import LinkedInPost, LINKEDIN_MAX_CHARS


def test_inline_preview_returns_zero_and_renders(capsys, tmp_path):
    rc = cp.main(["--author", "Geoff", "--headline", "ML eng",
                  "--body", "Tight hook.\n\nShort body that asks something?",
                  "--no-html"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Geoff" in out and "Pre-publish checks" in out


def test_over_length_inline_exits_one(capsys, tmp_path):
    rc = cp.main(["--author", "G", "--body", "x" * (LINKEDIN_MAX_CHARS + 5) + "?",
                  "--no-html"])
    assert rc == 1                          # hard cap is a real failure


def test_exact_id_writes_html_file(capsys, tmp_path):
    store = tmp_path / "posts.json"
    store.write_text(json.dumps({"posts": [
        {"author_name": "Geoff", "id": "p1",
         "body": "Hook line.\n\nBody with a question?"}]}), encoding="utf-8")
    html = tmp_path / "p1.html"
    rc = cp.main(["--post-id", "p1", "--store", str(store), "--html-out", str(html)])
    assert rc == 0
    assert html.exists()
    text = html.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "Hook line." in text


def test_fuzzy_post_delegates_to_resolver(capsys, tmp_path, monkeypatch):
    sentinel = LinkedInPost(author_name="WMS", body="Resolved post.\n\nWhy?", id="r1")
    called = {}

    def fake_resolve(query, store, live, pipeline):
        called["args"] = (query, store)
        return sentinel
    monkeypatch.setattr(cp, "_resolve", fake_resolve)

    rc = cp.main(["--post", "that glm router post", "--store", str(tmp_path / "s.json"),
                  "--no-html"])
    assert rc == 0
    assert called["args"][0] == "that glm router post"
    assert "Resolved post." in capsys.readouterr().out


def test_nothing_to_preview_errors(capsys):
    import pytest
    with pytest.raises(SystemExit):
        cp.main(["--no-html"])

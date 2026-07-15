"""The Posts domain must provide a real LinkedIn-style draft entry surface."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def test_posts_board_exposes_linkedin_composer_and_live_preview():
    source = APP_TSX.read_text(encoding="utf-8")
    assert "function LinkedInPostComposer" in source
    assert "New post" in source
    assert "LinkedInPreview" in source
    assert "createLinkedInPostDraft" in source
    assert "3000" in source

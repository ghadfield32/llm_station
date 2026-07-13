"""Create-Board module endpoint — one typed request stands up BOTH a kanban
board (repo/verb/status contract) and its domain surface (generic_task cards),
so a user-created board gets the same treatment as a built-in one.

Governance is the point: the new board's wall verbs are ALWAYS forbidden and the
write is atomic + gated. Hermetic: CONFIGS_DIR points at a tmp dir seeded with
empty-but-valid configs; the endpoint's real Pydantic validators run.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "services" / "agent_kanban_ui" / "app.py"

_WALL = {"approve_card", "merge", "deploy", "delete_card", "delete_board"}


def _seed_configs(tmp: Path) -> None:
    (tmp / "domain_surfaces.yaml").write_text(
        yaml.safe_dump({"schema_version": "command-center.domain-surfaces.v1",
                        "domains": []}), encoding="utf-8")
    (tmp / "kanban_boards.yaml").write_text(
        yaml.safe_dump({"schema_version": "command-center.kanban-boards.v1",
                        "boards": []}), encoding="utf-8")


def _load(monkeypatch, tmp_path, *, writes=True):
    from fastapi.testclient import TestClient
    _seed_configs(tmp_path)
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_boardmod_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_boardmod_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", writes)
    return mod, TestClient(mod.app)


def test_create_board_module_writes_both_configs_with_safe_governance(monkeypatch, tmp_path):
    mod, tc = _load(monkeypatch, tmp_path)
    r = tc.post("/api/board-module",
                json={"title": "My Books", "description": "reading list"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["board_id"] == "my_books"
    assert body["provider"] == "command_center_ui"
    assert body["card_component"] == "generic_task"

    # kanban board written, validates, wall verbs forbidden, human wall intact
    reg = yaml.safe_load((tmp_path / "kanban_boards.yaml").read_text(encoding="utf-8"))
    board = next(b for b in reg["boards"] if b["board_id"] == "my_books")
    assert board["provider"] == "command_center_ui"
    assert _WALL <= set(board["forbidden_agent_verbs"])
    assert _WALL.isdisjoint(board["allowed_agent_verbs"])
    # a new personal board is a LIFE board: no repository, no fake board-id-as-repo
    assert board["execution_scope"] == "life"
    assert board["repo_ids"] == []
    from command_center.schemas.contracts import KanbanBoardsConfig
    KanbanBoardsConfig.model_validate(reg)          # the written file is valid

    # domain surface written, board_store + generic_task, board_id linked
    dom = yaml.safe_load((tmp_path / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    surface = next(d for d in dom["domains"] if d["domain_id"] == "my_books")
    assert surface["source"] == "board_store"
    assert surface["card_component"] == "generic_task"
    assert surface["board_id"] == "my_books"
    from command_center.schemas.contracts import DomainSurfacesConfig
    DomainSurfacesConfig.model_validate(dom)

    # the create was audited
    audit = (tmp_path / "config_audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["board_id"] == "my_books" for line in audit)


def test_repository_board_requires_a_repo(monkeypatch, tmp_path):
    mod, tc = _load(monkeypatch, tmp_path)
    # a repository-scope board with no repo is rejected (no fake board-id fallback)
    r = tc.post("/api/board-module",
                json={"title": "CV Pipeline", "execution_scope": "repository"})
    assert r.status_code == 400
    # with a repo it's created and carries the scope + repo through
    ok = tc.post("/api/board-module", json={
        "title": "CV Pipeline", "execution_scope": "repository",
        "repo_ids": ["betts_basketball"]})
    assert ok.status_code == 201, ok.text
    assert ok.json()["execution_scope"] == "repository"
    reg = yaml.safe_load((tmp_path / "kanban_boards.yaml").read_text(encoding="utf-8"))
    board = next(b for b in reg["boards"] if b["board_id"] == "cv_pipeline")
    assert board["repo_ids"] == ["betts_basketball"]
    from command_center.schemas.contracts import KanbanBoardsConfig
    KanbanBoardsConfig.model_validate(reg)


def test_duplicate_board_is_409(monkeypatch, tmp_path):
    mod, tc = _load(monkeypatch, tmp_path)
    assert tc.post("/api/board-module", json={"title": "Health"}).status_code == 201
    assert tc.post("/api/board-module", json={"title": "Health"}).status_code == 409


def test_empty_title_is_400(monkeypatch, tmp_path):
    mod, tc = _load(monkeypatch, tmp_path)
    assert tc.post("/api/board-module", json={"title": "   "}).status_code == 400


def test_create_is_write_gated_503(monkeypatch, tmp_path):
    mod, tc = _load(monkeypatch, tmp_path, writes=False)
    r = tc.post("/api/board-module", json={"title": "Papers"})
    assert r.status_code == 503
    # and it wrote nothing
    reg = yaml.safe_load((tmp_path / "kanban_boards.yaml").read_text(encoding="utf-8"))
    assert reg["boards"] == []


# --- frontend guardrail (source-level) -------------------------------------------

APP_TSX = ROOT / "services" / "agent_kanban_ui" / "web" / "src" / "App.tsx"


def test_frontend_has_a_guided_create_board_wizard():
    src = APP_TSX.read_text(encoding="utf-8")
    assert "function CreateBoardWizard" in src
    assert "createBoardModule(" in src
    # reachable from the Boards controls surface, with a live preview
    assert "Create board" in src
    assert "schema-preview" in src

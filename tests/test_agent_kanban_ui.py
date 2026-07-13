"""Phase 4: the agent kanban UI backend.

Hermetic — the Ledger HTTP call and the agent-call log are stubbed, so we test the
grouping/proxy/metrics shape and the fail-loud Ledger path with no live services.
Write-capable console routes stay gated and validate their target config before
touching disk.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = Path(__file__).resolve().parents[1] / "services" / "agent_kanban_ui" / "app.py"
WEB = ROOT / "services" / "agent_kanban_ui" / "web"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_under_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod, TestClient(mod.app)


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_missions_grouped_into_ordered_columns(client, monkeypatch):
    mod, tc = client
    rows = [
        {"id": "T-1", "action": "do a", "risk": "L2", "status": "running"},
        {"id": "T-2", "action": "do b", "risk": "L3", "status": "awaiting_approval"},
        {"id": "T-3", "action": "do c", "risk": "L1", "status": "running"},
    ]
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp(rows))
    body = tc.get("/api/missions").json()
    assert body["total"] == 3
    names = [c["name"] for c in body["columns"]]
    # live columns appear in canonical order; awaiting_approval before running
    assert names == ["awaiting_approval", "running"]
    running = next(c for c in body["columns"] if c["name"] == "running")
    assert len(running["cards"]) == 2


def test_unknown_status_still_shown_not_hidden(client, monkeypatch):
    mod, tc = client
    rows = [{"id": "T-9", "action": "x", "status": "quarantined"}]
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp(rows))
    names = [c["name"] for c in tc.get("/api/missions").json()["columns"]]
    assert "quarantined" in names


def test_ledger_unreachable_is_502_not_empty_board(client, monkeypatch):
    mod, tc = client

    def boom(*a, **k):
        raise mod.httpx.ConnectError("refused")

    monkeypatch.setattr(mod.httpx, "get", boom)
    r = tc.get("/api/missions")
    detail = r.json()["detail"]
    assert r.status_code == 502
    assert "ledger unreachable" in detail
    assert "/missions" in detail


def test_metrics_uses_kanban_metrics(client, monkeypatch):
    mod, tc = client
    calls = [{"ts": "t", "surface": "discord", "tool": "stage_card",
              "args": {}, "ok": True, "ms": 5.0}]
    monkeypatch.setattr(mod, "load_calls", lambda *a, **k: calls)
    body = tc.get("/api/metrics").json()
    assert body["total_calls"] == 1 and body["intent_verb_calls"] == 1


def test_health_and_config(client):
    _, tc = client
    assert tc.get("/api/health").json()["status"] == "ok"
    cfg = tc.get("/api/config").json()
    # chat is OFF by default (no KANBAN_UI_CHAT_ENABLED in the test env)
    assert cfg["chat_enabled"] is False and cfg["model_roles"] == []


def test_pwa_assets_cache_static_assets_only():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((WEB / "public" / "manifest.webmanifest").read_text(encoding="utf-8"))
    service_worker = (WEB / "public" / "sw.js").read_text(encoding="utf-8")

    assert 'rel="manifest" href="/manifest.webmanifest"' in index
    assert 'name="apple-mobile-web-app-title" content="Kanban"' in index
    assert 'rel="apple-touch-icon" href="/icons/apple-touch-icon.png"' in index
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["name"] == "Agent Kanban Cockpit"
    assert manifest["short_name"] == "Kanban"
    assert any(
        icon["src"] == "/icons/cockpit-icon-192.png"
        and icon["sizes"] == "192x192"
        and icon["type"] == "image/png"
        for icon in manifest["icons"]
    )
    assert any(
        icon["src"] == "/icons/cockpit-icon-512.png"
        and icon["sizes"] == "512x512"
        and icon["type"] == "image/png"
        for icon in manifest["icons"]
    )
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    assert any(
        icon["src"] == "/icons/cockpit-maskable-512.png"
        and icon["sizes"] == "512x512"
        and icon["purpose"] == "maskable"
        for icon in manifest["icons"]
    )
    assert 'url.pathname.startsWith("/api/")' in service_worker
    assert 'request.method !== "GET"' in service_worker
    assert 'url.pathname.startsWith("/assets/")' in service_worker
    assert "/icons/apple-touch-icon.png" in service_worker


def test_chat_runtime_stays_behind_the_chat_wall(client):
    # specialist URLs come from operator env — a read-only deployment must
    # not serve them (nor lane/executor config) from /api/chat/runtime
    _, tc = client
    assert tc.get("/api/chat/runtime").status_code == 503


def _disable_frontier_lane(monkeypatch):
    """Explicit, self-contained disabled state — not a read of the live repo
    config, whose default.enabled is a genuine, changeable operator decision
    (see tests/test_frontier_client.py)."""
    from command_center.channels import frontier_client as fc_mod
    from command_center.improvement.frontier_router_eval import load_budgets
    budgets = load_budgets()
    disabled = budgets.model_copy(deep=True)
    disabled.default.enabled = False
    monkeypatch.setattr(fc_mod, "load_budgets", lambda: disabled)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)


def test_chat_runtime_is_one_gateway_no_specialist_links(client, monkeypatch):
    """The specialist link-outs (ORCA/OmniAgent/OxyGent) are GONE: one harness,
    one gateway, model switching through LOCAL roles + the opt-in FRONTIER lane,
    scoped-chat repo targets."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CONFIGS_DIR", Path(__file__).resolve().parents[1] / "configs")
    _disable_frontier_lane(monkeypatch)
    body = tc.get("/api/chat/runtime").json()
    assert body["harness"] == "GatewayCore"
    assert body["model_gateway"] == "LiteLLM"
    assert body["stream_endpoint"] == "/api/chat/stream"
    assert body["conversations_endpoint"] == "/api/chat/conversations"
    assert "external_chats" not in body
    assert "uses_orca" not in body
    repo_ids = {r["repo_id"] for r in body["repos"]}
    assert "llm_station" in repo_ids       # registered repos are chat targets
    assert "FRONTIER lane" in body["provider_note"]
    assert "cloud-free by design" in body["provider_note"]
    # executors (Claude Code / Codex CLI) are explicitly NOT chat models
    assert "not chat roles" in body["executor_note"]
    executor_names = {e["name"] for e in body["executors"]}
    assert {"claude-code", "codex-cli"} <= executor_names
    # the top-3 frontier candidates are reported (real config, real pricing,
    # unselectable by default since this test env has no key + lane disabled)
    frontier_ids = {f["model_id"] for f in body["frontier_models"]}
    assert {"glm-5.2", "deepseek-v4-pro", "kimi-k2.6"} <= frontier_ids
    assert all(not f["selectable"] for f in body["frontier_models"]
              if f["model_id"] in frontier_ids)


def test_frontier_model_selection_gated_off_by_default(client, monkeypatch):
    """A frontier: prefixed model is a real, known candidate — but stays
    unselectable (503, not 400) until the operator enables the lane + key.
    An unknown frontier id 400s distinctly from an unknown local role."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    _disable_frontier_lane(monkeypatch)
    r = tc.post("/api/chat/stream", json={
        "text": "hi", "conversation_id": "c1", "model": "frontier:glm-5.2"})
    assert r.status_code == 503
    assert "not enabled yet" in r.json()["detail"]

    r2 = tc.post("/api/chat/stream", json={
        "text": "hi", "conversation_id": "c1", "model": "frontier:not-a-real-model"})
    assert r2.status_code == 400
    assert "unknown frontier model" in r2.json()["detail"]


def test_chat_threads_store_shared_metadata(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    # transcripts off -> the server keeps compact thread metadata ONLY
    monkeypatch.setenv("GATEWAY_TRANSCRIPTS", "0")
    body = tc.get("/api/chat/threads").json()
    assert body["threads"] == []
    assert body["storage"] == "server_metadata_only"
    assert body["transcripts"]["enabled"] is False

    saved = tc.post("/api/chat/threads", json={
        "conversation_id": "job_application:job_1",
        "title": "Ruby Labs packet review",
        "last_prompt": "Review this application packet.",
        "model": "chat",
    }).json()
    assert saved["thread"]["conversation_id"] == "job_application:job_1"
    assert saved["thread"]["target"] == "GatewayCore"

    updated = tc.post("/api/chat/threads", json={
        "conversation_id": "job_application:job_1",
        "last_prompt": "What is the next action?",
        "model": "chat",
    }).json()
    assert len(updated["threads"]) == 1
    assert updated["threads"][0]["title"] == "What is the next action?"
    assert updated["threads"][0]["last_prompt"] == "What is the next action?"


def test_chat_thread_transcript_serves_full_story(client, monkeypatch, tmp_path):
    """The timeline endpoint returns the flight-recorder turns UNTRUNCATED —
    the whole point vs the SSE stream's 200/300-char cuts."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    monkeypatch.delenv("GATEWAY_TRANSCRIPTS", raising=False)

    from command_center.channels.transcript import TurnRecorder
    long_args = '{"query": "' + "x" * 400 + '"}'
    rec = TurnRecorder(surface="app", model="chat",
                       conversation_id="story-1", user_text="do the thing")
    rec.context("board_state")
    rec.tool("stage_card", long_args)
    rec.tool_result("stage_card", "ok-" + "y" * 400)
    rec.final("done")
    rec.flush()

    threads = tc.get("/api/chat/threads").json()
    assert threads["storage"] == "server_metadata_plus_transcripts"
    assert threads["transcripts"]["enabled"] is True

    body = tc.get("/api/chat/threads/story-1/transcript").json()
    assert body["turn_count"] == 1 and body["recording_enabled"] is True
    turn = body["turns"][0]
    assert turn["final"] == "done"
    assert turn["context_blocks"] == ["board_state"]
    tool = next(e for e in turn["events"] if e["type"] == "tool")
    assert tool["args"] == long_args                 # full args, no truncation
    result = next(e for e in turn["events"] if e["type"] == "tool_result")
    assert result["result"] == "ok-" + "y" * 400


def test_chat_transcript_endpoint_stays_behind_the_chat_wall(client):
    # read-only deployments (no KANBAN_UI_CHAT_ENABLED) must not serve
    # conversation content
    _, tc = client
    assert tc.get("/api/chat/threads/any/transcript").status_code == 503


def test_chat_conversations_index_merges_recorder_and_threads(
        client, monkeypatch, tmp_path):
    """The All Chats index: every recorded conversation (any surface) plus
    thread shortcuts that have not produced a recorded turn yet."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    monkeypatch.delenv("GATEWAY_TRANSCRIPTS", raising=False)

    from command_center.channels.transcript import TurnRecorder
    rec = TurnRecorder(surface="Discord", model="chat",
                       conversation_id="disc-1", user_text="from discord")
    rec.final("hello")
    rec.flush()
    tc.post("/api/chat/threads", json={
        "conversation_id": "app-only", "title": "No turns yet",
        "last_prompt": "queued question"})

    body = tc.get("/api/chat/conversations").json()
    by_id = {c["conversation_id"]: c for c in body["conversations"]}
    assert by_id["disc-1"]["turns"] == 1
    assert by_id["disc-1"]["surfaces"] == ["Discord"]
    assert by_id["app-only"]["turns"] == 0             # shortcut, not recorded
    assert by_id["app-only"]["title"] == "No turns yet"
    assert body["total"] >= 2


def test_chat_conversations_stay_behind_the_chat_wall(client):
    _, tc = client
    assert tc.get("/api/chat/conversations").status_code == 503
    # chat-history delete is chat-gated too
    assert tc.delete("/api/chat/threads/any").status_code == 503


def test_delete_conversation_clears_chat_history_only(
        client, monkeypatch, tmp_path):
    """Deleting a chat removes the thread shortcut + transcript file — and
    NOTHING else: the governed kanban event log is a different record."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    monkeypatch.delenv("GATEWAY_TRANSCRIPTS", raising=False)

    from command_center.channels.transcript import TurnRecorder, transcript_path
    rec = TurnRecorder(surface="app", model="chat",
                       conversation_id="bye", user_text="hello")
    rec.final("done")
    rec.flush()
    tc.post("/api/chat/threads", json={
        "conversation_id": "bye", "title": "Bye", "last_prompt": "hello"})
    tc.post("/api/chat/threads", json={
        "conversation_id": "keep", "title": "Keep", "last_prompt": "stay"})
    assert transcript_path("bye").is_file()

    body = tc.delete("/api/chat/threads/bye").json()
    assert body["status"] == "deleted" and body["transcript_removed"] is True
    assert not transcript_path("bye").is_file()
    remaining = {t["conversation_id"] for t in body["threads"]}
    assert remaining == {"keep"}
    index = tc.get("/api/chat/conversations").json()
    assert all(c["conversation_id"] != "bye" for c in index["conversations"])


def test_appflowy_board_domain_serves_snapshot_cards(client, monkeypatch, tmp_path):
    """The real papers/repos/dags data: cards come from the worker's board
    snapshot with an honest origin, the board's REAL lanes, and stable ids."""
    mod, tc = client
    snap = {
        "generated_at": "2026-07-01T00:00:00+00:00",
        "boards": [{
            "board": "papers",
            "statuses": ["Inbox", "Reading", "Read", "Archived"],
            "columns": [{
                "name": "Inbox",
                "cards": [{
                    "title": "Attention Is All You Need",
                    "meta": "9.9",
                    "fields": {"URL": "http://arxiv.org/abs/1706.03762",
                               "Authors": "Vaswani et al.",
                               "Abstract": "Transformers.",
                               "Topics": "cs.LG", "Score": "9.9",
                               "Status": "Inbox"},
                }],
            }],
        }],
    }
    snap_path = tmp_path / "board-snapshot.json"
    snap_path.write_text(json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", snap_path)

    out = mod._appflowy_board_cards(
        {"domain_id": "paper", "board": "papers", "columns": []})
    assert out["origin"] == "board_snapshot"
    assert out["generated_at"] == "2026-07-01T00:00:00+00:00"
    assert out["columns"] == ["Inbox", "Reading", "Read", "Archived"]
    card = out["cards"][0]
    assert card["title"] == "Attention Is All You Need"
    assert card["abstract"] == "Transformers."
    assert card["useful_for"] == "cs.LG"
    assert card["status"] == "Inbox"
    assert card["card_id"]                       # stable id for drawers/chat

    missing = mod._appflowy_board_cards(
        {"domain_id": "book", "board": "library", "columns": []})
    assert missing["cards"] == [] and "not in the snapshot" in missing["note"]


def test_transcript_card_story_is_fail_soft(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    # a plain (non card-scoped) conversation carries no card story
    assert mod._conversation_card_story("app") == []
    # unknown domain prefix: empty, never an error
    assert mod._conversation_card_story("nope:card-1") == []
    body = tc.get("/api/chat/threads/app/transcript").json()
    assert body["card_story"] == []


def test_chat_transcript_pages_from_the_newest_end(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    monkeypatch.delenv("GATEWAY_TRANSCRIPTS", raising=False)

    from command_center.channels.transcript import TurnRecorder
    for n in range(5):
        rec = TurnRecorder(surface="app", model="chat",
                           conversation_id="paged", user_text=f"turn {n}")
        rec.final(f"answer {n}")
        rec.flush()

    body = tc.get("/api/chat/threads/paged/transcript?limit=2").json()
    assert body["total_turns"] == 5 and body["turn_count"] == 2
    assert [t["user_text"] for t in body["turns"]] == ["turn 3", "turn 4"]
    older = tc.get("/api/chat/threads/paged/transcript?limit=2&offset=2").json()
    assert [t["user_text"] for t in older["turns"]] == ["turn 1", "turn 2"]


def test_chat_endpoint_survives_prompts_longer_than_thread_preview(
        client, monkeypatch, tmp_path):
    """Pasting a job description (>2000 chars) must not 500 the turn: the
    thread metadata keeps a truncated preview while the model gets it all."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    monkeypatch.setattr(mod, "_validated_model", lambda model: model)
    seen = {}

    class _Core:
        async def run_turn(self, conversation_id, text):
            seen["text"] = text
            return "got it"

    monkeypatch.setattr(mod, "_get_core", lambda model: _Core())
    long_text = "job description " * 250            # ~4000 chars
    r = tc.post("/api/chat", json={
        "text": long_text, "conversation_id": "c-long", "model": "chat"})
    assert r.status_code == 200 and r.json()["reply"] == "got it"
    assert seen["text"] == long_text                # model saw the full paste
    threads = tc.get("/api/chat/threads").json()["threads"]
    assert threads[0]["conversation_id"] == "c-long"
    assert len(threads[0]["last_prompt"]) <= 2000   # preview, not a 500


def test_job_search_profile_controls_surface_question_policy(client):
    _, tc = client
    body = tc.get("/api/job-search/profile-controls").json()
    assert body["writable"] is False
    assert body["application_questions"]["default_policy"] == "draft_or_route_manual"
    assert body["job_search"]["max_suggested_jobs_per_day"] >= 1
    assert body["job_search_settings_source"].endswith("profile\\search_settings.yml") or \
        body["job_search_settings_source"].endswith("profile/search_settings.yml")
    assert "work_authorization" in body["application_questions"]["review_required"]
    assert "application_question_policy" in body["source_paths"]
    assert "search_settings" in body["source_paths"]


def test_board_registry_endpoint_lists_configured_boards(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    body = tc.get("/api/board-registry").json()
    ids = {board["board_id"] for board in body["boards"]}
    assert "job_search_pipeline_internal" in ids
    assert body["config_path"].endswith("kanban_boards.yaml")
    job_board = next(board for board in body["boards"]
                     if board["board_id"] == "job_search_pipeline_internal")
    assert "approve_card" in job_board["forbidden_agent_verbs"]


def test_domain_schema_reports_disabled_write_gate(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", ROOT / "configs")
    body = tc.get("/api/domain-schema").json()
    assert body["schema_version"] == "command-center.domain-surfaces.v1"
    assert body["writable"] is False
    assert "not enabled" in body["write_gate"]
    assert any(domain["domain_id"] == "job_application" for domain in body["domains"])


def test_domain_schema_update_writes_validated_config(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = tmp_path / "configs"
    configs.mkdir()
    source = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    (configs / "domain_surfaces.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)

    domain = next(row for row in source["domains"] if row["domain_id"] == "linkedin_post")
    domain = json.loads(json.dumps(domain))
    domain["title"] = "Content"
    domain["columns"] = [*domain["columns"], "Review"]
    r = tc.put("/api/domain-schema/linkedin_post", json=domain)
    assert r.status_code == 200, r.json()
    body = r.json()
    updated = next(row for row in body["domains"] if row["domain_id"] == "linkedin_post")
    assert updated["title"] == "Content"
    assert "Review" in updated["columns"]

    saved = yaml.safe_load((configs / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    assert next(row for row in saved["domains"]
                if row["domain_id"] == "linkedin_post")["title"] == "Content"


def test_domain_schema_create_and_delete_board(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = tmp_path / "configs"
    configs.mkdir()
    raw = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    (configs / "domain_surfaces.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)

    new_domain = {
        "domain_id": "test_board",
        "title": "Test Board",
        "card_component": "generic_task",
        "source": "fixtures",
        "columns": ["Backlog", "Done"],
        "summary_fields": [{"name": "title", "label": "Title", "kind": "text"}],
        "drawer_fields": [{"name": "notes", "label": "Notes", "kind": "markdown"}],
        "allowed_actions": ["stage_card", "finish_todo"],
        "empty_state": {"title": "No cards", "hint": "Nothing queued."},
    }
    created = tc.post("/api/domain-schema", json=new_domain)
    assert created.status_code == 200, created.json()
    assert any(row["domain_id"] == "test_board" for row in created.json()["domains"])

    deleted = tc.delete("/api/domain-schema/test_board")
    assert deleted.status_code == 200, deleted.json()
    assert all(row["domain_id"] != "test_board" for row in deleted.json()["domains"])


def test_domain_schema_rejects_wall_verbs(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = tmp_path / "configs"
    configs.mkdir()
    raw = yaml.safe_load(
        (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8"))
    (configs / "domain_surfaces.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)

    bad_domain = {
        "domain_id": "bad_board",
        "title": "Bad Board",
        "card_component": "generic_task",
        "source": "fixtures",
        "columns": ["Backlog"],
        "summary_fields": [{"name": "title", "label": "Title", "kind": "text"}],
        "drawer_fields": [{"name": "notes", "label": "Notes", "kind": "markdown"}],
        "allowed_actions": ["delete_card"],
        "empty_state": {"title": "No cards", "hint": "Nothing queued."},
    }
    r = tc.post("/api/domain-schema", json=bad_domain)
    assert r.status_code == 400
    assert "wall verb" in r.json()["detail"]


def test_job_search_runtime_settings_write_profile_override(client, monkeypatch, tmp_path):
    mod, tc = client
    from command_center.job_search.config import load_config

    raw = json.loads(json.dumps(
        yaml.safe_load((ROOT / "configs" / "job_search.yaml").read_text(encoding="utf-8"))))
    data_root = tmp_path / "data"
    raw["job_search"]["data_root"] = str(data_root)
    configs = tmp_path / "configs"
    configs.mkdir()
    cfg_path = configs / "job_search.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (data_root / "profile").mkdir(parents=True)

    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "_job_search_config_and_root",
                        lambda: (load_config(cfg_path), data_root))
    r = tc.put("/api/job-search/profile-controls/runtime", json={
        "max_suggested_jobs_per_day": 40,
        "max_bot_possible_suggestions_per_day": 15,
        "max_manual_required_suggestions_per_day": 25,
        "max_selected_jobs_per_day": 10,
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["job_search"]["max_suggested_jobs_per_day"] == 40
    settings = yaml.safe_load(
        (data_root / "profile" / "search_settings.yml").read_text(encoding="utf-8"))
    assert settings["job_search"]["max_selected_jobs_per_day"] == 10


def test_job_search_category_settings_write_profile_override(client, monkeypatch, tmp_path):
    mod, tc = client
    from command_center.job_search.config import load_config

    raw = yaml.safe_load(
        (ROOT / "configs" / "job_search.yaml").read_text(encoding="utf-8"))
    data_root = tmp_path / "data"
    raw["job_search"]["data_root"] = str(data_root)
    configs = tmp_path / "configs"
    configs.mkdir()
    cfg_path = configs / "job_search.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (data_root / "profile").mkdir(parents=True)

    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "_job_search_config_and_root",
                        lambda: (load_config(cfg_path), data_root))
    r = tc.put("/api/job-search/profile-controls/category/analytics_engineer", json={
        "role_focus": "primary",
        "keywords": ["data engineer", "analytics engineer", "dbt"],
    })
    assert r.status_code == 200, r.json()
    category = next(c for c in r.json()["job_categories"] if c["id"] == "analytics_engineer")
    assert category["role_focus"] == "primary"
    assert category["keywords"] == ["data engineer", "analytics engineer", "dbt"]


def test_profile_writes_refused_with_chat_alone(client, monkeypatch):
    """Chat-enabled is NOT enough for profile YAML writes — the deployment must
    opt into config writes (same discipline as the domain-config editor)."""
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", False)
    for path, payload in (
        ("/api/job-search/profile-controls/runtime",
         {"max_suggested_jobs_per_day": 40}),
        ("/api/job-search/profile-controls/category/analytics_engineer",
         {"role_focus": "primary"}),
        ("/api/job-search/profile-controls/draft-default",
         {"key": "work_authorization", "value": "yes"}),
    ):
        r = tc.put(path, json=payload)
        assert r.status_code == 503, (path, r.json())
        assert "KANBAN_UI_DOMAIN_CONFIG_WRITES" in r.json()["detail"]


def test_status_probes_report_ok_and_error(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: _Resp({}))
    body = tc.get("/api/status").json()
    assert body["hops"]["ledger"] == "ok"
    assert body["targets"]["ledger"].endswith("/health")

    def boom(*a, **k):
        raise mod.httpx.ConnectError("refused")
    monkeypatch.setattr(mod.httpx, "get", boom)
    assert tc.get("/api/status").json()["hops"]["ledger"].startswith("error")


def test_runtime_debug_reports_urls_and_paths(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "LEDGER_BASE_URL", "http://ledger:8090")
    monkeypatch.setattr(mod, "_dns_probe", lambda url: {"ok": False, "host": "ledger",
                                                        "error": "not found"})
    monkeypatch.setattr(mod, "_http_probe", lambda url: {"ok": False, "url": url,
                                                         "error_type": "ConnectError",
                                                         "error": "refused"})
    monkeypatch.setattr(mod, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", tmp_path / "missing-snapshot.json")
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    body = tc.get("/api/debug/runtime").json()
    assert body["ledger"]["base_url"] == "http://ledger:8090"
    assert body["ledger"]["health_url"] == "http://ledger:8090/health"
    assert body["paths"]["board_snapshot"]["exists"] is False
    assert "writable" in body["paths"]["kanban_event_log"]
    assert "parent_writable" in body["paths"]["board_store_dir"]
    assert "127.0.0.1:8091" in body["ledger"]["host_run_hint"]


def test_relative_config_path_survives_runtime_cwd_change(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("KANBAN_UI_CONFIGS", "configs")
    spec = importlib.util.spec_from_file_location("agent_kanban_ui_path_test", APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_kanban_ui_path_test"] = mod
    spec.loader.exec_module(mod)
    assert mod.CONFIGS_DIR == (ROOT / "configs").resolve()

    monkeypatch.chdir(tmp_path)
    tc = TestClient(mod.app)
    models = tc.get("/api/models")
    domains = tc.get("/api/domains")
    debug = tc.get("/api/debug/runtime").json()

    assert models.status_code == 200, models.json()
    assert domains.status_code == 200, domains.json()
    assert debug["mode"]["cwd"] == str(tmp_path)
    assert debug["mode"]["startup_cwd"] == str(ROOT)
    assert debug["paths"]["configs_dir"]["path"] == str((ROOT / "configs").resolve())


def test_chat_and_writes_disabled_by_default_are_503(client):
    _, tc = client
    assert tc.post("/api/chat", json={"text": "hi"}).status_code == 503
    assert tc.post("/api/action", json={"action": "stage_card",
                                        "params": {}}).status_code == 503


def test_action_rejects_non_governed_verb(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    r = tc.post("/api/action", json={"action": "delete_everything", "params": {}})
    assert r.status_code == 400 and "not allowed" in r.json()["detail"]


def test_action_never_allows_approve(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    # there is simply no 'approve' verb in the governed set — the wall holds here too
    assert "approve" not in mod.ACTION_VERBS
    assert {"annotate_item", "set_item_field",
            "remove_item_field_value"} <= mod.ACTION_VERBS
    assert tc.post("/api/action", json={"action": "approve_card",
                                        "params": {}}).status_code == 400


def test_chat_validates_model_against_configs(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    (tmp_path / "models.yaml").write_text(
        "schema_version: '1'\nroles:\n  chat:\n    - alias: chat\n      provider: ollama\n"
        "      model: qwen3:30b\n      priority: 1\n      local: true\n")
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    r = tc.post("/api/chat", json={"text": "hi", "model": "no-such-role"})
    assert r.status_code == 400 and "unknown model role" in r.json()["detail"]


def test_boards_served_from_worker_snapshot(client, monkeypatch, tmp_path):
    mod, tc = client
    snap = tmp_path / "board-snapshot.json"
    snap.write_text('{"generated_at": "2026-06-13T00:00:00Z", '
                    '"boards": [{"board": "todos", "columns": []}]}')
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", snap)
    body = tc.get("/api/boards").json()
    assert body["boards"][0]["board"] == "todos"


def test_boards_missing_snapshot_is_503_with_path(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "BOARD_SNAPSHOT", tmp_path / "absent.json")
    r = tc.get("/api/boards")
    assert r.status_code == 503 and "snapshot not found" in r.json()["detail"]


def test_models_router_reads_configs_data_derived(client, monkeypatch, tmp_path):
    mod, tc = client
    (tmp_path / "models.yaml").write_text(
        "schema_version: '1'\nroles:\n  triage:\n    - alias: triage\n"
        "      provider: ollama\n      model: qwen3:30b\n      priority: 1\n"
        "      local: true\n")
    (tmp_path / "judges.yaml").write_text(
        "schema_version: '1'\nstages:\n  - stage: implement\n    judges:\n"
        "      - name: diff\n        role_alias: local-judge\n")
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)
    body = tc.get("/api/models").json()
    assert body["roles"][0]["role"] == "triage"
    assert body["roles"][0]["candidates"][0]["model"] == "qwen3:30b"
    assert body["judge_stages"][0]["stage"] == "implement"


def test_models_missing_config_is_503(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", tmp_path)   # empty dir, no models.yaml
    assert tc.get("/api/models").status_code == 503


def test_activity_feed_returns_recent_calls_newest_first(client, monkeypatch):
    mod, tc = client
    calls = [
        {"ts": "2026-01-01T00:00:01", "surface": "discord", "tool": "list_cards",
         "ok": True, "ms": 5.0, "detail": ""},
        {"ts": "2026-01-01T00:00:02", "surface": "mcp", "tool": "stage_card",
         "ok": False, "ms": 9.0, "detail": "boom"},
    ]
    monkeypatch.setattr(mod, "recent_calls", lambda limit=25: calls)
    out = tc.get("/api/activity").json()["calls"]
    assert out[0]["tool"] == "stage_card" and out[0]["ok"] is False   # newest first
    assert out[1]["tool"] == "list_cards"


def test_chat_prompt_for_card_is_domain_aware_not_job_shaped(client):
    """A non-job domain (repo) must render ITS OWN fields with real values,
    never the job_application-shaped fields (fit_score/apply_url/materials_path)
    printing as 'None' on an unrelated card."""
    mod, _ = client
    repo_spec = next(
        d for d in yaml.safe_load(
            (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8")
        )["domains"] if d["domain_id"] == "repo")
    card = {
        "card_id": "repo-1", "status": "Using", "repo_id": "cool-repo",
        "language": "Python", "why": "does something useful",
        "url": "https://github.com/x/cool-repo",
    }
    prompt = mod._chat_prompt_for_card(repo_spec, card, [], [], {})
    assert "fit_score" not in prompt
    assert "materials_path" not in prompt
    assert "apply_url" not in prompt
    assert "Repo: cool-repo" in prompt
    assert "Why it matters: does something useful" in prompt
    assert "APPLICATION MEMORY" not in prompt


def test_chat_prompt_for_card_job_application_keeps_application_memory(client):
    mod, _ = client
    job_spec = next(
        d for d in yaml.safe_load(
            (ROOT / "configs" / "domain_surfaces.yaml").read_text(encoding="utf-8")
        )["domains"] if d["domain_id"] == "job_application")
    card = {"card_id": "job-1", "status": "In Progress", "company": "Acme",
            "role_title": "Engineer", "fit_score": 8, "apply_url": "https://x"}
    application = {"exists": True, "application_id": "job-1", "status": "drafted"}
    prompt = mod._chat_prompt_for_card(job_spec, card, [], [], application)
    assert "APPLICATION MEMORY" in prompt
    assert "Do not claim an application was submitted" in prompt
    assert "Company: Acme" in prompt


def _real_autonomy_configs(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in ("autonomy.yaml", "kanban_boards.yaml"):
        (configs / name).write_text(
            (ROOT / "configs" / name).read_text(encoding="utf-8"), encoding="utf-8")
    return configs


def test_repo_chat_context_endpoint(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", _real_autonomy_configs(tmp_path))
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod.httpx, "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger down")))

    assert tc.get("/api/chat/repo-context/no-such-repo").status_code == 404

    r = tc.get("/api/chat/repo-context/llm_station")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["manifest"]["repo_id"] == "llm_station"
    assert body["verify"]["status"] in ("pass", "blocked")
    assert body["recent_missions"] and "unavailable" in body["recent_missions"][0]
    assert "repo_id: llm_station" in body["chat_prompt"]
    assert "autonomy_gate_status" in body["chat_prompt"]


def test_repo_chat_context_stays_behind_the_chat_wall(client):
    _, tc = client
    assert tc.get("/api/chat/repo-context/llm_station").status_code == 503


def test_register_repo_dry_run_never_writes(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = _real_autonomy_configs(tmp_path)
    before = (configs / "autonomy.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)   # DOMAIN_CONFIG_WRITES left False

    r = tc.post("/api/repos/register", json={
        "repo_id": "totally-new-test-repo", "local_path": "/tmp/wherever",
        "remote_url": "https://github.com/x/totally-new-test-repo",
        "kanban_board": "llm_station_command_center", "apply": False,
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["status"] == "validated_dry_run"
    assert "manifest_block" in body
    # hyphenated repo ids (a common real-world naming convention) must still
    # produce a valid POSIX env var name — .env/shell cannot use hyphens
    assert body["local_path_env"] == "TOTALLY_NEW_TEST_REPO_LOCAL_PATH"
    assert (configs / "autonomy.yaml").read_text(encoding="utf-8") == before   # no write

    already = tc.post("/api/repos/register", json={
        "repo_id": "llm_station", "local_path": "/tmp/x", "remote_url": "https://x",
        "kanban_board": "llm_station_command_center", "apply": False,
    })
    assert already.json()["status"] == "blocked"
    assert "repo_id_already_registered_llm_station" in already.json()["blockers"]


def test_register_repo_apply_requires_write_gate(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = _real_autonomy_configs(tmp_path)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", False)
    r = tc.post("/api/repos/register", json={
        "repo_id": "totally-new-test-repo", "local_path": "/tmp/wherever",
        "remote_url": "https://github.com/x/totally-new-test-repo",
        "kanban_board": "llm_station_command_center", "apply": True,
    })
    assert r.status_code == 503
    assert "KANBAN_UI_DOMAIN_CONFIG_WRITES" in r.json()["detail"]


def test_register_repo_apply_writes_disabled_manifest(client, monkeypatch, tmp_path):
    mod, tc = client
    configs = _real_autonomy_configs(tmp_path)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    r = tc.post("/api/repos/register", json={
        "repo_id": "totally-new-test-repo", "local_path": "/tmp/wherever",
        "remote_url": "https://github.com/x/totally-new-test-repo",
        "kanban_board": "llm_station_command_center", "apply": True,
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["status"] == "registered"
    saved = yaml.safe_load((configs / "autonomy.yaml").read_text(encoding="utf-8"))
    manifest = next(
        m for m in saved["repo_manifests"] if m["repo_id"] == "totally-new-test-repo")
    assert manifest["autonomous_edits_enabled"] is False
    assert manifest["blockers"] == ["repo_autonomy_not_yet_verified"]


def _job_search_test_root(tmp_path, monkeypatch, mod):
    """Point the app's job-search config + data root at a tmp copy so settings
    writes and rejection reads never touch the real data/job_search."""
    import yaml
    from command_center.job_search.config import load_config

    raw = yaml.safe_load(
        (ROOT / "configs" / "job_search.yaml").read_text(encoding="utf-8"))
    data_root = tmp_path / "data"
    raw["job_search"]["data_root"] = str(data_root)
    configs = tmp_path / "configs"
    configs.mkdir()
    cfg_path = configs / "job_search.yaml"
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    (data_root / "profile").mkdir(parents=True)
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "DOMAIN_CONFIG_WRITES", True)
    monkeypatch.setattr(mod, "CONFIGS_DIR", configs)
    monkeypatch.setattr(mod, "_job_search_config_and_root",
                        lambda: (load_config(cfg_path), data_root))
    return data_root, cfg_path


def test_job_search_locations_settings_write_profile_override(
        client, monkeypatch, tmp_path):
    import yaml
    mod, tc = client
    data_root, _ = _job_search_test_root(tmp_path, monkeypatch, mod)
    r = tc.put("/api/job-search/profile-controls/locations", json={
        "mode": "regions", "regions": ["Texas", "Seattle"],
        "remote_types_allowed": ["remote", "hybrid"],
        "employment_types_allowed": [],
    })
    assert r.status_code == 200, r.json()
    loc = r.json()["locations"]
    assert loc["regions"] == ["Texas", "Seattle"]
    assert loc["remote_types_allowed"] == ["remote", "hybrid"]
    # untouched fields survive the shallow section update
    assert loc["countries"] == ["United States"]
    settings = yaml.safe_load(
        (data_root / "profile" / "search_settings.yml").read_text(encoding="utf-8"))
    assert settings["locations"]["regions"] == ["Texas", "Seattle"]


def test_job_search_locations_invalid_combo_is_rejected(
        client, monkeypatch, tmp_path):
    mod, tc = client
    _job_search_test_root(tmp_path, monkeypatch, mod)
    # regions mode with no regions AND no countries must fail validation
    r = tc.put("/api/job-search/profile-controls/locations", json={
        "mode": "regions", "regions": [], "countries": [],
    })
    assert r.status_code == 400, r.json()


def test_job_search_languages_settings_write_profile_override(
        client, monkeypatch, tmp_path):
    mod, tc = client
    _job_search_test_root(tmp_path, monkeypatch, mod)
    r = tc.put("/api/job-search/profile-controls/languages", json={
        "spoken": ["English", "Spanish"]})
    assert r.status_code == 200, r.json()
    assert r.json()["languages"]["spoken"] == ["English", "Spanish"]


def test_prep_status_endpoint_reports_idle_queue(client):
    _, tc = client
    body = tc.get("/api/job-search/prep-status").json()
    assert body["operation"] == "prep_status"
    assert body["running"] is False
    assert "runs_completed" in body


def test_rejections_report_endpoint(client, monkeypatch, tmp_path):
    mod, tc = client
    data_root, _ = _job_search_test_root(tmp_path, monkeypatch, mod)
    from command_center.job_search.rejections import record_rejection
    record_rejection(data_root, job_key="a", reason_code="salary")
    body = tc.get("/api/job-search/rejections-report").json()
    assert body["total_rejections"] == 1
    assert body["counts_by_reason"].get("salary") == 1

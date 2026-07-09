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


def test_chat_runtime_reports_gateway_not_external_harness(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", Path(__file__).resolve().parents[1] / "configs")
    monkeypatch.delenv("ORCA_CHAT_URL", raising=False)
    monkeypatch.delenv("OMNIGENT_CHAT_URL", raising=False)
    monkeypatch.delenv("OMNIAGENT_CHAT_URL", raising=False)
    monkeypatch.delenv("OXYGENT_CHAT_URL", raising=False)
    body = tc.get("/api/chat/runtime").json()
    assert body["harness"] == "GatewayCore"
    assert body["model_gateway"] == "LiteLLM"
    assert body["uses_orca"] is False
    assert body["uses_omnigent"] is False
    assert body["uses_oxygent"] is False
    assert body["stream_endpoint"] == "/api/chat/stream"
    assert "GatewayCore + LiteLLM remains" in body["specialist_recommendation"]
    external = {chat["name"]: chat for chat in body["external_chats"]}
    assert external["ORCA"]["kind"] == "document visual QA specialist"
    assert "PDFs" in external["ORCA"]["best_for"]
    assert external["OmniAgent / Omnigent"]["source_url"].endswith("2606.19341")
    assert external["OxyGent"]["env_var"] == "OXYGENT_CHAT_URL"


def test_chat_runtime_marks_configured_specialist_links_active(client, monkeypatch):
    mod, tc = client
    monkeypatch.setattr(mod, "CONFIGS_DIR", Path(__file__).resolve().parents[1] / "configs")
    monkeypatch.setenv("ORCA_CHAT_URL", "http://orca.local/chat")
    monkeypatch.setenv("OMNIAGENT_CHAT_URL", "http://omniagent.local/chat")
    monkeypatch.setenv("OXYGENT_CHAT_URL", "http://oxygent.local/chat")
    body = tc.get("/api/chat/runtime").json()
    assert body["uses_orca"] is True
    assert body["uses_omnigent"] is True
    assert body["uses_oxygent"] is True
    external = {chat["name"]: chat for chat in body["external_chats"]}
    assert external["ORCA"]["url"] == "http://orca.local/chat"
    assert external["OmniAgent / Omnigent"]["env_var"] == "OMNIAGENT_CHAT_URL"
    assert external["OxyGent"]["handoff_mode"] == "external_link"


def test_chat_threads_store_shared_metadata(client, monkeypatch, tmp_path):
    mod, tc = client
    monkeypatch.setattr(mod, "CHAT_ENABLED", True)
    monkeypatch.setattr(mod, "CHAT_THREADS_FILE", tmp_path / "chat-threads.json")
    body = tc.get("/api/chat/threads").json()
    assert body["threads"] == []
    assert body["storage"] == "server_metadata_only"

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

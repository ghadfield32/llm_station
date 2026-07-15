from pathlib import Path


def test_init_env_generates_agent_worker_token(monkeypatch, tmp_path: Path):
    from command_center.cli import init_env

    template = tmp_path / ".env.example"
    destination = tmp_path / ".env"
    template.write_text(
        "LITELLM_MASTER_KEY=\n"
        "POSTGRES_PASSWORD=\n"
        "LEDGER_APPROVAL_SECRET=\n"
        "AGENT_WORKER_TOKEN=\n"
        "KANBAN_UI_AGENT_SESSIONS_ENABLED=1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(init_env, "TEMPLATE", template)
    monkeypatch.setattr(init_env, "DEST", destination)

    assert init_env.main() == 0
    values = dict(
        line.split("=", 1)
        for line in destination.read_text(encoding="utf-8").splitlines()
    )
    assert len(values["AGENT_WORKER_TOKEN"]) >= 48
    assert values["KANBAN_UI_AGENT_SESSIONS_ENABLED"] == "1"

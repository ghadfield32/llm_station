from __future__ import annotations

import json

from command_center.cli import doctor
from command_center.cli.main import COMMANDS


def test_phase_one_commands_are_registered():
    assert "doctor" in COMMANDS
    assert "bootstrap-local" in COMMANDS
    assert "verify-stack" in COMMANDS


def test_github_env_ref_check_reports_presence_without_values(monkeypatch):
    secret_path = r"C:\Users\example\outside-repo\llm-station.pem"
    monkeypatch.setenv("GITHUB_APP_ID", "123456")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv1.secret-client")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", secret_path)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    config_check = doctor.check_config_contracts()
    result = doctor.check_github_env_refs(config_check)
    payload = json.dumps(result.as_dict(), sort_keys=True)

    assert result.status == "PASS"
    assert "Iv1.secret-client" not in payload
    assert secret_path not in payload
    required = result.evidence["required"]
    assert {item["name"] for item in required} == {
        "GITHUB_APP_ID",
        "GITHUB_CLIENT_ID",
        "GITHUB_APP_PRIVATE_KEY_PATH",
    }
    assert all("length" in item for item in required)


def test_doctor_report_safety_flags_do_not_claim_external_writes():
    checks = [
        doctor.Check("local", "Local", "PASS"),
        doctor.Check("external", "External", "BLOCKED", blocker="missing service"),
    ]

    report = doctor._report(checks)

    assert report["summary"]["status"] == "BLOCKED"
    assert report["safety"]["external_writes_performed"] is False
    assert report["safety"]["repo_source_writes_performed"] is False


def test_committed_config_secret_scan_allows_env_refs_not_literals():
    result = doctor.check_committed_config_secret_scan()

    assert result.status == "PASS"
    assert result.evidence["findings"] == []

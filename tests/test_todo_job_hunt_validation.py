"""Hermetic tests for the read-only deployed Todos/job-hunt validator."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_todo_job_hunt.py"
)
SPEC = importlib.util.spec_from_file_location("validate_todo_job_hunt_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)

BASE = "http://127.0.0.1:8787"
ASSET = "/assets/index-reviewed.js"


def _openapi() -> dict:
    return {
        "components": {
            "schemas": {
                "JobSearchRetentionSettingsIn": {
                    "properties": {
                        "rich_application_cache_days": {
                            "type": "integer", "minimum": 1, "maximum": 365,
                        }
                    }
                }
            }
        },
        "paths": {
            "/api/job-search/cards/{card_id}/outreach": {"get": {}},
            "/api/job-search/profile-controls/company-targets": {"put": {}},
            "/api/job-search/profile-controls/retention": {"put": {}},
            "/api/job-search/question-library": {"get": {}, "post": {}},
            "/api/job-search/relationships": {"get": {}},
        },
    }


def _payloads() -> dict[str, object]:
    captures = [
        {
            "capture_id": row.capture_id,
            "processing_status": "routed",
            "preview": row.source_text[:160],
        }
        for row in validator.REQUIRED_WORKFLOWS
    ]
    payloads: dict[str, object] = {
        "/api/health": {"status": "ok"},
        "/api/config": {"chat_enabled": True},
        "/api/domain-schema": {
            "writable": True,
            "write_gate": "enabled",
            "domains": [{
                "domain_id": "generic_task",
                "title": "General Todos",
                "board_id": "personal_todos",
                "card_component": "generic_task",
                "source": "board_store",
                "columns": [
                    "Backlog", "Ready", "In Progress", "Done", "Blocked",
                    "Rejected", "Awaiting Approval",
                ],
            }],
        },
        "/api/intake/inbox": {
            "total": 5,
            "columns": [{"name": "routed", "captures": captures}],
        },
        "/api/domain/generic_task/cards": {
            "cards": [{
                "card_id": f"card-{index}",
                "board_id": "personal_todos",
                "work_item_id": row.work_item_id,
                "projection_source": "work_graph",
                "title": row.title,
                "status": "Done",
                "canonical_status": "done",
                "capture_id": row.capture_id,
                "conversation_id": f"capture:{row.capture_id}",
            } for index, row in enumerate(validator.REQUIRED_WORKFLOWS)],
        },
        "/api/job-search/profile-controls": {
            "writable": True,
            "write_gate": "enabled",
            "company_targets": {
                "faang": ["Example One"],
                "major_other": ["Example Two"],
                "sports_tech_companies": ["Example Three"],
                "sports_teams_keywords": ["Example League"],
            },
            "retention": {
                "rich_application_cache_days": 30,
                "purge_rich_files": False,
            },
            "standing_answers": {"answers": []},
            "application_questions": {"never_auto_answer": ["eeo"]},
        },
        "/api/job-search/relationships": {"relationships": []},
        "/api/job-search/question-library": {"questions": []},
        "/openapi.json": _openapi(),
        "/": f'<html><script type="module" src="{ASSET}"></script></html>',
        ASSET: "\n".join(validator.UI_MARKERS),
    }
    for row in validator.REQUIRED_WORKFLOWS:
        payloads[f"/api/captures/{row.capture_id}"] = {
            "record": {"capture_id": row.capture_id, "raw_content": row.source_text},
            "processing_status": "routed",
        }
    return payloads


class FixtureTransport:
    def __init__(
        self,
        payloads: dict[str, object] | None = None,
        *,
        headers: dict[str, dict[str, str]] | None = None,
        final_urls: dict[str, str] | None = None,
    ) -> None:
        self.payloads = payloads or _payloads()
        self.headers = headers or {}
        self.final_urls = final_urls or {}
        self.calls: list[tuple[str, str, float, int]] = []

    def __call__(
        self, method: str, url: str, timeout: float, max_response_bytes: int,
    ) -> validator.HttpResponse:
        self.calls.append((method, url, timeout, max_response_bytes))
        path = url.removeprefix(BASE)
        value = self.payloads[path]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, bytes):
            body = value
        elif isinstance(value, str):
            body = value.encode("utf-8")
        else:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        default_headers = {"content-type": "application/json"}
        if path in {
            "/api/job-search/profile-controls",
            "/api/job-search/relationships",
            "/api/job-search/question-library",
        }:
            default_headers["cache-control"] = "no-store"
        default_headers.update(self.headers.get(path, {}))
        return validator.HttpResponse(
            status=200,
            headers=default_headers,
            body=body,
            final_url=self.final_urls.get(path, url),
        )


def _statuses(report: dict) -> dict[str, str]:
    return {check["id"]: check["status"] for check in report["checks"]}


def test_full_acceptance_contract_passes_and_transport_is_get_only():
    transport = FixtureTransport()
    report = validator.validate_deployment(
        BASE, transport=transport, expected_asset="index-reviewed.js")

    assert report["overall"] == "pass"
    assert report["summary"] == {"passed": 14, "failed": 0, "total": 14}
    assert set(_statuses(report).values()) == {"pass"}
    assert {method for method, *_ in transport.calls} == {"GET"}
    assert all(timeout == 10.0 for _, _, timeout, _ in transport.calls)
    assert all(limit == 1_048_576 for _, _, _, limit in transport.calls)


@pytest.mark.parametrize(("defect", "failed_check"), [
    ("chat_disabled", "prepare_chat_gate"),
    ("wrong_todos_title", "todos_schema"),
    ("capture_source_changed", "five_exact_capture_receipts"),
    ("card_not_done", "five_done_work_graph_cards"),
    ("company_groups_untyped", "editable_company_watchlists"),
    ("retention_bound_weakened", "retention_1_to_365_contract"),
    ("outreach_became_writable", "job_hunt_api_contract"),
    ("ui_control_missing", "shipped_ui_markers"),
])
def test_independent_contract_defects_fail_the_expected_check(defect, failed_check):
    payloads = copy.deepcopy(_payloads())
    if defect == "chat_disabled":
        payloads["/api/config"]["chat_enabled"] = False
    elif defect == "wrong_todos_title":
        payloads["/api/domain-schema"]["domains"][0]["title"] = "Tasks"
    elif defect == "capture_source_changed":
        first = validator.REQUIRED_WORKFLOWS[0]
        payloads[f"/api/captures/{first.capture_id}"]["record"]["raw_content"] = "changed"
    elif defect == "card_not_done":
        payloads["/api/domain/generic_task/cards"]["cards"][0]["status"] = "In Progress"
    elif defect == "company_groups_untyped":
        payloads["/api/job-search/profile-controls"]["company_targets"] = {}
    elif defect == "retention_bound_weakened":
        payloads["/openapi.json"]["components"]["schemas"][
            "JobSearchRetentionSettingsIn"
        ]["properties"]["rich_application_cache_days"]["maximum"] = 366
    elif defect == "outreach_became_writable":
        payloads["/openapi.json"]["paths"][
            "/api/job-search/cards/{card_id}/outreach"
        ]["post"] = {}
    elif defect == "ui_control_missing":
        payloads[ASSET] = str(payloads[ASSET]).replace(validator.UI_MARKERS[0], "")

    report = validator.validate_deployment(BASE, transport=FixtureTransport(payloads))
    assert report["overall"] == "fail"
    failed = {
        check_id for check_id, status in _statuses(report).items()
        if status == "fail"
    }
    assert failed == {failed_check}


def test_private_payloads_and_transport_errors_never_enter_serialized_report():
    secret = "PRIVATE-JOB-SEARCH-SENTINEL"
    payloads = _payloads()
    payloads["/api/job-search/profile-controls"]["standing_answers"] = {
        "answers": [{"question": secret, "answer": secret}],
    }
    payloads["/api/job-search/relationships"] = {
        "relationships": [{"name": secret, "notes": secret}],
    }
    payloads["/api/job-search/question-library"] = {
        "questions": [{"question": secret, "candidate_answers": [secret]}],
    }
    report = validator.validate_deployment(BASE, transport=FixtureTransport(payloads))
    serialized = json.dumps(report, ensure_ascii=False)
    assert report["overall"] == "pass"
    assert secret not in serialized
    assert all(row.source_text not in serialized for row in validator.REQUIRED_WORKFLOWS)

    payloads["/api/job-search/profile-controls"] = RuntimeError(secret)
    failed = validator.validate_deployment(BASE, transport=FixtureTransport(payloads))
    assert failed["overall"] == "fail"
    assert secret not in json.dumps(failed)
    assert _statuses(failed)["private_no_store"] == "fail"

    payloads = _payloads()
    payloads["/api/config"] = validator.SafeValidationError(secret)
    unsafe_internal = validator.validate_deployment(
        BASE, transport=FixtureTransport(payloads))
    assert secret not in json.dumps(unsafe_internal)
    prepare = next(
        check for check in unsafe_internal["checks"]
        if check["id"] == "prepare_chat_gate")
    assert prepare["detail"] == "validation_failed"


def test_malformed_and_oversized_responses_fail_safely_without_body_echo():
    payloads = _payloads()
    payloads["/api/config"] = b'{"PRIVATE-BODY":'
    malformed = validator.validate_deployment(BASE, transport=FixtureTransport(payloads))
    prepare = next(c for c in malformed["checks"] if c["id"] == "prepare_chat_gate")
    assert prepare == {"id": "prepare_chat_gate", "status": "fail", "detail": "invalid_json"}
    assert "PRIVATE-BODY" not in json.dumps(malformed)

    payloads = _payloads()
    payloads[ASSET] = b"x" * 257
    oversized = validator.validate_deployment(
        BASE, transport=FixtureTransport(payloads), max_response_bytes=256)
    shipped = next(c for c in oversized["checks"] if c["id"] == "shipped_ui_markers")
    assert shipped["status"] == "fail"
    assert shipped["detail"] == "response_too_large"


def test_cross_origin_asset_and_redirect_are_refused_before_private_reads_escape():
    payloads = _payloads()
    payloads["/"] = '<script src="https://example.invalid/asset.js"></script>'
    transport = FixtureTransport(payloads)
    report = validator.validate_deployment(BASE, transport=transport)
    assert _statuses(report)["shipped_ui_markers"] == "fail"
    assert all("example.invalid" not in url for _, url, _, _ in transport.calls)

    redirecting = FixtureTransport(
        _payloads(), final_urls={"/api/config": "https://example.invalid/api/config"})
    report = validator.validate_deployment(BASE, transport=redirecting)
    assert _statuses(report)["prepare_chat_gate"] == "fail"
    assert "cross_origin_redirect_refused" in json.dumps(report)


def test_non_loopback_target_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="--allow-remote"):
        validator.validate_deployment("https://cockpit.example", transport=FixtureTransport())


def test_expected_asset_filename_detects_a_different_build():
    report = validator.validate_deployment(
        BASE, transport=FixtureTransport(), expected_asset="index-other.js")
    assert report["overall"] == "fail"
    assert _statuses(report)["reviewed_asset_filename"] == "fail"

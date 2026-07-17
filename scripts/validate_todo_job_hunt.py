#!/usr/bin/env python3
"""Read-only acceptance validation for the deployed General Todos/job-hunt workflow.

The validator performs only bounded, same-origin GET requests. It deliberately
does not print capture bodies, company names, relationship data, questions, or
standing answers. Its report contains contract check names and non-private
counts/identifiers only.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

SCHEMA_VERSION = "command-center.todo-job-hunt-validation.v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576


@dataclass(frozen=True)
class RequiredWorkflow:
    capture_id: str
    work_item_id: str
    title: str
    source_text: str


REQUIRED_WORKFLOWS = (
    RequiredWorkflow(
        capture_id="cap-8ec756f690",
        work_item_id="W-0465b5e0a5",
        title="Build a page-by-page job application companion",
        source_text=(
            "Make kanban job hunt have a go through application with you setup "
            "so you can work through it one by one page by page together if wanted."
        ),
    ),
    RequiredWorkflow(
        capture_id="cap-971b8b8b51",
        work_item_id="W-c823e5d303",
        title="Add LinkedIn known-contact follow-ups and connection suggestions",
        source_text=(
            "Kanban should included the follow up messages to people we actually "
            "know on LinkedIn and recommended people to connect with on LinkedIn"
        ),
    ),
    RequiredWorkflow(
        capture_id="cap-f4c71251cf",
        work_item_id="W-47f19022f4",
        title="Add an editable company watchlist for job search",
        source_text=(
            "Have an easy company search add on so it keeps up with whatever "
            "companies you want"
        ),
    ),
    RequiredWorkflow(
        capture_id="cap-a165eef95f",
        work_item_id="W-9ffaf92253",
        title="Learn unanswered application questions by job type",
        source_text=(
            "Learns from questions we can’t answer so we can add those to our "
            "collection with typical answers for different job types"
        ),
    ),
    RequiredWorkflow(
        capture_id="cap-fe4190a887",
        work_item_id="W-9cd270a560",
        title="Add adjustable 30-day application outcome memory",
        source_text=(
            "It should keep a bare database of jobs applied to (lasting 30 days "
            "(adjustable)) ynless we mark we got a communication furthering the "
            "process."
        ),
    ),
)

EXPECTED_COMPANY_GROUPS = {
    "faang",
    "major_other",
    "sports_tech_companies",
    "sports_teams_keywords",
}
UI_MARKERS = (
    "Saved first, then a capture-scoped chat opens with General Todos, existing-kanban, "
    "and new-kanban choices.",
    "Choose an existing kanban…",
    "New kanban unavailable:",
    "work page-by-page in chat",
    "save company watchlist",
    "add known contact",
    "Search phrases only; no named people are invented or looked up.",
    "Add this non-sensitive question to library",
    "This communication furthers the process — refresh the retention window.",
)
HTTP_METHOD_KEYS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
SAFE_REASON_CODES = {
    "cards_list_required",
    "cross_origin_asset_refused",
    "cross_origin_redirect_refused",
    "cross_origin_request_refused",
    "invalid_json",
    "javascript_asset_not_found",
    "json_object_required",
    "non_get_request_refused",
    "response_too_large",
    "transport_timeout",
    "transport_unavailable",
}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


Transport = Callable[[str, str, float, int], HttpResponse]


class SafeValidationError(RuntimeError):
    """An error whose message is intentionally safe to place in a report."""


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, host, port


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _normalize_base_url(base_url: str, *, allow_remote: bool) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("base URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("base URL must not contain a path, query, or fragment")
    if not allow_remote and not _is_loopback_host(parsed.hostname):
        raise ValueError("non-loopback target requires --allow-remote")
    return value


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if _origin(req.full_url) != _origin(newurl):
            raise SafeValidationError("cross_origin_redirect_refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(
    method: str,
    url: str,
    timeout: float,
    max_response_bytes: int,
) -> HttpResponse:
    if method != "GET":
        raise SafeValidationError("non_get_request_refused")
    request = Request(
        url,
        method="GET",
        headers={"Accept": "application/json,text/html,*/*", "User-Agent": SCHEMA_VERSION},
    )
    opener = build_opener(_SameOriginRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise SafeValidationError("response_too_large")
            return HttpResponse(
                status=int(response.status),
                headers={key: value for key, value in response.headers.items()},
                body=body,
                final_url=response.geturl(),
            )
    except SafeValidationError:
        raise
    except HTTPError as exc:
        raise SafeValidationError(f"http_status_{exc.code}") from None
    except URLError:
        raise SafeValidationError("transport_unavailable") from None
    except TimeoutError:
        raise SafeValidationError("transport_timeout") from None


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    return next(
        (str(value) for key, value in headers.items() if key.lower() == wanted),
        "",
    )


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, SafeValidationError):
        reason = str(exc)
        if (
            reason in SAFE_REASON_CODES
            or re.fullmatch(r"http_status_[0-9]{3}", reason)
            or re.fullmatch(r"unexpected_[A-Za-z0-9_]+", reason)
        ):
            return reason
        return "validation_failed"
    return f"unexpected_{type(exc).__name__}"


def _json_object(response: HttpResponse) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SafeValidationError("invalid_json") from None
    if not isinstance(value, dict):
        raise SafeValidationError("json_object_required")
    return value


def _operations(path_item: Any) -> set[str]:
    if not isinstance(path_item, dict):
        return set()
    return {str(key).lower() for key in path_item if str(key).lower() in HTTP_METHOD_KEYS}


def validate_deployment(
    base_url: str = DEFAULT_BASE_URL,
    *,
    transport: Transport = urllib_transport,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allow_remote: bool = False,
    expected_asset: str | None = None,
) -> dict[str, Any]:
    base = _normalize_base_url(base_url, allow_remote=allow_remote)
    base_origin = _origin(base)
    checks: list[dict[str, str]] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "id": check_id,
            "status": "pass" if passed else "fail",
            "detail": detail,
        })

    def get(path: str) -> HttpResponse:
        url = urljoin(base + "/", path.lstrip("/"))
        if _origin(url) != base_origin:
            raise SafeValidationError("cross_origin_request_refused")
        try:
            response = transport("GET", url, timeout, max_response_bytes)
        except Exception as exc:
            raise SafeValidationError(_safe_reason(exc)) from None
        if response.status != 200:
            raise SafeValidationError(f"http_status_{response.status}")
        if len(response.body) > max_response_bytes:
            raise SafeValidationError("response_too_large")
        if _origin(response.final_url) != base_origin:
            raise SafeValidationError("cross_origin_redirect_refused")
        return response

    def get_json(path: str) -> tuple[dict[str, Any], HttpResponse]:
        response = get(path)
        return _json_object(response), response

    try:
        health, _ = get_json("/api/health")
        record("health", health.get("status") == "ok", "cockpit health is ok")
    except Exception as exc:
        record("health", False, _safe_reason(exc))

    try:
        config, _ = get_json("/api/config")
        record(
            "prepare_chat_gate",
            config.get("chat_enabled") is True,
            "chat is enabled for Prepare now",
        )
    except Exception as exc:
        record("prepare_chat_gate", False, _safe_reason(exc))

    try:
        schema, _ = get_json("/api/domain-schema")
        domains = schema.get("domains")
        todos = [
            domain
            for domain in domains if isinstance(domain, dict)
            and domain.get("domain_id") == "generic_task"
        ] if isinstance(domains, list) else []
        todos_ok = (
            len(todos) == 1
            and todos[0].get("title") == "General Todos"
            and todos[0].get("board_id") == "personal_todos"
            and todos[0].get("card_component") == "generic_task"
            and todos[0].get("source") == "board_store"
            and todos[0].get("columns") == [
                "Backlog", "Ready", "In Progress", "Done", "Blocked",
                "Rejected", "Awaiting Approval",
            ]
        )
        record("todos_schema", todos_ok, "canonical General Todos surface is present")
        record(
            "new_kanban_write_gate",
            schema.get("writable") is True and schema.get("write_gate") == "enabled",
            "new-kanban creation gate is explicitly writable",
        )
    except Exception as exc:
        reason = _safe_reason(exc)
        record("todos_schema", False, reason)
        record("new_kanban_write_gate", False, reason)

    capture_views: dict[str, dict[str, Any]] = {}
    try:
        inbox, _ = get_json("/api/intake/inbox")
        columns = inbox.get("columns")
        cards = [
            card
            for column in columns if isinstance(column, dict)
            for card in column.get("captures", []) if isinstance(card, dict)
        ] if isinstance(columns, list) else []
        inbox_ids = [str(card.get("capture_id")) for card in cards]
        inbox_ok = all(inbox_ids.count(row.capture_id) == 1 for row in REQUIRED_WORKFLOWS)
        source_ok = inbox_ok
        for row in REQUIRED_WORKFLOWS:
            view, _ = get_json(f"/api/captures/{row.capture_id}")
            capture_views[row.capture_id] = view
            record_data = view.get("record")
            source_ok = source_ok and (
                isinstance(record_data, dict)
                and record_data.get("capture_id") == row.capture_id
                and record_data.get("raw_content") == row.source_text
                and view.get("processing_status") == "routed"
            )
        record(
            "five_exact_capture_receipts",
            source_ok,
            "5 immutable source captures are present exactly once and routed",
        )
    except Exception as exc:
        record("five_exact_capture_receipts", False, _safe_reason(exc))

    try:
        board, _ = get_json("/api/domain/generic_task/cards")
        cards = board.get("cards")
        if not isinstance(cards, list):
            raise SafeValidationError("cards_list_required")
        matched: list[dict[str, Any]] = []
        valid = len(capture_views) == len(REQUIRED_WORKFLOWS)
        for row in REQUIRED_WORKFLOWS:
            matches = [
                card for card in cards
                if isinstance(card, dict) and card.get("capture_id") == row.capture_id
            ]
            valid = valid and len(matches) == 1
            if len(matches) != 1:
                continue
            card = matches[0]
            matched.append(card)
            valid = valid and (
                card.get("work_item_id") == row.work_item_id
                and card.get("title") == row.title
                and card.get("board_id") == "personal_todos"
                and card.get("projection_source") == "work_graph"
                and card.get("status") == "Done"
                and card.get("canonical_status") == "done"
                and card.get("conversation_id") == f"capture:{row.capture_id}"
            )
        valid = valid and len({card.get("work_item_id") for card in matched}) == 5
        record(
            "five_done_work_graph_cards",
            valid,
            "5 distinct capture-linked work-graph cards are Done on personal_todos",
        )
    except Exception as exc:
        record("five_done_work_graph_cards", False, _safe_reason(exc))

    try:
        controls, controls_response = get_json("/api/job-search/profile-controls")
        relationships, relationships_response = get_json("/api/job-search/relationships")
        questions, questions_response = get_json("/api/job-search/question-library")
        company_targets = controls.get("company_targets")
        retention = controls.get("retention")
        company_ok = (
            controls.get("writable") is True
            and controls.get("write_gate") == "enabled"
            and isinstance(company_targets, dict)
            and set(company_targets) == EXPECTED_COMPANY_GROUPS
            and all(isinstance(value, list) for value in company_targets.values())
        )
        memory_ok = (
            isinstance(relationships.get("relationships"), list)
            and isinstance(questions.get("questions"), list)
            and isinstance(controls.get("standing_answers"), dict)
            and isinstance(controls.get("application_questions"), dict)
        )
        retention_ok = (
            isinstance(retention, dict)
            and isinstance(retention.get("rich_application_cache_days"), int)
            and 1 <= retention["rich_application_cache_days"] <= 365
            and retention.get("purge_rich_files") is False
        )
        private_no_store = all(
            "no-store" in _header(response.headers, "cache-control").lower()
            for response in (
                controls_response, relationships_response, questions_response,
            )
        )
        record("editable_company_watchlists", company_ok, "typed company groups are editable")
        record("private_question_and_contact_memory", memory_ok, "private memory APIs are available")
        record("current_retention_posture", retention_ok, "current retention is bounded and deletion-disabled")
        record("private_no_store", private_no_store, "private GET responses forbid caching")
        # Drop references to private response bodies before continuing/reporting.
        del controls, relationships, questions
    except Exception as exc:
        reason = _safe_reason(exc)
        record("editable_company_watchlists", False, reason)
        record("private_question_and_contact_memory", False, reason)
        record("current_retention_posture", False, reason)
        record("private_no_store", False, reason)

    try:
        openapi, _ = get_json("/openapi.json")
        schemas = openapi.get("components", {}).get("schemas", {})
        retention_property = (
            schemas.get("JobSearchRetentionSettingsIn", {})
            .get("properties", {})
            .get("rich_application_cache_days", {})
        )
        bounds_ok = (
            retention_property.get("minimum") == 1
            and retention_property.get("maximum") == 365
        )
        paths = openapi.get("paths", {})
        api_ok = isinstance(paths, dict) and (
            _operations(paths.get("/api/job-search/cards/{card_id}/outreach")) == {"get"}
            and _operations(paths.get("/api/job-search/profile-controls/company-targets")) == {"put"}
            and _operations(paths.get("/api/job-search/profile-controls/retention")) == {"put"}
            and _operations(paths.get("/api/job-search/question-library")) == {"get", "post"}
            and _operations(paths.get("/api/job-search/relationships")) == {"get"}
        )
        record("retention_1_to_365_contract", bounds_ok, "OpenAPI declares retention bounds 1..365")
        record("job_hunt_api_contract", api_ok, "deployed job-hunt API methods match the reviewed contract")
    except Exception as exc:
        reason = _safe_reason(exc)
        record("retention_1_to_365_contract", False, reason)
        record("job_hunt_api_contract", False, reason)

    try:
        html_response = get("/")
        html = html_response.body.decode("utf-8")
        match = re.search(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html)
        if not match:
            raise SafeValidationError("javascript_asset_not_found")
        asset_url = urljoin(base + "/", match.group(1))
        if _origin(asset_url) != base_origin:
            raise SafeValidationError("cross_origin_asset_refused")
        asset_response = get(asset_url)
        bundle = asset_response.body.decode("utf-8")
        markers_ok = all(marker in bundle for marker in UI_MARKERS)
        record("shipped_ui_markers", markers_ok, "reviewed workflow controls are in the shipped JS")
        if expected_asset is not None:
            actual_name = PurePosixPath(urlparse(asset_url).path).name
            record(
                "reviewed_asset_filename",
                actual_name == PurePosixPath(expected_asset).name,
                f"shipped asset filename is {actual_name}",
            )
    except Exception as exc:
        reason = _safe_reason(exc)
        record("shipped_ui_markers", False, reason)
        if expected_asset is not None:
            record("reviewed_asset_filename", False, reason)

    passed = sum(check["status"] == "pass" for check in checks)
    failed = len(checks) - passed
    return {
        "schema_version": SCHEMA_VERSION,
        "target": base,
        "mode": "read_only_get",
        "overall": "pass" if failed == 0 else "fail",
        "summary": {"passed": passed, "failed": failed, "total": len(checks)},
        "checks": checks,
    }


def _failed_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "read_only_get",
        "overall": "fail",
        "summary": {"passed": 0, "failed": 1, "total": 1},
        "checks": [{"id": "validator_input", "status": "fail", "detail": reason}],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-response-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--expected-asset")
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0 or args.max_response_bytes <= 0:
            raise ValueError("timeout and max-response-bytes must be positive")
        report = validate_deployment(
            args.base_url,
            timeout=args.timeout,
            max_response_bytes=args.max_response_bytes,
            allow_remote=args.allow_remote,
            expected_asset=args.expected_asset,
        )
    except ValueError as exc:
        report = _failed_report(str(exc))
    except Exception as exc:
        report = _failed_report(_safe_reason(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

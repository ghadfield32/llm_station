"""build_snapshot() is pure: a synthetic VerificationReport in, a redacted
status-snapshot dict out. No subprocess, no filesystem — that's covered by
running the module directly (see life-center-infra's own test coverage for
`lc verify --json`'s shape)."""
from __future__ import annotations

from command_center.mcp.life_center_status_collector import build_snapshot

_REPORT = {
    "schema_version": "life-center.verify.v1",
    "generated_at": "2026-07-17T23:00:00+00:00",
    "catalog_digest": "sha256:abc",
    "checks": [
        {"check_id": "container_health:nextcloud", "service_id": "nextcloud", "status": "pass"},
        {"check_id": "http_reachability:nextcloud", "service_id": "nextcloud", "status": "pass"},
        {"check_id": "container_health:immich-server", "service_id": "immich-server", "status": "warn"},
        {"check_id": "http_reachability:actual", "service_id": "actual", "status": "fail"},
        {"check_id": "not_automated:backup_age", "service_id": None, "status": "unknown"},
    ],
}


def test_build_snapshot_reduces_per_service_overall_status():
    snap = build_snapshot(_REPORT)
    by_service = {s["service"]: s["status"] for s in snap["services"]}
    assert by_service["nextcloud"] == "healthy"      # all checks pass
    assert by_service["immich-server"] == "attention"  # one warn, no fail
    assert by_service["actual"] == "down"            # one fail


def test_build_snapshot_skips_service_id_none_checks():
    snap = build_snapshot(_REPORT)
    services = {s["service"] for s in snap["services"]}
    assert None not in services
    assert len(services) == 3  # not_automated:backup_age contributes no service row


def test_build_snapshot_overview_counts_down_as_attention():
    snap = build_snapshot(_REPORT)
    ov = snap["overview"]
    assert ov["services_total"] == 3
    assert ov["services_healthy"] == 1
    # ServiceHealth distinguishes attention/down; Overview only has two buckets,
    # so both "attention" and "down" services fold into services_attention here.
    assert ov["services_attention"] == 2


def test_build_snapshot_never_fabricates_unautomated_fields():
    snap = build_snapshot(_REPORT)
    ov = snap["overview"]
    assert ov["oldest_backup_age_hours"] == 0.0
    assert ov["open_security_findings"] == 0


def test_build_snapshot_carries_schema_and_digest_through():
    snap = build_snapshot(_REPORT)
    assert snap["schema_version"] == "life-center.status-snapshot.v1"
    assert snap["source_verify_schema_version"] == "life-center.verify.v1"
    assert snap["catalog_digest"] == "sha256:abc"

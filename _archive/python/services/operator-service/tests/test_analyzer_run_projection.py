from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fdai_operator_service.analyzer_run_projection import (
    project_analyzer_run,
    project_latest_analyzer_coverage,
)

NOW = datetime(2026, 9, 14, 3, 30, tzinfo=UTC)


def _row(
    *,
    recorded_at: datetime = NOW,
    execution_authority: bool = False,
    source_complete: bool | None = True,
    schema_version: str = "1.2.0",
    coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    target_resolution: dict[str, object] = {
        "configured": 0,
        "discovered": 22,
        "candidate_count": 35,
        "inventory_consulted": True,
        "skipped_reasons": ["unverified_state_fact"],
        "skipped_reason_counts": {"unverified_state_fact": 13},
        "truncated": False,
    }
    if source_complete is not None:
        target_resolution["source_complete"] = source_complete
    report: dict[str, object] = {
        "targets": 22,
        "findings": 0,
        "published": 0,
        "duplicates_suppressed": 0,
        "uncertain": 0,
        "unsupported_targets": [],
        "analyzer_errors": [],
        "publish_errors": [],
        "receipt_errors": [],
        "receipts": [],
        "target_resolution": target_resolution,
        "readiness": {
            "scheduling": "local_loop",
            "target_discovery": "available",
            "metric_access": "available",
            "event_publication": "unverified",
            "metric_source_delays": {},
        },
        "trace_continuity": {
            "targets": 0,
            "scenarios": 0,
            "continuous": 0,
            "unknown": 0,
            "findings": 0,
            "published": 0,
            "publish_errors": [],
        },
    }
    if coverage is not None:
        report["coverage"] = coverage
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return {
        "value": {
            "schema_version": schema_version,
            "run_id": "local-analyzer-1",
            "tick_id": "7",
            "attempt_id": hashlib.sha256(canonical.encode()).hexdigest(),
            "recorded_at": recorded_at.isoformat(),
            "report_digest": hashlib.sha256(canonical.encode()).hexdigest(),
            "report": report,
            "execution_authority": execution_authority,
        }
    }


def test_projects_complete_no_authority_tick_coverage() -> None:
    projection = project_analyzer_run([_row()])

    assert projection == {
        "source": "postgresql:state_kv:analyzer-tick-receipt",
        "recorded_at": NOW.isoformat(),
        "targets": 22,
        "findings": 0,
        "published": 0,
        "duplicates_suppressed": 0,
        "uncertain": 0,
        "configured_targets": 0,
        "discovered_targets": 22,
        "candidate_count": 35,
        "inventory_consulted": True,
        "source_complete": True,
        "truncated": False,
        "skipped_reasons": ["unverified_state_fact"],
        "skipped_reason_counts": {"unverified_state_fact": 13},
        "unsupported_target_count": 0,
        "analyzer_error_count": 0,
        "publish_error_count": 0,
        "receipt_error_count": 0,
        "trace_publish_error_count": 0,
        "scheduling": "local_loop",
        "metric_access": "available",
        "event_publication": "unverified",
        "execution_authority": False,
    }


def test_returns_none_without_a_retained_tick() -> None:
    assert project_analyzer_run([]) is None


def test_projects_current_cross_resource_coverage() -> None:
    publication_counts = {
        "published": 0,
        "published_receipt_unrecorded": 0,
        "duplicate_suppressed": 0,
        "reconciled_duplicate": 0,
        "publish_uncertain": 0,
        "awaiting_reconciliation": 0,
        "failed": 0,
    }
    coverage: dict[str, object] = {
        "schema_version": "1.0.0",
        "status": "available",
        "unavailable_reason": None,
        "candidate_count": 1,
        "selected_count": 1,
        "evaluated_count": 1,
        "held_count": 0,
        "finding_count": 0,
        "unsupported_count": 0,
        "error_count": 0,
        "unattributed_error_count": 0,
        "unattributed_error_codes": [],
        "publication_counts": publication_counts,
        "resource_types": [
            {
                "resource_type": "api-gateway",
                "candidate_count": 1,
                "selected_count": 1,
                "evaluated_count": 1,
                "held_count": 0,
                "held_reason_counts": {},
                "finding_count": 0,
                "unsupported_count": 0,
                "error_count": 0,
                "error_codes": [],
                "publication_counts": publication_counts,
            }
        ],
        "resources": [
            {
                "resource_ref": "resource-api",
                "resource_type": "api-gateway",
                "resource_kind": "api_management",
                "evaluation_state": "evaluated_no_finding",
                "finding_count": 0,
                "unsupported_count": 0,
                "error_count": 0,
                "error_codes": [],
                "publication_counts": publication_counts,
            }
        ],
        "cause_claim_supported": False,
        "execution_authority": False,
    }
    row = _row(schema_version="1.3.0", coverage=coverage)

    projection = project_analyzer_run([row])

    assert projection is not None
    assert "coverage" not in projection
    latest = project_latest_analyzer_coverage([row])
    assert latest["status"] == "available"
    assert latest["recorded_at"] == NOW.isoformat()
    resources = latest["resources"]
    assert isinstance(resources, list)
    assert resources[0]["resource_type"] == "api-gateway"
    failed_row = _row(
        schema_version="1.3.0",
        coverage=coverage,
        source_complete=False,
    )
    partial_projection = project_analyzer_run([failed_row])
    assert partial_projection is not None
    assert partial_projection["source_complete"] is False
    assert project_latest_analyzer_coverage([failed_row])["status"] == "available"


def test_returns_latest_successful_tick_after_a_failed_retry() -> None:
    projection = project_analyzer_run(
        [
            _row(recorded_at=NOW + timedelta(minutes=1), source_complete=False),
            _row(),
        ]
    )

    assert projection is not None
    assert projection["recorded_at"] == NOW.isoformat()
    assert projection["source_complete"] is True


def test_invalid_current_coverage_is_section_local_unavailable() -> None:
    coverage = {
        "schema_version": "1.0.0",
        "status": "unavailable",
        "unavailable_reason": "source_absent",
        "cause_claim_supported": False,
        "execution_authority": True,
    }

    row = _row(schema_version="1.3.0", coverage=coverage)
    projection = project_analyzer_run([row])

    assert projection is not None
    assert "coverage" not in projection
    latest = project_latest_analyzer_coverage([row])
    assert latest["status"] == "unavailable"
    assert latest["unavailable_reason"] == "invalid_coverage"


def test_returns_none_when_no_successful_tick_is_retained() -> None:
    assert project_analyzer_run([_row(source_complete=False)]) is None
    latest = project_latest_analyzer_coverage([_row(source_complete=False)])
    assert latest["status"] == "unavailable"
    assert latest["unavailable_reason"] == "legacy_receipt"


def test_invalid_receipt_withholds_successful_reference_without_failing_route() -> None:
    tampered = _row()
    tampered["value"]["report"]["targets"] = 23  # type: ignore[index]
    assert project_analyzer_run([tampered, _row()]) is None
    assert project_latest_analyzer_coverage([tampered])["unavailable_reason"] == ("invalid_receipt")

    assert project_analyzer_run([_row(execution_authority=True)]) is None


def test_rejects_missing_source_completeness() -> None:
    assert project_analyzer_run([_row(source_complete=None)]) is None

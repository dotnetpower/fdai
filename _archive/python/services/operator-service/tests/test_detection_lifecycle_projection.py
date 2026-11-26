"""The lifecycle section admits a tracked row or names why it cannot.

The Operator Service did not observe the evidence, so it never repairs a
projection. Every test below asks whether a specific defect produces a named
unavailable section instead of a shorter, calmer answer than the one the
control plane actually retained.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fdai_operator_service.detection_lifecycle_projection import (
    LIFECYCLE_SCHEMA_VERSION,
    detection_lifecycle_projection,
)

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_REF = "cluster-a/default/orders"


def _targets(section: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read the served targets with the shape the Operator API promises."""

    targets = section["targets"]
    assert isinstance(targets, list)
    return [cast(dict[str, Any], target) for target in targets]


def _first(section: Mapping[str, Any]) -> dict[str, Any]:
    """Read the only served target."""

    targets = _targets(section)
    assert len(targets) == 1
    return targets[0]


def _failure(**overrides: Any) -> dict[str, Any]:
    failure = {
        "resource_ref": _REF,
        "idempotency_key": "restart-1",
        "signal": "container_restart",
        "occurred_at": (_NOW - timedelta(seconds=12)).isoformat(),
        "recorded_at": _NOW.isoformat(),
        "detection_latency_seconds": 12.0,
        "evidence_complete": True,
        "recovery_closed": False,
        "recovery_status": "restart_observed_not_recovered",
        "publication": "published",
        "assessed_by": "core.ontology_platform.kubernetes_pod_lifecycle",
        "evidence_refs": ["pod-old"],
        "evidence_gaps": [],
    }
    failure.update(overrides)
    return failure


def _snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot = {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "resource_ref": _REF,
        "generated_at": _NOW.isoformat(),
        "freshness_budget_seconds": 900.0,
        "current_state": "failing",
        "current_state_observed_at": _NOW.isoformat(),
        "current_signal": "container_restart",
        "recovery_state": "not_verified",
        "recovery_verified_at": None,
        "failure_count": 1,
        "failures": [_failure()],
        "retained_record_count": 1,
        "evidence_gaps": [],
        "evidence_gap_details": [],
        "delivery_counts": {
            "published": 1,
            "published_receipt_unrecorded": 0,
            "duplicate_suppressed": 0,
            "reconciled_duplicate": 0,
            "publish_uncertain": 0,
            "awaiting_reconciliation": 0,
            "failed": 0,
        },
        "cause_claim_supported": False,
        "execution_authority": False,
    }
    snapshot.update(overrides)
    return snapshot


def _row(snapshot: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    value = {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "resource_ref": _REF,
        "snapshot": snapshot if snapshot is not None else _snapshot(),
        "records": [],
    }
    value.update(overrides)
    return {"value": value, "updated_at": _NOW}


def test_no_row_is_an_available_section_with_nothing_to_report() -> None:
    section = detection_lifecycle_projection([], now=_NOW)

    assert section["status"] == "available"
    assert section["target_count"] == 0
    assert section["failure_total"] == 0
    assert section["cause_claim_supported"] is False
    assert section["execution_authority"] is False


def test_a_valid_row_is_served_with_its_four_answers_separated() -> None:
    section = detection_lifecycle_projection([_row()], now=_NOW)

    target = _first(section)
    assert section["counts"] == {"recovered": 0, "failing": 1, "unknown": 0}
    assert section["recovery_counts"] == {"verified": 0, "not_verified": 1, "unknown": 0}
    assert section["failure_total"] == 1
    assert section["gap_target_count"] == 0
    assert target["current_state"] == "failing"
    assert target["recovery_state"] == "not_verified"
    assert target["failures"][0]["publication"] == "published"
    assert target["stale"] is False


def test_verified_recovery_keeps_the_failure_that_preceded_it() -> None:
    snapshot = _snapshot(
        current_state="recovered",
        recovery_state="verified",
        recovery_verified_at=_NOW.isoformat(),
        failures=[_failure(recovery_closed=True, recovery_status="restart_observed_recovered")],
    )

    section = detection_lifecycle_projection([_row(snapshot)], now=_NOW)

    target = _first(section)
    assert target["current_state"] == "recovered"
    assert target["recovery_verified_at"] == _NOW.isoformat()
    assert target["failure_count"] == 1


def test_a_projection_older_than_its_budget_withdraws_its_current_state() -> None:
    section = detection_lifecycle_projection([_row()], now=_NOW + timedelta(hours=3))

    target = _first(section)
    assert target["stale"] is True
    assert target["current_state"] == "unknown"
    assert target["current_signal"] is None
    assert target["recovery_state"] == "unknown"
    assert target["recovery_verified_at"] is None
    assert "stale_evidence" in target["evidence_gaps"]
    assert target["failure_count"] == 1
    assert section["gap_target_count"] == 1


def test_an_uncertain_delivery_reaches_the_operator_as_a_gap() -> None:
    snapshot = _snapshot(
        evidence_gaps=["delivery_uncertain"],
        failures=[_failure(publication="publish_uncertain")],
        delivery_counts={
            "published": 0,
            "published_receipt_unrecorded": 0,
            "duplicate_suppressed": 0,
            "reconciled_duplicate": 0,
            "publish_uncertain": 1,
            "awaiting_reconciliation": 0,
            "failed": 0,
        },
    )

    section = detection_lifecycle_projection([_row(snapshot)], now=_NOW)

    target = _first(section)
    assert target["evidence_gaps"] == ["delivery_uncertain"]
    assert target["delivery_counts"]["publish_uncertain"] == 1
    assert section["gap_target_count"] == 1


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row["value"].update(schema_version=2), "unsupported_schema"),
        (lambda row: row["value"]["snapshot"].update(schema_version=2), "unsupported_schema"),
        (lambda row: row["value"].update(snapshot="not-an-object"), "malformed_projection"),
        (lambda row: row.update(value="not-an-object"), "malformed_projection"),
        (
            lambda row: row["value"]["snapshot"].update(cause_claim_supported=True),
            "cause_claim_rejected",
        ),
        (
            lambda row: row["value"]["snapshot"].update(execution_authority=True),
            "authority_claim_rejected",
        ),
        (
            lambda row: row["value"]["snapshot"].update(current_state="recovered"),
            "unverified_recovery_rejected",
        ),
        (
            lambda row: row["value"]["snapshot"].update(failure_count=5),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"].update(current_state="mostly_fine"),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"]["delivery_counts"].update(invented=1),
            "unknown_publication_state",
        ),
        (
            lambda row: row["value"]["snapshot"].update(generated_at="2026-08-31 noon"),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"]["failures"][0].update(recovery_closed="yes"),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"]["failures"][0].update(
                recovery_closed=True, evidence_complete=False
            ),
            "unverified_recovery_rejected",
        ),
        (
            lambda row: row["value"]["snapshot"]["failures"][0].update(
                evidence_refs=[f"ref-{index}" for index in range(20)]
            ),
            "evidence_ref_limit_exceeded",
        ),
        (
            lambda row: row["value"]["snapshot"].update(
                failure_count=40, failures=[_failure() for _ in range(40)]
            ),
            "failure_limit_exceeded",
        ),
        (
            lambda row: row["value"]["snapshot"].update(evidence_gaps=["nothing_wrong"]),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"].update(
                evidence_gaps=["stale_evidence", "stale_evidence"]
            ),
            "malformed_projection",
        ),
        (
            lambda row: row["value"]["snapshot"].update(retained_record_count=-1),
            "malformed_projection",
        ),
    ],
)
def test_a_defective_row_makes_the_section_unavailable_with_a_named_reason(
    mutate: Any,
    reason: str,
) -> None:
    row = _row()
    mutate(row)

    section = detection_lifecycle_projection([row], now=_NOW)

    assert section["status"] == "unavailable"
    assert section["unavailable_reason"] == reason
    assert section["targets"] == []
    assert section["target_count"] == 0
    assert section["failure_total"] == 0


def test_one_defective_row_never_shortens_a_healthy_neighbour() -> None:
    healthy = _row()
    defective = _row()
    defective["value"]["snapshot"]["current_state"] = "mostly_fine"

    section = detection_lifecycle_projection([healthy, defective], now=_NOW)

    assert section["status"] == "unavailable"
    assert section["unavailable_reason"] == "malformed_projection"


def test_more_targets_than_the_bound_are_refused_rather_than_truncated() -> None:
    rows = []
    for index in range(201):
        row = copy.deepcopy(_row())
        row["value"]["snapshot"]["resource_ref"] = f"{_REF}-{index}"
        rows.append(row)

    section = detection_lifecycle_projection(rows, now=_NOW)

    assert section["status"] == "unavailable"
    assert section["unavailable_reason"] == "target_limit_exceeded"


def test_targets_are_ordered_by_reference_so_the_surface_is_stable() -> None:
    second = copy.deepcopy(_row())
    second["value"]["snapshot"]["resource_ref"] = "cluster-a/default/payments"

    section = detection_lifecycle_projection([_row(), second], now=_NOW)

    assert [target["resource_ref"] for target in _targets(section)] == [
        "cluster-a/default/orders",
        "cluster-a/default/payments",
    ]

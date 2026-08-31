from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_operator_service.analyzer_lifecycle_projection import (
    project_analyzer_lifecycle,
)
from fdai_operator_service.families.operations import ProjectionUnavailableError

NOW = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)


def _row(
    key: str,
    *,
    resource_ref: str = "cluster/example/pod/orders",
    signal: str = "pod_replacement",
    current_state: str = "running",
    evidence_state: str = "complete",
    publication: str = "published",
    recovery_closed: bool | None = True,
    occurred_at: str = "2026-08-31T06:59:50+00:00",
    recorded_at: str = "2026-08-31T07:00:00+00:00",
) -> dict[str, object]:
    return {
        "updated_at": NOW,
        "value": {
            "schema_version": "1.0.0",
            "idempotency_key": key,
            "resource_ref": resource_ref,
            "resource_kind": "kubernetes_pod",
            "signal": signal,
            "occurred_at": occurred_at,
            "recorded_at": recorded_at,
            "current_state": current_state,
            "detection_latency_seconds": 10.0,
            "evidence_complete": evidence_state == "complete",
            "evidence_state": evidence_state,
            "publication": publication,
            "recovery_closed": recovery_closed,
            "evidence_refs": ["pod-old", "pod-new"],
            "cause_claim_supported": False,
            "execution_authority": False,
        },
    }


def test_projection_separates_current_history_and_duplicate_publication() -> None:
    rows = [
        _row(
            "analyzer:current",
            publication="duplicate_suppressed",
            recorded_at="2026-08-31T07:00:01+00:00",
        ),
        _row("analyzer:current"),
        _row(
            "analyzer:history",
            signal="container_restart",
            current_state="failed",
            recovery_closed=False,
            occurred_at="2026-08-31T06:55:00+00:00",
            recorded_at="2026-08-31T06:55:05+00:00",
        ),
    ]

    result = project_analyzer_lifecycle(rows)

    assert result["target_count"] == 1
    target = result["targets"][0]  # type: ignore[index]
    assert target["current"]["signal"] == "pod_replacement"  # type: ignore[index]
    assert target["current"]["publication"] == {  # type: ignore[index]
        "current": "duplicate_suppressed",
        "attempts": ["published", "duplicate_suppressed"],
        "duplicate_observed": True,
    }
    assert target["history"][0]["signal"] == "container_restart"  # type: ignore[index]
    assert target["history"][0]["recovery_state"] == "open"  # type: ignore[index]


def test_projection_keeps_missed_conflicting_and_incomplete_states_explicit() -> None:
    rows = [
        _row("missed", resource_ref="pod/missed", evidence_state="missed"),
        _row("conflict", resource_ref="pod/conflict", evidence_state="conflicting"),
        _row("incomplete", resource_ref="pod/incomplete", evidence_state="incomplete"),
    ]

    result = project_analyzer_lifecycle(rows)

    assert result["evidence_counts"] == {
        "complete": 0,
        "incomplete": 1,
        "conflicting": 1,
        "missed": 1,
    }
    assert all(
        target["current"]["cause_claim_supported"] is False  # type: ignore[index]
        and target["current"]["execution_authority"] is False  # type: ignore[index]
        for target in result["targets"]  # type: ignore[union-attr]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("evidence_state", "invented"),
        ("cause_claim_supported", True),
        ("execution_authority", True),
    ),
)
def test_projection_rejects_widened_or_unknown_receipts(field: str, value: object) -> None:
    row = _row("invalid")
    row["value"][field] = value  # type: ignore[index]

    with pytest.raises(ProjectionUnavailableError):
        project_analyzer_lifecycle([row])

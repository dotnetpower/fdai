from __future__ import annotations

import pytest
from fdai_operator_service.analyzer_coverage_projection import (
    project_analyzer_coverage,
)
from fdai_operator_service.families.operations import ProjectionUnavailableError

PUBLICATIONS = {
    "published": 0,
    "published_receipt_unrecorded": 0,
    "duplicate_suppressed": 0,
    "reconciled_duplicate": 0,
    "publish_uncertain": 0,
    "awaiting_reconciliation": 0,
    "failed": 0,
}


def _coverage() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "status": "available",
        "unavailable_reason": None,
        "candidate_count": 2,
        "selected_count": 1,
        "evaluated_count": 0,
        "held_count": 1,
        "finding_count": 0,
        "unsupported_count": 1,
        "error_count": 0,
        "unattributed_error_count": 0,
        "publication_counts": PUBLICATIONS,
        "resource_types": [
            {
                "resource_type": "kubernetes-cluster",
                "candidate_count": 1,
                "selected_count": 1,
                "evaluated_count": 0,
                "held_count": 0,
                "finding_count": 0,
                "unsupported_count": 1,
                "error_count": 0,
                "publication_counts": PUBLICATIONS,
            },
            {
                "resource_type": "llm-endpoint",
                "candidate_count": 1,
                "selected_count": 0,
                "evaluated_count": 0,
                "held_count": 1,
                "finding_count": 0,
                "unsupported_count": 0,
                "error_count": 0,
                "publication_counts": PUBLICATIONS,
            },
        ],
        "resources": [
            {
                "resource_ref": "resource-aks",
                "resource_type": "kubernetes-cluster",
                "resource_kind": "aks_cluster",
                "evaluation_state": "unsupported",
                "finding_count": 0,
                "unsupported_count": 1,
                "error_count": 0,
                "publication_counts": PUBLICATIONS,
            }
        ],
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def test_preserves_unsupported_as_distinct_from_error_and_health() -> None:
    projected = project_analyzer_coverage(
        _coverage(),
        run_attempt_id="a" * 64,
    )

    assert projected["evaluated_count"] == 0
    assert projected["unsupported_count"] == 1
    resources = projected["resources"]
    assert isinstance(resources, list)
    assert resources[0]["evaluation_state"] == "unsupported"
    assert projected["schema_version"] == "1.1.0"
    assert projected["unattributed_error_codes"] == []
    resource_types = projected["resource_types"]
    assert isinstance(resource_types, list)
    assert resource_types[1]["held_reason_counts"] == {"legacy_unspecified": 1}
    assert resources[0]["error_codes"] == []


def test_rejects_widened_authority_and_broken_candidate_algebra() -> None:
    authority = _coverage()
    authority["execution_authority"] = True
    with pytest.raises(ProjectionUnavailableError, match="authority"):
        project_analyzer_coverage(authority, run_attempt_id="a" * 64)

    broken = _coverage()
    broken["candidate_count"] = 3
    with pytest.raises(ProjectionUnavailableError, match="global totals"):
        project_analyzer_coverage(broken, run_attempt_id="a" * 64)


def test_current_schema_preserves_reconciled_reason_and_error_codes() -> None:
    current = _coverage()
    current["schema_version"] = "1.1.0"
    current["error_count"] = 1
    current["unattributed_error_count"] = 1
    current["unattributed_error_codes"] = ["publication_failure"]
    resource_types = current["resource_types"]
    assert isinstance(resource_types, list)
    resource_types[0]["held_reason_counts"] = {}
    resource_types[0]["error_codes"] = []
    resource_types[1]["held_reason_counts"] = {"selection_limit": 1}
    resource_types[1]["error_codes"] = []
    resources = current["resources"]
    assert isinstance(resources, list)
    resources[0]["error_codes"] = []

    projected = project_analyzer_coverage(current, run_attempt_id="a" * 64)

    assert projected["unattributed_error_codes"] == ["publication_failure"]
    projected_types = projected["resource_types"]
    assert isinstance(projected_types, list)
    assert projected_types[1]["held_reason_counts"] == {"selection_limit": 1}


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("held_reason", "held reason totals"),
        ("resource_error_codes", "error codes"),
        ("type_error_codes", "resource type totals"),
        ("unattributed_error_codes", "unattributed error codes"),
    ),
)
def test_current_schema_rejects_invalid_reason_and_error_algebra(
    mutation: str,
    message: str,
) -> None:
    current = _coverage()
    current["schema_version"] = "1.1.0"
    current["unattributed_error_codes"] = []
    resource_types = current["resource_types"]
    resources = current["resources"]
    assert isinstance(resource_types, list)
    assert isinstance(resources, list)
    for row in resource_types:
        row["held_reason_counts"] = {"selection_limit": 1} if row["held_count"] == 1 else {}
        row["error_codes"] = []
    resources[0]["error_codes"] = []

    if mutation == "held_reason":
        resource_types[1]["held_reason_counts"] = {}
    elif mutation == "resource_error_codes":
        resources[0]["error_codes"] = ["analyzer_failure"]
    elif mutation == "type_error_codes":
        resource_types[0]["error_codes"] = ["analyzer_failure"]
    else:
        current["unattributed_error_codes"] = ["publication_failure"]

    with pytest.raises(ProjectionUnavailableError, match=message):
        project_analyzer_coverage(current, run_attempt_id="a" * 64)

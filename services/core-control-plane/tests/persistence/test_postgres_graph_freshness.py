from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.persistence.postgres_graph_freshness import _receipt_from_row

_NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64


def _row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "inventory-generation-1",
        "observation_kind": "observed",
        "metadata": {
            "link_types": ["attached_to", "contains", "depends_on"],
            "relationship_complete": True,
            "provider_scope_coverage": {"provider_identity_complete": True},
            "derived_source_states": [
                {
                    "source": "azure-resource-graph",
                    "status": "available",
                    "observed_at": _NOW.isoformat(),
                    "reason": None,
                }
            ],
        },
        "completed_at": _NOW,
        "updated_at": _NOW + timedelta(seconds=1),
        "recorded_at": _NOW + timedelta(seconds=2),
        "resource_present": True,
        "realtime_pending": False,
        "newer_failure": False,
    }
    value.update(overrides)
    return value


def test_active_inventory_row_builds_exact_no_authority_receipt() -> None:
    first = _receipt_from_row(
        _row(),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )
    replay = _receipt_from_row(
        _row(),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert first == replay
    assert first.complete is True
    assert first.conflicts == ()
    assert first.valid_until == _NOW + timedelta(hours=1)
    assert first.execution_authority is False
    assert first.receipt_digest.startswith("sha256:")
    assert first.graph_revision.startswith("sha256:")


def test_active_inventory_gaps_remain_explicit_and_incomplete() -> None:
    receipt = _receipt_from_row(
        _row(
            observation_kind="expected",
            resource_present=False,
            realtime_pending=True,
            newer_failure=True,
            metadata={
                "link_types": ["contains"],
                "relationship_complete": False,
                "provider_scope_coverage": {"provider_identity_complete": False},
                "derived_source_states": [
                    {
                        "source": "kubernetes",
                        "status": "unavailable",
                        "observed_at": None,
                        "reason": "authorization_failed",
                    }
                ],
                "truncated": True,
            },
        ),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert receipt.complete is False
    assert receipt.truncated is True
    assert receipt.conflicts == (
        "graph_link_coverage_incomplete",
        "graph_not_observed",
        "graph_provider_identity_incomplete",
        "graph_realtime_pending",
        "graph_relationship_incomplete",
        "graph_source_incomplete",
        "graph_target_missing",
        "inventory_truncated",
        "newer_inventory_failure",
    )


@pytest.mark.parametrize("metadata", [None, [], "{not-json"])
def test_active_inventory_rejects_malformed_metadata(metadata: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _receipt_from_row(
            _row(metadata=metadata),
            target_ref="resource-a",
            ontology_release_digest=_RELEASE,
            freshness_budget=timedelta(hours=1),
        )

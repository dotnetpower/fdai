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
        "ontology_status": {
            "status": "available",
            "generation": "inventory-generation-1",
            "ontology_release_digest": _RELEASE,
        },
        "ontology_manifest": {
            "status": "available",
            "generation": "inventory-generation-1",
            "ontology_release_digest": _RELEASE,
            "complete": True,
            "relationship_complete": True,
            "object_ids": ["resource-a"],
            "link_keys": [],
        },
        "operating_status": {
            "status": "projected",
            "source_revision": "operating-model-1",
        },
        "operating_manifest": {
            "status": "projected",
            "source_revision": "operating-model-1",
            "object_ids": [],
            "link_keys": [],
        },
        "resource_present": True,
        "realtime_pending": False,
        "overlay_pending": False,
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

    assert first is not None
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
            overlay_pending=True,
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

    assert receipt is not None
    assert receipt.complete is False
    assert receipt.truncated is True
    assert receipt.conflicts == (
        "graph_link_coverage_incomplete",
        "graph_not_observed",
        "graph_overlay_pending",
        "graph_provider_identity_incomplete",
        "graph_realtime_pending",
        "graph_relationship_incomplete",
        "graph_source_incomplete",
        "graph_target_missing",
        "inventory_truncated",
        "newer_inventory_failure",
    )


def test_projection_release_and_generation_mismatch_remain_incomplete() -> None:
    receipt = _receipt_from_row(
        _row(
            ontology_status={
                "status": "available",
                "generation": "inventory-generation-2",
                "ontology_release_digest": "sha256:" + "b" * 64,
            },
            ontology_manifest={
                "generation": "inventory-generation-2",
                "ontology_release_digest": "sha256:" + "b" * 64,
                "complete": True,
                "relationship_complete": True,
            },
        ),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert receipt is not None
    assert receipt.ontology_release_digest == "sha256:" + "b" * 64
    assert receipt.complete is False
    assert "graph_projection_incomplete" in receipt.conflicts
    assert "graph_release_mismatch" in receipt.conflicts


def test_missing_persisted_projection_release_returns_unavailable() -> None:
    receipt = _receipt_from_row(
        _row(ontology_manifest={}),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert receipt is None


def test_operating_model_revision_changes_receipt_identity() -> None:
    first = _receipt_from_row(
        _row(),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )
    second = _receipt_from_row(
        _row(
            operating_status={
                "status": "projected",
                "source_revision": "operating-model-2",
            },
            operating_manifest={
                "status": "projected",
                "source_revision": "operating-model-2",
                "object_ids": ["objective-2"],
                "link_keys": [],
            },
        ),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert first is not None
    assert second is not None
    assert first.graph_revision != second.graph_revision
    assert first.receipt_digest != second.receipt_digest


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"operating_status": None}, "operating_model_incomplete"),
        ({"operating_manifest": None}, "operating_model_incomplete"),
        (
            {
                "operating_status": {
                    "status": "projected",
                    "source_revision": "operating-model-2",
                }
            },
            "operating_model_incomplete",
        ),
        (
            {
                "operating_status": {"status": "projected", "source_revision": "   "},
                "operating_manifest": {"status": "projected", "source_revision": "   "},
            },
            "operating_model_incomplete",
        ),
    ],
)
def test_operating_model_identity_is_required(
    overrides: dict[str, object],
    reason: str,
) -> None:
    receipt = _receipt_from_row(
        _row(**overrides),
        target_ref="resource-a",
        ontology_release_digest=_RELEASE,
        freshness_budget=timedelta(hours=1),
    )

    assert receipt is not None
    assert receipt.complete is False
    assert reason in receipt.conflicts


@pytest.mark.parametrize("metadata", [None, [], "{not-json"])
def test_active_inventory_rejects_malformed_metadata(metadata: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _receipt_from_row(
            _row(metadata=metadata),
            target_ref="resource-a",
            ontology_release_digest=_RELEASE,
            freshness_budget=timedelta(hours=1),
        )

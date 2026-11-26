"""Tests for semantic graph-refresh certification receipt construction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.graph_refresh_audit import GraphEvidenceStatus
from fdai.delivery.semantic_refresh_certification import (
    ActiveCertificationResource,
    _secured,
)
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY

NOW = datetime(2026, 9, 27, tzinfo=UTC)
RESOURCE = ActiveCertificationResource(
    generation="generation-1",
    resource_id="/subscriptions/example/resourceGroups/example",
    resource_type="resource-group",
    name="example",
)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, GraphEvidenceStatus.COMPLETE),
        ({"age_seconds": 120}, GraphEvidenceStatus.STALE),
        ({"completeness": 0.5}, GraphEvidenceStatus.INCOMPLETE),
        ({"conflicts": ("certification_conflict",)}, GraphEvidenceStatus.CONFLICTING),
        ({"include_metadata": False}, GraphEvidenceStatus.UNAVAILABLE),
    ],
)
def test_certification_secured_states_remain_distinct(
    kwargs: dict[str, object],
    expected: GraphEvidenceStatus,
) -> None:
    age_seconds = int(kwargs.pop("age_seconds", 1))
    secured = _secured(
        RESOURCE,
        now=NOW,
        age_seconds=age_seconds,
        ontology_release_digest="sha256:" + ("a" * 64),
        principal_scope_digest="sha256:" + ("b" * 64),
        **kwargs,
    )
    properties = secured.materialization.graph.objects[0].properties["properties"]

    if expected is GraphEvidenceStatus.UNAVAILABLE:
        assert properties == {}
    else:
        metadata = properties[STATE_FACT_METADATA_PROPERTY]
        assert metadata["source_revision"] == RESOURCE.generation

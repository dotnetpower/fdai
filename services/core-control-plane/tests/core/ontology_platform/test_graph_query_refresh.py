"""Focused graph-first refresh integration tests for secured ObjectSet queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.graph_query_refresh import (
    SecuredGraphEvidenceQueryRefresher,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.shared.contracts.models import OntologyReleaseRef
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


class _Gateway:
    def __init__(self, refreshed: SecuredObjectSetQueryResult) -> None:
        self.refreshed = refreshed
        self.calls = 0

    async def materialize(self, definition, *, projection_request):
        del definition, projection_request
        self.calls += 1
        return self.refreshed


class _LiveProvider:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0

    async def refresh(self, *, definition, secured):
        del definition, secured
        self.calls += 1
        return self.result


def _secured(
    *,
    age_seconds: int,
    conflicts: tuple[str, ...] = (),
    include_resource_without_metadata: bool = False,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        freshness_seconds=60,
    )
    state = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-1",
        effective_at=NOW - timedelta(seconds=age_seconds),
        recorded_at=NOW - timedelta(seconds=age_seconds),
        evidence_cutoff=NOW - timedelta(seconds=age_seconds),
        freshness_ceiling_seconds=300,
        completeness=0.0 if conflicts else 1.0,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=("inventory-generation:generation-1",),
    )
    objects = [
        OntologyObjectRecord(
            id="resource-1",
            object_type="Resource",
            properties={"properties": {STATE_FACT_METADATA_PROPERTY: state.to_mapping()}},
        )
    ]
    if include_resource_without_metadata:
        objects.append(
            OntologyObjectRecord(
                id="resource-2",
                object_type="Resource",
                properties={"properties": {}},
            )
        )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=tuple(objects),
            links=(),
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=OntologyReleaseRef(schema_version="1.0.0", digest=DIGEST),
            projected_result_digest=_projected_result_digest(materialization),
            purpose=definition.purpose,
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=True,
            truncated=False,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


def _request() -> ProjectionRequest:
    return ProjectionRequest(
        caller_role="reader",
        declared_purposes=frozenset({"operations-review"}),
    )


async def test_current_complete_graph_skips_live_provider() -> None:
    secured = _secured(age_seconds=30)
    live = _LiveProvider()
    gateway = _Gateway(secured)
    refresher = SecuredGraphEvidenceQueryRefresher(gateway=gateway, live_provider=live)

    assert (
        await refresher.refresh(
            definition=secured.materialization.definition,
            projection_request=_request(),
            secured=secured,
        )
        == secured
    )
    assert live.calls == 0
    assert gateway.calls == 0


async def test_stale_graph_without_provider_holds() -> None:
    secured = _secured(age_seconds=61)
    refresher = SecuredGraphEvidenceQueryRefresher(gateway=_Gateway(secured))

    with pytest.raises(QueryNodeHeldError, match="graph_stale"):
        await refresher.refresh(
            definition=secured.materialization.definition,
            projection_request=_request(),
            secured=secured,
        )


async def test_graph_holds_when_any_resource_lacks_freshness_metadata() -> None:
    secured = _secured(age_seconds=0, include_resource_without_metadata=True)
    refresher = SecuredGraphEvidenceQueryRefresher(gateway=_Gateway(secured))

    with pytest.raises(QueryNodeHeldError, match="graph_incomplete"):
        await refresher.refresh(
            definition=secured.materialization.definition,
            projection_request=_request(),
            secured=secured,
        )


async def test_stale_graph_refreshes_once_and_requeries_current_graph() -> None:
    stale = _secured(age_seconds=61)
    current = _secured(age_seconds=0)
    live = _LiveProvider()
    gateway = _Gateway(current)
    refresher = SecuredGraphEvidenceQueryRefresher(gateway=gateway, live_provider=live)

    assert (
        await refresher.refresh(
            definition=stale.materialization.definition,
            projection_request=_request(),
            secured=stale,
        )
        == current
    )
    assert live.calls == 1
    assert gateway.calls == 1


async def test_conflicting_graph_stays_held_after_one_refresh() -> None:
    conflicting = _secured(age_seconds=0, conflicts=("status",))
    live = _LiveProvider()
    gateway = _Gateway(conflicting)
    refresher = SecuredGraphEvidenceQueryRefresher(gateway=gateway, live_provider=live)

    with pytest.raises(QueryNodeHeldError, match="graph_conflicting"):
        await refresher.refresh(
            definition=conflicting.materialization.definition,
            projection_request=_request(),
            secured=conflicting,
        )
    assert live.calls == 1
    assert gateway.calls == 1

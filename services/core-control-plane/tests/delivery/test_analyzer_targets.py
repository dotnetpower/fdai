"""Analyzer target resolution from configuration and the durable inventory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.analyzer_targets import (
    INVENTORY_SCAN_LIMIT,
    SKIP_MALFORMED_RESOURCE,
    SKIP_STALE_STATE_FACT,
    SKIP_UNMAPPED_RESOURCE_TYPE,
    SKIP_UNUSABLE_STATE_FACT,
    SKIP_UNVERIFIED_STATE_FACT,
    AnalyzerTargetResolutionError,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.inventory import ResourceRecord
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

from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _state_fact(
    *,
    observed_at: datetime = NOW,
    conflicts: tuple[str, ...] = (),
    synthetic: bool = False,
    completeness: float = 1.0,
    lane: StateFactLane = StateFactLane.OBSERVED,
    authority: StateFactAuthority = StateFactAuthority.PROVIDER,
) -> dict[str, object]:
    return StateFactMetadata(
        lane=lane,
        authority=authority,
        source_identity="inventory-provider",
        source_revision="generation-1",
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=300,
        completeness=completeness,
        synthetic=synthetic,
        conflicts=conflicts,
        evidence_refs=("inventory-generation:generation-1",),
    ).to_mapping()


def _resource(
    resource_id: str,
    resource_type: str,
    *,
    state_fact: Mapping[str, object] | None = None,
) -> OntologyObjectRecord:
    provider_properties: dict[str, Any] = {}
    if state_fact is not None:
        provider_properties[STATE_FACT_METADATA_PROPERTY] = dict(state_fact)
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": resource_type,
            "properties": provider_properties,
        },
    )


class StubStore:
    """Minimal read-only stand-in for the durable inventory projection."""

    def __init__(
        self,
        objects: Sequence[OntologyObjectRecord] = (),
        *,
        truncated: bool = False,
        source_complete: bool = True,
        source_generation: str | None = None,
        error: Exception | None = None,
        honor_property_filter: bool = True,
    ) -> None:
        self._objects = tuple(objects)
        self._truncated = truncated
        self._source_complete = source_complete
        self._source_generation = source_generation
        self._error = error
        self._honor_property_filter = honor_property_filter
        self.limits: list[int] = []
        self.property_text_filters: list[Mapping[str, Sequence[str]] | None] = []
        self.relationship_flags: list[bool] = []

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        object_ids: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot:
        del object_ids, property_equals
        assert tuple(object_types) == ("Resource",)
        self.limits.append(limit)
        self.property_text_filters.append(property_text_in)
        self.relationship_flags.append(include_relationships)
        if self._error is not None:
            raise self._error
        objects = self._objects
        if self._honor_property_filter and property_text_in is not None:
            objects = tuple(
                record
                for record in objects
                if all(
                    record.properties.get(key) in values for key, values in property_text_in.items()
                )
            )
        return OntologyGraphSnapshot(
            objects=objects[:limit],
            truncated=self._truncated or len(objects) > limit,
            source_complete=self._source_complete,
            source_generation=self._source_generation,
        )


class StubProviderReferenceReader:
    """Return provider identities for exact requested logical resources."""

    def __init__(
        self,
        resources: Mapping[str, ResourceRecord],
        *,
        snapshot_id: str | None = "generation-1",
        error: Exception | None = None,
    ) -> None:
        self._resources = resources
        self._snapshot_id = snapshot_id
        self._error = error
        self.requests: list[tuple[str, ...]] = []
        self.provider_requests: list[tuple[str, ...]] = []

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        self.requests.append(resource_ids)
        if self._error is not None:
            raise self._error
        return self._snapshot_id, {
            resource_id: self._resources[resource_id]
            for resource_id in resource_ids
            if resource_id in self._resources
        }

    async def read_active_resources_by_provider_refs(
        self,
        *,
        provider_refs: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        self.provider_requests.append(provider_refs)
        if self._error is not None:
            raise self._error
        return self._snapshot_id, {
            resource.provider_ref.casefold(): resource
            for resource in self._resources.values()
            if resource.provider_ref is not None
            and resource.provider_ref.casefold() in provider_refs
        }


def _provider_reader(store: StubStore) -> StubProviderReferenceReader:
    resources: dict[str, ResourceRecord] = {}
    for record in store._objects:
        resource_id = record.properties.get("id")
        resource_type = record.properties.get("type")
        if (
            isinstance(resource_id, str)
            and resource_id.strip()
            and isinstance(resource_type, str)
            and resource_type.strip()
        ):
            resources[resource_id] = ResourceRecord(
                resource_id=resource_id,
                type=resource_type,
                provider_ref=f"/providers/example/resources/{resource_id}",
            )
    return StubProviderReferenceReader(resources)


async def _resolve(
    store: StubStore | None,
    *,
    configured: Sequence[AnalyzerTarget] = (),
    now: datetime = NOW,
    max_discovered: int = 200,
    decision_evidence: bool = True,
    provider_references: StubProviderReferenceReader | None = None,
    bind_provider_references: bool = True,
):
    reader = provider_references
    if reader is None and store is not None and bind_provider_references:
        reader = _provider_reader(store)
    return await resolve_analyzer_targets(
        configured=configured,
        store=store,  # type: ignore[arg-type]
        now=now,
        max_discovered=max_discovered,
        decision_evidence=(
            StubDecisionEvidenceAdmissionProvider(lambda: now) if decision_evidence else None
        ),
        provider_references=reader,
    )


# ---------------------------------------------------------------------------
# Durable inventory resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supported_inventory_resources_join_the_tick() -> None:
    store = StubStore(
        (
            _resource("res-aks", "kubernetes-cluster", state_fact=_state_fact()),
            _resource("res-mysql", "mysql-server", state_fact=_state_fact()),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),
        AnalyzerTarget(resource_ref="res-mysql", resource_kind="mysql_flexible_server"),
    )
    assert resolution.discovered == 2
    assert resolution.inventory_consulted is True
    assert store.relationship_flags == [False]
    assert resolution.skipped_reasons == ()
    assert [target.provider_query_ref for target in resolution.targets] == [
        "/providers/example/resources/res-aks",
        "/providers/example/resources/res-mysql",
    ]
    assert "provider_query_ref" not in repr(resolution.targets[0])


@pytest.mark.parametrize(
    ("resource_type", "resource_kind"),
    (
        ("api-gateway", "api_management"),
        ("kubernetes-cluster", "aks_cluster"),
        ("llm-endpoint", "azure_openai"),
        ("mysql-server", "mysql_flexible_server"),
        ("network.application-gateway", "application_gateway"),
    ),
)
@pytest.mark.asyncio
async def test_every_shipped_analyzer_kind_receives_its_provider_query_identity(
    resource_type: str,
    resource_kind: str,
) -> None:
    store = StubStore((_resource("res-1", resource_type),))

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-1", resource_kind=resource_kind),
    )
    assert resolution.targets[0].provider_query_ref == ("/providers/example/resources/res-1")


@pytest.mark.asyncio
async def test_property_keyed_inventory_state_selects_the_canonical_state_fact() -> None:
    state_fact = _state_fact()
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact={"availabilityState": {"malformed": True}, "state": state_fact},
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),
    )
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_property_metadata_without_generic_state_uses_identity_admission() -> None:
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact={"availabilityState": _state_fact()},
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),
    )
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_malformed_canonical_state_in_property_metadata_is_unusable() -> None:
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact={"state": "not-an-object"},
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (SKIP_UNUSABLE_STATE_FACT,)


@pytest.mark.asyncio
async def test_a_resource_without_a_state_fact_is_still_selectable() -> None:
    store = StubStore((_resource("res-apim", "api-gateway"),))

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-apim", resource_kind="api_management"),
    )
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_identity_only_selection_needs_no_state_admission() -> None:
    """Read-only identity enumeration asserts no decision-critical state."""

    store = StubStore((_resource("res-apim", "api-gateway"),))

    resolution = await _resolve(store, decision_evidence=False)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-apim", resource_kind="api_management"),
    )
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_state_fact_without_independent_admission_is_skipped() -> None:
    store = StubStore((_resource("res-aks", "kubernetes-cluster", state_fact=_state_fact()),))

    resolution = await _resolve(store, decision_evidence=False)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (SKIP_UNVERIFIED_STATE_FACT,)


@pytest.mark.asyncio
async def test_future_dated_state_fact_is_skipped() -> None:
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact=_state_fact(observed_at=NOW + timedelta(seconds=1)),
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (SKIP_STALE_STATE_FACT,)


@pytest.mark.asyncio
async def test_configured_targets_lead_and_win_a_duplicate() -> None:
    store = StubStore(
        (
            _resource("res-aks", "kubernetes-cluster", state_fact=_state_fact()),
            _resource("res-gw", "network.application-gateway", state_fact=_state_fact()),
        )
    )

    resolution = await _resolve(
        store,
        configured=(AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),),
    )

    assert resolution.targets[0].resource_ref == "res-aks"
    assert resolution.targets[0].provider_query_ref == ("/providers/example/resources/res-aks")
    assert [item.resource_ref for item in resolution.targets] == ["res-aks", "res-gw"]
    assert resolution.configured == 1
    assert resolution.discovered == 1


@pytest.mark.asyncio
async def test_configured_arm_reference_collapses_into_logical_inventory_target() -> None:
    provider_ref = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example-rg/providers/"
        "Microsoft.ContainerService/managedClusters/example-aks"
    )
    store = StubStore((_resource("logical-aks", "kubernetes-cluster"),))
    reader = StubProviderReferenceReader(
        {
            "logical-aks": ResourceRecord(
                resource_id="logical-aks",
                type="kubernetes-cluster",
                provider_ref=provider_ref,
            )
        }
    )

    resolution = await _resolve(
        store,
        configured=(AnalyzerTarget(resource_ref=provider_ref, resource_kind="aks_cluster"),),
        provider_references=reader,
    )

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="logical-aks", resource_kind="aks_cluster"),
    )
    assert resolution.targets[0].provider_query_ref == provider_ref
    assert resolution.configured == 1
    assert resolution.discovered == 0
    assert reader.provider_requests == [(provider_ref.casefold(),)]


@pytest.mark.asyncio
async def test_configured_provider_reference_must_match_active_inventory() -> None:
    provider_ref = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example-rg/providers/"
        "Microsoft.ContainerService/managedClusters/missing"
    )

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="provider reference is absent from active inventory",
    ):
        await _resolve(
            StubStore((_resource("logical-aks", "kubernetes-cluster"),)),
            configured=(
                AnalyzerTarget(
                    resource_ref="logical-aks",
                    resource_kind="aks_cluster",
                    provider_query_ref=provider_ref,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_configured_provider_reference_must_use_same_inventory_generation() -> None:
    provider_ref = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example-rg/providers/"
        "Microsoft.ContainerService/managedClusters/example-aks"
    )
    store = StubStore(
        (_resource("logical-aks", "kubernetes-cluster"),),
        source_generation="generation-2",
    )
    reader = StubProviderReferenceReader(
        {
            "logical-aks": ResourceRecord(
                resource_id="logical-aks",
                type="kubernetes-cluster",
                provider_ref=provider_ref,
            )
        },
        snapshot_id="generation-1",
    )

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="generation changed during target resolution",
    ):
        await _resolve(
            store,
            configured=(
                AnalyzerTarget(
                    resource_ref="logical-aks",
                    resource_kind="aks_cluster",
                    provider_query_ref=provider_ref,
                ),
            ),
            provider_references=reader,
        )


@pytest.mark.asyncio
async def test_unbound_legacy_arm_target_requires_separate_identities() -> None:
    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="MUST separate logical resource_id and provider_resource_id",
    ):
        await _resolve(
            None,
            configured=(
                AnalyzerTarget(
                    resource_ref=(
                        "/subscriptions/00000000-0000-0000-0000-000000000000/"
                        "resourceGroups/example-rg/providers/"
                        "Microsoft.ContainerService/managedClusters/example-aks"
                    ),
                    resource_kind="aks_cluster",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_unbound_explicit_target_accepts_separate_identities() -> None:
    target = AnalyzerTarget(
        resource_ref="logical-aks",
        resource_kind="aks_cluster",
        provider_query_ref=(
            "/subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/example-rg/providers/"
            "Microsoft.ContainerService/managedClusters/example-aks"
        ),
    )

    resolution = await _resolve(None, configured=(target,))

    assert resolution.targets == (target,)


@pytest.mark.asyncio
async def test_unbound_non_metric_target_does_not_require_provider_identity() -> None:
    target = AnalyzerTarget(
        resource_ref="scenario/pod-uid",
        resource_kind="kubernetes_pod",
    )

    resolution = await _resolve(None, configured=(target,))

    assert resolution.targets == (target,)


@pytest.mark.asyncio
async def test_configured_target_kind_must_match_its_inventory_resource_type() -> None:
    store = StubStore((_resource("res-aks", "kubernetes-cluster"),))

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="configured analyzer kind conflicts",
    ):
        await _resolve(
            store,
            configured=(
                AnalyzerTarget(
                    resource_ref="res-aks",
                    resource_kind="mysql_flexible_server",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_configured_target_uses_provider_identity_despite_stale_state() -> None:
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact=_state_fact(observed_at=NOW - timedelta(seconds=301)),
            ),
        )
    )

    resolution = await _resolve(
        store,
        configured=(AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),),
    )

    assert resolution.targets[0].provider_query_ref == ("/providers/example/resources/res-aks")
    assert resolution.discovered == 0
    assert resolution.skipped_reasons == (SKIP_STALE_STATE_FACT,)


@pytest.mark.asyncio
async def test_resolution_is_deterministic_across_projection_ordering() -> None:
    records = (
        _resource("res-b", "kubernetes-cluster", state_fact=_state_fact()),
        _resource("res-a", "mysql-server", state_fact=_state_fact()),
        _resource("res-c", "llm-endpoint", state_fact=_state_fact()),
    )

    first = await _resolve(StubStore(records))
    second = await _resolve(StubStore(tuple(reversed(records))))

    assert first.targets == second.targets
    assert [item.resource_ref for item in first.targets] == ["res-a", "res-b", "res-c"]


# ---------------------------------------------------------------------------
# Fail-closed selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unmapped_and_malformed_resources_are_skipped_with_reasons() -> None:
    malformed = OntologyObjectRecord(
        id="res-broken",
        object_type="Resource",
        properties={"id": "  ", "type": "kubernetes-cluster"},
    )
    store = StubStore(
        (
            _resource("res-disk", "disk", state_fact=_state_fact()),
            malformed,
        ),
        honor_property_filter=False,
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (
        SKIP_MALFORMED_RESOURCE,
        SKIP_UNMAPPED_RESOURCE_TYPE,
    )
    assert resolution.candidate_count == 2
    assert dict(resolution.skipped_reason_counts) == {
        SKIP_MALFORMED_RESOURCE: 1,
        SKIP_UNMAPPED_RESOURCE_TYPE: 1,
    }


@pytest.mark.asyncio
async def test_stale_conflicting_and_synthetic_evidence_is_skipped() -> None:
    store = StubStore(
        (
            _resource(
                "res-stale",
                "kubernetes-cluster",
                state_fact=_state_fact(observed_at=NOW - timedelta(seconds=601)),
            ),
            _resource(
                "res-conflict",
                "mysql-server",
                state_fact=_state_fact(conflicts=("status",)),
            ),
            _resource(
                "res-synthetic",
                "llm-endpoint",
                state_fact=_state_fact(synthetic=True),
            ),
            _resource(
                "res-partial",
                "api-gateway",
                state_fact=_state_fact(completeness=0.5),
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (
        SKIP_STALE_STATE_FACT,
        SKIP_UNUSABLE_STATE_FACT,
    )
    assert resolution.candidate_count == 4
    assert dict(resolution.skipped_reason_counts) == {
        SKIP_STALE_STATE_FACT: 1,
        SKIP_UNUSABLE_STATE_FACT: 3,
    }


@pytest.mark.asyncio
async def test_malformed_state_fact_evidence_is_skipped() -> None:
    store = StubStore(
        (
            _resource(
                "res-aks",
                "kubernetes-cluster",
                state_fact={"lane": "observed"},
            ),
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (SKIP_UNUSABLE_STATE_FACT,)


@pytest.mark.asyncio
async def test_a_projection_read_failure_fails_closed_instead_of_degrading() -> None:
    store = StubStore(error=RuntimeError("connection refused"))

    with pytest.raises(AnalyzerTargetResolutionError):
        await _resolve(
            store,
            configured=(AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),),
        )


@pytest.mark.asyncio
async def test_a_provider_identity_read_failure_fails_the_complete_tick() -> None:
    store = StubStore((_resource("res-aks", "kubernetes-cluster"),))
    reader = StubProviderReferenceReader({}, error=RuntimeError("connection refused"))

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="provider identity read failed",
    ):
        await _resolve(store, provider_references=reader)


@pytest.mark.parametrize(
    "reader",
    (
        StubProviderReferenceReader({}),
        StubProviderReferenceReader(
            {
                "res-aks": ResourceRecord(
                    resource_id="res-aks",
                    type="kubernetes-cluster",
                    provider_ref=None,
                )
            }
        ),
        StubProviderReferenceReader(
            {
                "res-aks": ResourceRecord(
                    resource_id="res-aks",
                    type="mysql-server",
                    provider_ref="/providers/example/resources/res-aks",
                )
            }
        ),
    ),
)
@pytest.mark.asyncio
async def test_missing_or_mismatched_provider_identity_fails_closed(
    reader: StubProviderReferenceReader,
) -> None:
    store = StubStore((_resource("res-aks", "kubernetes-cluster"),))

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="does not match eligible analyzer targets",
    ):
        await _resolve(store, provider_references=reader)


@pytest.mark.asyncio
async def test_case_variant_provider_aliases_fail_closed() -> None:
    store = StubStore(
        (
            _resource("res-a", "kubernetes-cluster"),
            _resource("res-b", "kubernetes-cluster"),
        )
    )
    reader = StubProviderReferenceReader(
        {
            "res-a": ResourceRecord(
                resource_id="res-a",
                type="kubernetes-cluster",
                provider_ref="/subscriptions/example/resourceGroups/rg/providers/example/a",
            ),
            "res-b": ResourceRecord(
                resource_id="res-b",
                type="kubernetes-cluster",
                provider_ref="/SUBSCRIPTIONS/EXAMPLE/RESOURCEGROUPS/RG/PROVIDERS/EXAMPLE/A",
            ),
        }
    )

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="ambiguous across analyzer targets",
    ):
        await _resolve(store, provider_references=reader)


@pytest.mark.asyncio
async def test_an_inventory_projection_requires_its_provider_identity_reader() -> None:
    store = StubStore((_resource("res-aks", "kubernetes-cluster"),))

    with pytest.raises(
        AnalyzerTargetResolutionError,
        match="reader is unavailable",
    ):
        await _resolve(store, bind_provider_references=False)


# ---------------------------------------------------------------------------
# Bounds and degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unbound_projection_keeps_the_configured_list() -> None:
    configured = (
        AnalyzerTarget(
            resource_ref="res-aks",
            resource_kind="aks_cluster",
            provider_query_ref="/providers/example/resources/res-aks",
        ),
    )

    resolution = await _resolve(None, configured=configured)

    assert resolution.targets == configured
    assert resolution.inventory_consulted is False
    assert resolution.discovered == 0


@pytest.mark.asyncio
async def test_discovered_targets_are_bounded_and_report_truncation() -> None:
    records = tuple(
        _resource(f"res-{index:02d}", "kubernetes-cluster", state_fact=_state_fact())
        for index in range(5)
    )
    store = StubStore(records)

    resolution = await _resolve(store, max_discovered=2)

    assert store.limits == [INVENTORY_SCAN_LIMIT]
    assert [item.resource_ref for item in resolution.targets] == ["res-00", "res-01"]
    assert resolution.truncated is True


@pytest.mark.asyncio
async def test_incomplete_inventory_source_is_preserved_in_resolution() -> None:
    store = StubStore(
        (_resource("res-00", "kubernetes-cluster", state_fact=_state_fact()),),
        source_complete=False,
    )

    resolution = await _resolve(store)

    assert resolution.source_complete is False


@pytest.mark.asyncio
async def test_withheld_targets_do_not_require_provider_identity_reads() -> None:
    store = StubStore(
        (
            _resource("res-00", "kubernetes-cluster", state_fact=_state_fact()),
            _resource("res-01", "mysql-server", state_fact=_state_fact()),
        )
    )
    reader = StubProviderReferenceReader(
        {
            "res-00": ResourceRecord(
                resource_id="res-00",
                type="kubernetes-cluster",
                provider_ref="/providers/example/resources/res-00",
            )
        }
    )

    resolution = await _resolve(
        store,
        max_discovered=1,
        provider_references=reader,
    )

    assert [item.resource_ref for item in resolution.targets] == ["res-00"]
    assert reader.requests == [("res-00",)]
    assert resolution.truncated is True


@pytest.mark.asyncio
async def test_configured_duplicates_do_not_report_false_truncation() -> None:
    configured = (AnalyzerTarget(resource_ref="res-01", resource_kind="aks_cluster"),)
    store = StubStore(
        (
            _resource("res-00", "mysql-server", state_fact=_state_fact()),
            _resource("res-01", "kubernetes-cluster", state_fact=_state_fact()),
        )
    )

    resolution = await _resolve(
        store,
        configured=configured,
        max_discovered=1,
    )

    assert [item.resource_ref for item in resolution.targets] == ["res-01", "res-00"]
    assert resolution.truncated is False


@pytest.mark.asyncio
async def test_unmapped_resources_do_not_starve_later_supported_targets() -> None:
    records = (
        *(
            _resource(f"res-unmapped-{index:04d}", "disk", state_fact=_state_fact())
            for index in range(INVENTORY_SCAN_LIMIT + 250)
        ),
        _resource("res-supported-1", "kubernetes-cluster", state_fact=_state_fact()),
        _resource("res-supported-2", "mysql-server", state_fact=_state_fact()),
    )
    store = StubStore(records)

    resolution = await _resolve(store, max_discovered=2)

    assert store.limits == [INVENTORY_SCAN_LIMIT]
    assert store.property_text_filters == [
        {
            "type": (
                "api-gateway",
                "kubernetes-cluster",
                "llm-endpoint",
                "mysql-server",
                "network.application-gateway",
            )
        }
    ]
    assert [item.resource_ref for item in resolution.targets] == [
        "res-supported-1",
        "res-supported-2",
    ]
    assert resolution.truncated is False
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_naive_now_and_out_of_range_bounds_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await _resolve(None, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="max_discovered"):
        await _resolve(None, max_discovered=0)


@pytest.mark.asyncio
async def test_the_bound_stays_inside_the_durable_store_query_limit() -> None:
    store = StubStore()

    await _resolve(store, max_discovered=999)

    assert store.limits == [INVENTORY_SCAN_LIMIT]
    with pytest.raises(ValueError, match="max_discovered"):
        await _resolve(store, max_discovered=1000)


@pytest.mark.asyncio
async def test_a_naive_evidence_cutoff_is_an_unusable_state_fact() -> None:
    naive = dict(_state_fact())
    for field in ("effective_at", "recorded_at", "evidence_cutoff"):
        naive[field] = "2026-08-16T12:00:00"
    store = StubStore([_resource("res-naive", "api-gateway", state_fact=naive)])

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (SKIP_UNUSABLE_STATE_FACT,)

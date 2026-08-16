"""Analyzer target resolution from configuration and the durable inventory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.analyzer_targets import (
    SKIP_MALFORMED_RESOURCE,
    SKIP_STALE_STATE_FACT,
    SKIP_UNMAPPED_RESOURCE_TYPE,
    SKIP_UNUSABLE_STATE_FACT,
    AnalyzerTargetResolutionError,
    resolve_analyzer_targets,
)
from fdai.delivery.analyzer_tick import AnalyzerTarget
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
        error: Exception | None = None,
    ) -> None:
        self._objects = tuple(objects)
        self._truncated = truncated
        self._error = error
        self.limits: list[int] = []

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        del property_equals
        assert tuple(object_types) == ("Resource",)
        self.limits.append(limit)
        if self._error is not None:
            raise self._error
        return OntologyGraphSnapshot(objects=self._objects, truncated=self._truncated)


async def _resolve(
    store: StubStore | None,
    *,
    configured: Sequence[AnalyzerTarget] = (),
    now: datetime = NOW,
    max_discovered: int = 200,
):
    return await resolve_analyzer_targets(
        configured=configured,
        store=store,  # type: ignore[arg-type]
        now=now,
        max_discovered=max_discovered,
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
    assert resolution.skipped_reasons == ()


@pytest.mark.asyncio
async def test_a_resource_without_a_state_fact_is_still_selectable() -> None:
    store = StubStore((_resource("res-apim", "api-gateway"),))

    resolution = await _resolve(store)

    assert resolution.targets == (
        AnalyzerTarget(resource_ref="res-apim", resource_kind="api_management"),
    )
    assert resolution.skipped_reasons == ()


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
    assert [item.resource_ref for item in resolution.targets] == ["res-aks", "res-gw"]
    assert resolution.configured == 1
    assert resolution.discovered == 1


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
        )
    )

    resolution = await _resolve(store)

    assert resolution.targets == ()
    assert resolution.skipped_reasons == (
        SKIP_MALFORMED_RESOURCE,
        SKIP_UNMAPPED_RESOURCE_TYPE,
    )


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


# ---------------------------------------------------------------------------
# Bounds and degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unbound_projection_keeps_the_configured_list() -> None:
    configured = (AnalyzerTarget(resource_ref="res-aks", resource_kind="aks_cluster"),)

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

    assert store.limits == [3]
    assert [item.resource_ref for item in resolution.targets] == ["res-00", "res-01"]
    assert resolution.truncated is True


@pytest.mark.asyncio
async def test_naive_now_and_out_of_range_bounds_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await _resolve(None, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="max_discovered"):
        await _resolve(None, max_discovered=0)

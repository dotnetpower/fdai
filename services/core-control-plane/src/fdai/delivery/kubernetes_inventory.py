"""Enrich one complete provider generation with Kubernetes runtime topology."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Protocol

from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    InventoryPromotionEnricher,
    PromotedInventoryObservation,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot
from fdai.delivery.kubernetes_relationships import project_kubernetes_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)

KUBERNETES_INVENTORY_SOURCE_NAME = "kubernetes_runtime_inventory"

_LOGGER = logging.getLogger(__name__)
_KUBERNETES_CLUSTER_TYPE = "kubernetes-cluster"


class KubernetesRuntimeInventorySource(Protocol):
    """Collect one complete Kubernetes runtime generation."""

    async def collect(self) -> KubernetesApiInventorySnapshot: ...


class SequentialInventoryPromotionEnricher:
    """Apply independent enrichers serially while preserving their source states."""

    def __init__(self, *enrichers: InventoryPromotionEnricher) -> None:
        if not enrichers:
            raise ValueError("sequential inventory enrichment requires at least one enricher")
        self._enrichers = enrichers

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        current = observation
        for enricher in self._enrichers:
            previous = current
            current = await enricher.enrich(current)
            if previous.state_base_generation_checked and (
                not current.state_base_generation_checked
                or current.state_base_generation != previous.state_base_generation
            ):
                raise ValueError(
                    "sequential inventory enrichment MUST preserve the pinned state generation"
                )
        return current


class UnavailableKubernetesInventoryEnricher:
    """Record explicit unavailability when no Kubernetes source is configured."""

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        clusters = sum(
            1 for resource in observation.resources if resource.type == _KUBERNETES_CLUSTER_TYPE
        )
        if clusters:
            # Silent degradation here reads as an empty cluster rather than a missing source.
            _LOGGER.warning(
                "kubernetes_runtime_source_unconfigured_for_observed_clusters",
                extra={
                    "generation": observation.generation,
                    "observed_cluster_count": clusters,
                },
            )
        return _unavailable(observation, reason="kubernetes_source_unconfigured")


class KubernetesInventoryEnricher:
    """Add complete UID-grounded runtime objects and independently verified links."""

    def __init__(
        self,
        *,
        source: KubernetesRuntimeInventorySource,
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog,
    ) -> None:
        self._source = source
        self._relationship_mapping_catalog = relationship_mapping_catalog

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        if not observation.complete:
            return _unavailable(observation, reason="inventory_generation_incomplete")
        cluster_ids = {
            resource.resource_id
            for resource in observation.resources
            if resource.type == "kubernetes-cluster"
        }
        if not cluster_ids:
            return _unavailable(observation, reason="cluster_identity_unavailable")
        try:
            snapshot = await self._source.collect()
        except Exception:  # noqa: BLE001 - source details never enter generation metadata
            return _unavailable(observation, reason="kubernetes_source_unavailable")
        cluster_refs = {
            resource.props.get("cluster_ref")
            for resource in snapshot.resources
            if isinstance(resource.props.get("cluster_ref"), str)
        }
        if len(cluster_refs) != 1 or not cluster_refs <= cluster_ids:
            return _unavailable(observation, reason="cluster_identity_mismatch")

        combined_resources = (*observation.resources, *snapshot.resources)
        projected = project_kubernetes_relationships(
            combined_resources,
            catalog=self._relationship_mapping_catalog,
            complete=True,
        )
        verified = verify_inventory_relationships(
            generation=observation.generation,
            resources=combined_resources,
            links=projected.links,
            complete=True,
            recorded_at=snapshot.observed_at,
            upstream_drops=projected.dropped,
        )
        existing_resource_ids = {resource.resource_id for resource in observation.resources}
        if any(resource.resource_id in existing_resource_ids for resource in snapshot.resources):
            return _unavailable(observation, reason="kubernetes_resource_identity_conflict")
        existing_link_ids = {
            (link.from_id, link.link_type, link.to_id) for link in observation.links
        }
        if any(
            (link.from_id, link.link_type, link.to_id) in existing_link_ids
            for link in verified.links
        ):
            return _unavailable(observation, reason="kubernetes_relationship_identity_conflict")
        relationship_drops = (*observation.relationship_drops, *verified.dropped)
        if verified.dropped:
            # Keep independently verified records that are usable while making
            # each unresolved endpoint visible as incomplete evidence.
            return replace(
                observation,
                resources=combined_resources,
                links=(*observation.links, *verified.links),
                relationship_drops=relationship_drops,
                source_states=(
                    *observation.source_states,
                    InventoryProjectionSourceState(
                        source=KUBERNETES_INVENTORY_SOURCE_NAME,
                        status=InventoryProjectionSourceStatus.UNAVAILABLE,
                        observed_at=None,
                        reason="kubernetes_relationship_incomplete",
                    ),
                ),
            )
        return replace(
            observation,
            resources=combined_resources,
            links=(*observation.links, *verified.links),
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=KUBERNETES_INVENTORY_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.AVAILABLE,
                    observed_at=snapshot.observed_at,
                    reason=None,
                ),
            ),
        )


def _unavailable(
    observation: PromotedInventoryObservation,
    *,
    reason: str,
) -> PromotedInventoryObservation:
    return replace(
        observation,
        source_states=(
            *observation.source_states,
            InventoryProjectionSourceState(
                source=KUBERNETES_INVENTORY_SOURCE_NAME,
                status=InventoryProjectionSourceStatus.UNAVAILABLE,
                observed_at=None,
                reason=reason,
            ),
        ),
    )


__all__ = [
    "KUBERNETES_INVENTORY_SOURCE_NAME",
    "KubernetesInventoryEnricher",
    "KubernetesRuntimeInventorySource",
    "SequentialInventoryPromotionEnricher",
    "UnavailableKubernetesInventoryEnricher",
]

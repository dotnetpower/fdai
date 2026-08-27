"""Kubernetes runtime inventory enrichment tests."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot
from fdai.delivery.kubernetes_inventory import (
    KubernetesInventoryEnricher,
    UnavailableKubernetesInventoryEnricher,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import ResourceRecord

CATALOG_ROOT = Path("rule-catalog/vocabulary/provider-relationship-mappings")
OBSERVED_AT = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
CLUSTER_ID = "scope-example/resource-group/rg-example/providers/containerservice/aks-example"
NODE_POOL_ID = f"{CLUSTER_ID}/agent-pools/system"


class _Source:
    def __init__(self, snapshot: KubernetesApiInventorySnapshot) -> None:
        self._snapshot = snapshot

    async def collect(self) -> KubernetesApiInventorySnapshot:
        return self._snapshot


def _resource(resource_id: str, type_id: str, props: dict[str, object]) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        type=type_id,
        props=props,
        last_seen=OBSERVED_AT.isoformat(),
    )


def _observation() -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation="generation-1",
        resources=(
            _resource(
                CLUSTER_ID,
                "kubernetes-cluster",
                {"cluster_ref": CLUSTER_ID, "name": "aks-example"},
            ),
            _resource(
                NODE_POOL_ID,
                "kubernetes-node-pool",
                {"cluster_ref": CLUSTER_ID, "name": "system"},
            ),
        ),
        links=(),
        complete=True,
        relationship_drops=(),
        recorded_at=OBSERVED_AT,
    )


def _snapshot(*, cluster_ref: str = CLUSTER_ID) -> KubernetesApiInventorySnapshot:
    namespace_id = f"{cluster_ref}/kubernetes/kubernetes.namespace/_cluster/ns"
    node_id = f"{cluster_ref}/kubernetes/kubernetes.node/_cluster/node"
    pod_id = f"{cluster_ref}/kubernetes/kubernetes.pod/default/pod"
    return KubernetesApiInventorySnapshot(
        resources=tuple(
            sorted(
                (
                    _resource(
                        namespace_id,
                        "kubernetes.namespace",
                        {
                            "cluster_ref": cluster_ref,
                            "name": "default",
                            "namespace": "default",
                            "uid": "uid-namespace",
                        },
                    ),
                    _resource(
                        node_id,
                        "kubernetes.node",
                        {
                            "cluster_ref": cluster_ref,
                            "name": "node-1",
                            "node_pool": "system",
                            "uid": "uid-node",
                        },
                    ),
                    _resource(
                        pod_id,
                        "kubernetes.pod",
                        {
                            "cluster_ref": cluster_ref,
                            "namespace": "default",
                            "name": "pod-1",
                            "node_name": "node-1",
                            "uid": "uid-pod",
                        },
                    ),
                ),
                key=lambda resource: resource.resource_id,
            )
        ),
        observed_at=OBSERVED_AT,
    )


async def test_adds_runtime_resources_and_verified_relationships() -> None:
    result = await KubernetesInventoryEnricher(
        source=_Source(_snapshot()),
        relationship_mapping_catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
    ).enrich(_observation())

    assert len(result.resources) == 5
    edges = {(link.from_type, link.link_type, link.to_type) for link in result.links}
    assert ("kubernetes-cluster", "contains", "kubernetes.namespace") in edges
    assert ("kubernetes-node-pool", "contains", "kubernetes.node") in edges
    assert ("kubernetes.namespace", "contains", "kubernetes.pod") in edges
    assert ("kubernetes.pod", "kubernetes_scheduled_on", "kubernetes.node") in edges
    assert all(
        link.observation_metadata is not None and link.observation_metadata.verified
        for link in result.links
    )
    assert result.source_states[-1].status is InventoryProjectionSourceStatus.AVAILABLE


async def test_retains_observed_resources_when_one_relationship_endpoint_is_unavailable() -> None:
    snapshot = _snapshot()
    without_node = KubernetesApiInventorySnapshot(
        resources=tuple(
            resource for resource in snapshot.resources if resource.type != "kubernetes.node"
        ),
        observed_at=snapshot.observed_at,
    )

    result = await KubernetesInventoryEnricher(
        source=_Source(without_node),
        relationship_mapping_catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
    ).enrich(_observation())

    assert {resource.type for resource in result.resources} == {
        "kubernetes-cluster",
        "kubernetes-node-pool",
        "kubernetes.namespace",
        "kubernetes.pod",
    }
    assert any(link.link_type == "contains" for link in result.links)
    assert result.source_states[-1].status is InventoryProjectionSourceStatus.UNAVAILABLE
    assert result.source_states[-1].reason == "kubernetes_relationship_incomplete"
    assert any(
        drop.mapping_id == "kubernetes.pod-scheduled-on-node" for drop in result.relationship_drops
    )


async def test_cluster_identity_mismatch_preserves_provider_generation() -> None:
    original = _observation()
    result = await KubernetesInventoryEnricher(
        source=_Source(_snapshot(cluster_ref="scope-example/foreign-cluster")),
        relationship_mapping_catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
    ).enrich(original)

    assert result.resources == original.resources
    assert result.links == original.links
    assert result.source_states[-1].status is InventoryProjectionSourceStatus.UNAVAILABLE
    assert result.source_states[-1].reason == "cluster_identity_mismatch"


async def test_unconfigured_source_reports_the_clusters_it_leaves_unobserved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="fdai.delivery.kubernetes_inventory"):
        result = await UnavailableKubernetesInventoryEnricher().enrich(_observation())

    assert result.source_states[-1].reason == "kubernetes_source_unconfigured"
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "kubernetes_runtime_source_unconfigured_for_observed_clusters"
    ]
    assert [record.observed_cluster_count for record in records] == [1]  # type: ignore[attr-defined]


async def test_unconfigured_source_stays_quiet_without_an_observed_cluster(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observation = _observation()
    without_cluster = replace(
        observation,
        resources=tuple(
            resource for resource in observation.resources if resource.type != "kubernetes-cluster"
        ),
    )

    with caplog.at_level(logging.WARNING, logger="fdai.delivery.kubernetes_inventory"):
        result = await UnavailableKubernetesInventoryEnricher().enrich(without_cluster)

    assert result.source_states[-1].reason == "kubernetes_source_unconfigured"
    assert caplog.records == []

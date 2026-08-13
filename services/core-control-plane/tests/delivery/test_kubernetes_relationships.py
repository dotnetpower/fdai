"""Adversarial Kubernetes relationship projection fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.delivery.kubernetes_relationships import project_kubernetes_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import RelationshipDropReason, ResourceRecord

CATALOG_ROOT = Path("rule-catalog/vocabulary/provider-relationship-mappings")
OBSERVED_AT = "2026-08-13T10:00:00Z"
CLUSTER_REF = "kubernetes.cluster:example"
SERVICE_ID = f"{CLUSTER_REF}/resource/service-api"
POD_ID = f"{CLUSTER_REF}/resource/pod-api-0"
ENDPOINTS_ID = f"{CLUSTER_REF}/resource/endpoints-api"


def _resource(
    resource_id: str,
    type_id: str,
    *,
    name: str,
    labels: dict[str, str] | None = None,
    selector: dict[str, str] | None = None,
) -> ResourceRecord:
    props: dict[str, object] = {
        "cluster_ref": CLUSTER_REF,
        "namespace": "default",
        "name": name,
    }
    if labels is not None:
        props["labels"] = labels
    if selector is not None:
        props["selector"] = selector
    return ResourceRecord(
        resource_id=resource_id,
        type=type_id,
        props=props,
        last_seen=OBSERVED_AT,
    )


def _resources() -> tuple[ResourceRecord, ...]:
    return (
        _resource(
            SERVICE_ID,
            "kubernetes.service",
            name="api",
            selector={"app": "api"},
        ),
        _resource(
            POD_ID,
            "kubernetes.pod",
            name="api-0",
            labels={"app": "api"},
        ),
        _resource(ENDPOINTS_ID, "kubernetes.endpoints", name="api"),
    )


def test_complete_snapshot_projects_canonical_kubernetes_relationships() -> None:
    result = project_kubernetes_relationships(
        _resources(),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.dropped == ()
    assert [(link.from_id, link.link_type, link.to_id) for link in result.links] == [
        (SERVICE_ID, "kubernetes_exposes_endpoints", ENDPOINTS_ID),
        (SERVICE_ID, "kubernetes_selects", POD_ID),
    ]
    assert all(link.mapping_evidence is not None for link in result.links)


def test_reversed_snapshot_input_preserves_canonical_direction() -> None:
    catalog = load_provider_relationship_mapping_catalog(CATALOG_ROOT)

    forward = project_kubernetes_relationships(_resources(), catalog=catalog, complete=True)
    reversed_input = project_kubernetes_relationships(
        tuple(reversed(_resources())),
        catalog=catalog,
        complete=True,
    )

    assert reversed_input == forward


def test_missing_endpoints_is_absent_and_reported() -> None:
    result = project_kubernetes_relationships(
        _resources()[:-1],
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert [(link.link_type, link.to_id) for link in result.links] == [
        ("kubernetes_selects", POD_ID)
    ]
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        (
            "kubernetes.service-exposes-endpoints",
            RelationshipDropReason.MISSING_TARGET_ENDPOINT,
        )
    ]


def test_duplicate_selected_pod_edge_fails_closed() -> None:
    service, pod, endpoints = _resources()
    result = project_kubernetes_relationships(
        (service, pod, pod, endpoints),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert [(link.link_type, link.to_id) for link in result.links] == [
        ("kubernetes_exposes_endpoints", ENDPOINTS_ID)
    ]
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        ("kubernetes.service-selects-pod", RelationshipDropReason.DUPLICATE_EDGE)
    ]


def test_partial_snapshot_claims_no_kubernetes_relationships() -> None:
    result = project_kubernetes_relationships(
        _resources(),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=False,
    )

    assert result.links == ()
    assert [drop.reason for drop in result.dropped] == [RelationshipDropReason.PARTIAL_GENERATION]


def test_complete_candidates_require_independent_generation_verification() -> None:
    resources = _resources()
    projected = project_kubernetes_relationships(
        resources,
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    verified = verify_inventory_relationships(
        generation="kubernetes-generation-1",
        resources=resources,
        links=projected.links,
        complete=True,
        recorded_at=datetime(2026, 8, 13, 10, 1, tzinfo=UTC),
        upstream_drops=projected.dropped,
    )

    assert verified.dropped == ()
    assert len(verified.links) == 2
    assert all(
        link.observation_metadata is not None and link.observation_metadata.verified
        for link in verified.links
    )

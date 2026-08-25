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
NAMESPACE_ID = f"{CLUSTER_REF}/namespace/default"
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
    extra: dict[str, object] | None = None,
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
    if extra is not None:
        props.update(extra)
    return ResourceRecord(
        resource_id=resource_id,
        type=type_id,
        props=props,
        last_seen=OBSERVED_AT,
    )


def _resources() -> tuple[ResourceRecord, ...]:
    return (
        ResourceRecord(
            resource_id=CLUSTER_REF,
            type="kubernetes-cluster",
            props={"cluster_ref": CLUSTER_REF, "name": "example"},
            last_seen=OBSERVED_AT,
        ),
        _resource(NAMESPACE_ID, "kubernetes.namespace", name="default"),
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
        (CLUSTER_REF, "contains", NAMESPACE_ID),
        (NAMESPACE_ID, "contains", ENDPOINTS_ID),
        (NAMESPACE_ID, "contains", POD_ID),
        (NAMESPACE_ID, "contains", SERVICE_ID),
        (SERVICE_ID, "kubernetes_exposes_endpoints", ENDPOINTS_ID),
        (SERVICE_ID, "kubernetes_selects", POD_ID),
    ]
    assert all(link.mapping_evidence is not None for link in result.links)


def test_complete_snapshot_projects_ingress_and_endpoint_slice_relationships() -> None:
    ingress_class_id = f"{CLUSTER_REF}/resource/ingress-class-web"
    ingress_id = f"{CLUSTER_REF}/resource/ingress-api"
    endpoint_slice_id = f"{CLUSTER_REF}/resource/endpoint-slice-api"
    resources = (
        *_resources(),
        ResourceRecord(
            resource_id=ingress_class_id,
            type="kubernetes.ingress-class",
            props={
                "cluster_ref": CLUSTER_REF,
                "name": "web",
                "uid": "uid-ingress-class",
            },
            last_seen=OBSERVED_AT,
        ),
        _resource(
            ingress_id,
            "kubernetes.ingress",
            name="api",
            extra={
                "uid": "uid-ingress",
                "backend_service_names": ("api",),
                "ingress_class_name": "web",
            },
        ),
        _resource(
            endpoint_slice_id,
            "kubernetes.endpoint-slice",
            name="api-abcd",
            extra={"uid": "uid-endpoint-slice", "service_name": "api"},
        ),
    )

    result = project_kubernetes_relationships(
        resources,
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.dropped == ()
    edges = {(link.from_id, link.link_type, link.to_id) for link in result.links}
    assert (CLUSTER_REF, "contains", ingress_class_id) in edges
    assert (NAMESPACE_ID, "contains", ingress_id) in edges
    assert (NAMESPACE_ID, "contains", endpoint_slice_id) in edges
    assert (ingress_id, "routes_to", SERVICE_ID) in edges
    assert (ingress_id, "attached_to", ingress_class_id) in edges
    assert (SERVICE_ID, "kubernetes_exposes_endpoint_slice", endpoint_slice_id) in edges


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
        ("contains", NAMESPACE_ID),
        ("contains", POD_ID),
        ("contains", SERVICE_ID),
        ("kubernetes_selects", POD_ID),
    ]
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        (
            "kubernetes.service-exposes-endpoints",
            RelationshipDropReason.MISSING_TARGET_ENDPOINT,
        )
    ]


def test_duplicate_selected_pod_edge_fails_closed() -> None:
    cluster, namespace, service, pod, endpoints = _resources()
    result = project_kubernetes_relationships(
        (cluster, namespace, service, pod, pod, endpoints),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert [(link.link_type, link.to_id) for link in result.links] == [
        ("contains", NAMESPACE_ID),
        ("contains", ENDPOINTS_ID),
        ("contains", SERVICE_ID),
        ("kubernetes_exposes_endpoints", ENDPOINTS_ID),
    ]
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        ("kubernetes.namespace-contains-resource", RelationshipDropReason.DUPLICATE_EDGE),
        ("kubernetes.service-selects-pod", RelationshipDropReason.DUPLICATE_EDGE),
    ]


def test_service_selector_never_crosses_namespace() -> None:
    cluster, namespace, service, pod, endpoints = _resources()
    cross_namespace_pod = ResourceRecord(
        resource_id=f"{CLUSTER_REF}/resource/pod-api-other",
        type="kubernetes.pod",
        props={
            "cluster_ref": CLUSTER_REF,
            "namespace": "other",
            "name": "api-other",
            "labels": {"app": "api"},
        },
        last_seen=OBSERVED_AT,
    )

    result = project_kubernetes_relationships(
        (cluster, namespace, service, pod, cross_namespace_pod, endpoints),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    selected = [link.to_id for link in result.links if link.link_type == "kubernetes_selects"]
    assert selected == [POD_ID]


def test_partial_snapshot_claims_no_kubernetes_relationships() -> None:
    result = project_kubernetes_relationships(
        _resources(),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=False,
    )

    assert result.links == ()
    assert [drop.reason for drop in result.dropped] == [RelationshipDropReason.PARTIAL_GENERATION]


def test_complete_snapshot_projects_runtime_scheduling_and_owner_lineage() -> None:
    node_pool_id = f"{CLUSTER_REF}/agent-pool/system"
    node_id = f"{CLUSTER_REF}/node/node-1"
    vm_id = f"{CLUSTER_REF}/vmss/system/virtual-machine/0"
    vm_provider_ref = (
        "/subscriptions/subscription-example/resourceGroups/rg-example/providers/"
        "Microsoft.Compute/virtualMachineScaleSets/vmss-example/virtualMachines/0"
    )
    cron_job_id = f"{CLUSTER_REF}/resource/cron-job-nightly"
    job_id = f"{CLUSTER_REF}/resource/job-nightly-1"
    deployment_id = f"{CLUSTER_REF}/resource/deployment-api"
    replica_set_id = f"{CLUSTER_REF}/resource/replica-set-api"
    pod_id = f"{CLUSTER_REF}/resource/pod-api"
    resources = (
        ResourceRecord(
            resource_id=CLUSTER_REF,
            type="kubernetes-cluster",
            props={"cluster_ref": CLUSTER_REF, "name": "example"},
            last_seen=OBSERVED_AT,
        ),
        _resource(NAMESPACE_ID, "kubernetes.namespace", name="default"),
        ResourceRecord(
            resource_id=node_pool_id,
            type="kubernetes-node-pool",
            props={"cluster_ref": CLUSTER_REF, "name": "system"},
            last_seen=OBSERVED_AT,
        ),
        ResourceRecord(
            resource_id=node_id,
            type="kubernetes.node",
            props={
                "cluster_ref": CLUSTER_REF,
                "name": "node-1",
                "node_pool": "system",
                "provider_resource_ref": vm_provider_ref,
                "uid": "uid-node-1",
            },
            last_seen=OBSERVED_AT,
        ),
        ResourceRecord(
            resource_id=vm_id,
            type="compute.vm",
            props={"name": "unrelated-display-name"},
            provider_ref=vm_provider_ref,
            last_seen=OBSERVED_AT,
        ),
        _resource(
            cron_job_id,
            "kubernetes.cron-job",
            name="nightly",
            extra={"uid": "uid-cron-job"},
        ),
        _resource(
            job_id,
            "kubernetes.job",
            name="nightly-1",
            extra={"uid": "uid-job", "owner_uids": ("uid-cron-job",)},
        ),
        _resource(
            deployment_id,
            "kubernetes.deployment",
            name="api",
            extra={"uid": "uid-deployment"},
        ),
        _resource(
            replica_set_id,
            "kubernetes.replica-set",
            name="api-123",
            extra={"uid": "uid-replica-set", "owner_uids": ("uid-deployment",)},
        ),
        _resource(
            pod_id,
            "kubernetes.pod",
            name="api-123-abc",
            extra={
                "uid": "uid-pod",
                "node_name": "node-1",
                "owner_uids": ("uid-replica-set",),
            },
        ),
    )

    result = project_kubernetes_relationships(
        resources,
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.dropped == ()
    edges = {(link.from_id, link.link_type, link.to_id) for link in result.links}
    assert (node_pool_id, "contains", node_id) in edges
    assert (node_id, "kubernetes_backed_by", vm_id) in edges
    assert (pod_id, "kubernetes_scheduled_on", node_id) in edges
    assert (job_id, "kubernetes_owned_by", cron_job_id) in edges
    assert (replica_set_id, "kubernetes_owned_by", deployment_id) in edges
    assert (pod_id, "kubernetes_owned_by", replica_set_id) in edges


def test_runtime_owner_uid_does_not_cross_cluster() -> None:
    owner = _resource(
        f"{CLUSTER_REF}/resource/job-example",
        "kubernetes.job",
        name="example",
        extra={"uid": "shared-owner-uid"},
    )
    foreign_cluster = "kubernetes.cluster:foreign"
    child = ResourceRecord(
        resource_id=f"{foreign_cluster}/resource/pod-example",
        type="kubernetes.pod",
        props={
            "cluster_ref": foreign_cluster,
            "namespace": "default",
            "name": "example",
            "uid": "uid-pod",
            "owner_uids": ("shared-owner-uid",),
        },
        last_seen=OBSERVED_AT,
    )

    result = project_kubernetes_relationships(
        (owner, child),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.links == ()
    assert (
        "kubernetes.resource-owned-by-controller",
        RelationshipDropReason.MISSING_TARGET_ENDPOINT,
    ) in {(drop.mapping_id, drop.reason) for drop in result.dropped}


def test_node_provider_bridge_never_falls_back_to_similar_names() -> None:
    node = ResourceRecord(
        resource_id=f"{CLUSTER_REF}/node/system-0",
        type="kubernetes.node",
        props={
            "cluster_ref": CLUSTER_REF,
            "name": "system-0",
            "provider_resource_ref": "/subscriptions/example/vmss/system/virtualMachines/0",
        },
        last_seen=OBSERVED_AT,
    )
    virtual_machine = ResourceRecord(
        resource_id=f"{CLUSTER_REF}/vm/system-0",
        type="compute.vm",
        props={"name": "system-0"},
        provider_ref="/subscriptions/example/vmss/other/virtualMachines/0",
        last_seen=OBSERVED_AT,
    )

    result = project_kubernetes_relationships(
        (node, virtual_machine),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.links == ()
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        (
            "kubernetes.node-backed-by-vmss-vm",
            RelationshipDropReason.MISSING_TARGET_ENDPOINT,
        )
    ]


def test_ingress_with_missing_backend_emits_no_partial_route() -> None:
    cluster, namespace, service, pod, endpoints = _resources()
    ingress = _resource(
        f"{CLUSTER_REF}/resource/ingress-api",
        "kubernetes.ingress",
        name="api",
        extra={
            "uid": "uid-ingress",
            "backend_service_names": ("api", "missing"),
        },
    )

    result = project_kubernetes_relationships(
        (cluster, namespace, service, pod, endpoints, ingress),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert all(
        link.mapping_evidence is None
        or link.mapping_evidence.mapping_id != "kubernetes.ingress-routes-to-service"
        for link in result.links
    )
    assert (
        "kubernetes.ingress-routes-to-service",
        RelationshipDropReason.MISSING_TARGET_ENDPOINT,
    ) in {(drop.mapping_id, drop.reason) for drop in result.dropped}


def test_node_provider_bridge_rejects_ambiguous_provider_identity() -> None:
    provider_ref = "/subscriptions/example/vmss/system/virtualMachines/0"
    node = ResourceRecord(
        resource_id=f"{CLUSTER_REF}/node/system-0",
        type="kubernetes.node",
        props={
            "cluster_ref": CLUSTER_REF,
            "name": "system-0",
            "provider_resource_ref": provider_ref,
        },
        last_seen=OBSERVED_AT,
    )
    virtual_machines = tuple(
        ResourceRecord(
            resource_id=f"{CLUSTER_REF}/vm/system-{index}",
            type="compute.vm",
            props={"name": f"system-{index}"},
            provider_ref=provider_ref,
            last_seen=OBSERVED_AT,
        )
        for index in range(2)
    )

    result = project_kubernetes_relationships(
        (node, *virtual_machines),
        catalog=load_provider_relationship_mapping_catalog(CATALOG_ROOT),
        complete=True,
    )

    assert result.links == ()
    assert [(drop.mapping_id, drop.reason) for drop in result.dropped] == [
        (
            "kubernetes.node-backed-by-vmss-vm",
            RelationshipDropReason.CONFLICTING_DUPLICATE,
        )
    ]


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
    assert len(verified.links) == 6
    assert all(
        link.observation_metadata is not None and link.observation_metadata.verified
        for link in verified.links
    )

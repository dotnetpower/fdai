"""Inventory-grounded Kubernetes Pod lifecycle identity tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot
from fdai.delivery.kubernetes_pod_lifecycle_identity import pod_lifecycle_identities
from fdai.shared.providers.inventory import ResourceRecord

NOW = datetime(2026, 8, 28, tzinfo=UTC)


def _resource(
    resource_id: str,
    resource_type: str,
    **properties: object,
) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        type=resource_type,
        props={"cluster_ref": "cluster-a", **properties},
        last_seen=NOW.isoformat(),
    )


def test_pod_identity_uses_inventory_controller_chain() -> None:
    snapshot = KubernetesApiInventorySnapshot(
        resources=tuple(
            sorted(
                (
                    _resource(
                        "deployment/orders",
                        "kubernetes.deployment",
                        uid="deployment-uid",
                    ),
                    _resource(
                        "pod/orders-new",
                        "kubernetes.pod",
                        uid="pod-new",
                        namespace="default",
                        controller_uid="replicaset-uid",
                    ),
                    _resource(
                        "replicaset/orders",
                        "kubernetes.replica-set",
                        uid="replicaset-uid",
                        controller_uid="deployment-uid",
                    ),
                ),
                key=lambda item: item.resource_id,
            )
        ),
        observed_at=NOW,
    )

    identities = pod_lifecycle_identities(snapshot)

    assert len(identities) == 1
    assert identities[0].pod_uid == "pod-new"
    assert identities[0].controller_uid == "replicaset-uid"
    assert identities[0].root_controller_uid == "deployment-uid"
    assert identities[0].root_controller_kind == "Deployment"


def test_pod_identity_omits_unresolved_controller_chain() -> None:
    snapshot = KubernetesApiInventorySnapshot(
        resources=(
            _resource(
                "pod/unresolved",
                "kubernetes.pod",
                uid="pod-unresolved",
                namespace="default",
                controller_uid="missing-controller",
            ),
        ),
        observed_at=NOW,
    )

    assert pod_lifecycle_identities(snapshot) == ()

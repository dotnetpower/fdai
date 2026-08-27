"""Derive durable Pod controller identity from complete Kubernetes inventory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesPodLifecycleIdentity,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot

_ROOT_KIND_BY_TYPE = {
    "kubernetes.daemon-set": "DaemonSet",
    "kubernetes.deployment": "Deployment",
    "kubernetes.job": "Job",
    "kubernetes.stateful-set": "StatefulSet",
}


class KubernetesPodLifecycleIdentitySink(Protocol):
    """Persist immutable Pod controller identities without mutating inventory state."""

    async def append_pod_identities(
        self,
        identities: tuple[KubernetesPodLifecycleIdentity, ...],
    ) -> None: ...


def pod_lifecycle_identities(
    snapshot: KubernetesApiInventorySnapshot,
) -> tuple[KubernetesPodLifecycleIdentity, ...]:
    """Return controller-grounded Pod identities from one complete snapshot."""

    resources_by_uid = {
        uid: resource
        for resource in snapshot.resources
        if isinstance((uid := resource.props.get("uid")), str) and uid
    }
    source_revision = _snapshot_revision(snapshot)
    identities: list[KubernetesPodLifecycleIdentity] = []
    for pod in snapshot.resources:
        if pod.type != "kubernetes.pod":
            continue
        props = pod.props
        pod_uid = _text(props, "uid")
        namespace = _text(props, "namespace")
        controller_uid = _text(props, "controller_uid")
        controller = resources_by_uid.get(controller_uid)
        if controller is None:
            continue
        root_uid, root_kind = _root_controller(controller, resources_by_uid)
        if root_uid is None or root_kind is None:
            continue
        evidence_material = json.dumps(
            {
                "cluster_ref": _text(props, "cluster_ref"),
                "namespace": namespace,
                "pod_id": pod.resource_id,
                "pod_uid": pod_uid,
                "controller_uid": controller_uid,
                "root_controller_uid": root_uid,
                "root_controller_kind": root_kind,
                "source_revision": source_revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        identities.append(
            KubernetesPodLifecycleIdentity(
                cluster_ref=_text(props, "cluster_ref"),
                namespace=namespace,
                pod_id=pod.resource_id,
                pod_uid=pod_uid,
                controller_uid=controller_uid,
                root_controller_uid=root_uid,
                root_controller_kind=root_kind,
                observed_at=snapshot.observed_at,
                source_revision=source_revision,
                evidence_ref=(
                    "kubernetes-pod-lifecycle:" + hashlib.sha256(evidence_material).hexdigest()
                ),
            )
        )
    return tuple(sorted(identities, key=lambda item: (item.pod_uid, item.evidence_ref)))


def _root_controller(
    controller: object,
    resources_by_uid: Mapping[str, object],
) -> tuple[str | None, str | None]:
    controller_type = getattr(controller, "type", None)
    props = getattr(controller, "props", None)
    if not isinstance(controller_type, str) or not isinstance(props, Mapping):
        return None, None
    root_kind = _ROOT_KIND_BY_TYPE.get(controller_type)
    if root_kind is not None:
        return _text(props, "uid"), root_kind
    if controller_type != "kubernetes.replica-set":
        return None, None
    root_uid = props.get("controller_uid")
    if not isinstance(root_uid, str) or not root_uid:
        return None, None
    root = resources_by_uid.get(root_uid)
    root_type = getattr(root, "type", None)
    root_props = getattr(root, "props", None)
    if root_type != "kubernetes.deployment" or not isinstance(root_props, Mapping):
        return None, None
    return _text(root_props, "uid"), "Deployment"


def _snapshot_revision(snapshot: KubernetesApiInventorySnapshot) -> str:
    material = json.dumps(
        [
            {
                "id": resource.resource_id,
                "type": resource.type,
                "uid": resource.props.get("uid"),
                "controller_uid": resource.props.get("controller_uid"),
            }
            for resource in snapshot.resources
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"Kubernetes Pod lifecycle {key} is unavailable")
    return item.strip()


__all__ = [
    "KubernetesPodLifecycleIdentitySink",
    "pod_lifecycle_identities",
]

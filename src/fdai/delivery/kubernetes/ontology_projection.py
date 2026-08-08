"""Project bounded Kubernetes evidence into typed ontology resources and links."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord

_MAX_RESOURCES = 1000


@dataclass(frozen=True, slots=True)
class KubernetesOntologyProjection:
    """Exact-identity Kubernetes resource objects and evidence-supported relationships."""

    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]


def build_kubernetes_ontology_projection(
    resources: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    expected_namespace: str,
    cluster_ref: str,
) -> KubernetesOntologyProjection:
    """Project exact UID resources; incomplete evidence produces no relationship claims."""

    if len(resources) > _MAX_RESOURCES:
        raise ValueError("Kubernetes ontology resource count exceeds limit")
    if not expected_namespace.strip():
        raise ValueError("Kubernetes ontology expected_namespace MUST be non-empty")
    if not cluster_ref.startswith("kubernetes.cluster:"):
        raise ValueError("Kubernetes ontology cluster_ref is invalid")
    by_uid: dict[str, tuple[str, Mapping[str, Any]]] = {}
    by_identity: dict[tuple[str, str, str], str] = {}
    objects: list[OntologyObjectRecord] = []
    for resource in sorted(resources, key=_sort_key):
        uid = _text(resource.get("uid"))
        kind = _text(resource.get("kind"))
        namespace = _text(resource.get("namespace"))
        if namespace and namespace != expected_namespace:
            raise ValueError("Kubernetes ontology evidence crossed the target namespace")
        name = _text(resource.get("name"))
        if not all((uid, kind, namespace, name)):
            continue
        if uid in by_uid:
            raise ValueError(f"duplicate Kubernetes resource UID {uid!r}")
        identity = (kind, namespace, name)
        if identity in by_identity:
            raise ValueError(f"duplicate Kubernetes resource identity {identity!r}")
        object_id = f"{cluster_ref}/resource/{uid}"
        by_uid[uid] = (object_id, resource)
        by_identity[identity] = object_id
        objects.append(
            OntologyObjectRecord(
                id=object_id,
                object_type="Resource",
                properties={
                    "id": object_id,
                    "type": f"kubernetes.{kind.lower()}",
                    "name": name,
                    "parent_id": f"{cluster_ref}/namespace/{namespace}",
                    "properties": {
                        "kind": kind,
                        "namespace": namespace,
                        "uid": uid,
                    },
                },
            )
        )
    namespace_ref = f"{cluster_ref}/namespace/{expected_namespace}"
    if objects:
        objects.append(
            OntologyObjectRecord(
                id=namespace_ref,
                object_type="Resource",
                properties={
                    "id": namespace_ref,
                    "type": "kubernetes.namespace",
                    "name": expected_namespace,
                    "properties": {
                        "cluster_ref": cluster_ref,
                        "namespace": expected_namespace,
                    },
                },
            )
        )
        objects.sort(key=lambda item: item.id)
    if not evidence_complete:
        return KubernetesOntologyProjection(objects=tuple(objects), links=())

    links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    for object_id, resource in by_uid.values():
        namespace = _text(resource.get("namespace"))
        _add_link(links, "contains", f"{cluster_ref}/namespace/{namespace}", object_id)
        if resource.get("owner_reference_projection_complete") is True:
            for owner in _mappings(resource.get("owner_references")):
                owner_uid = _text(owner.get("uid"))
                owner_entry = by_uid.get(owner_uid)
                if owner_entry is not None:
                    _add_link(links, "kubernetes_owned_by", object_id, owner_entry[0])
        kind = _text(resource.get("kind"))
        name = _text(resource.get("name"))
        if kind == "Service":
            endpoints_id = by_identity.get(("Endpoints", namespace, name))
            if endpoints_id is not None:
                _add_link(links, "kubernetes_exposes_endpoints", object_id, endpoints_id)
            selector = resource.get("selector")
            if (
                isinstance(selector, Mapping)
                and selector
                and all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in selector.items()
                )
            ):
                for pod_id, pod in by_uid.values():
                    if pod.get("kind") != "Pod" or pod.get("namespace") != namespace:
                        continue
                    labels = pod.get("labels")
                    if isinstance(labels, Mapping) and all(
                        labels.get(key) == value for key, value in selector.items()
                    ):
                        _add_link(links, "kubernetes_selects", object_id, pod_id)
        if kind in {"DaemonSet", "Deployment", "StatefulSet"}:
            template = resource.get("pod_template")
            if not isinstance(template, Mapping) or template.get("projection_complete") is not True:
                continue
            for container in _mappings(template.get("containers")):
                if container.get("env_projection_complete") is not True:
                    continue
                for env in _mappings(container.get("env")):
                    host = _text(env.get("endpoint_host"))
                    if host and "." not in host:
                        service_id = by_identity.get(("Service", namespace, host))
                        if service_id is not None:
                            _add_link(links, "depends_on", object_id, service_id)
    return KubernetesOntologyProjection(
        objects=tuple(objects),
        links=tuple(
            sorted(links.values(), key=lambda item: (item.from_id, item.link_type, item.to_id))
        ),
    )


def _add_link(
    links: dict[tuple[str, str, str], OntologyLinkRecord],
    link_type: str,
    from_id: str,
    to_id: str,
) -> None:
    links[(from_id, link_type, to_id)] = OntologyLinkRecord(link_type, from_id, to_id)


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _sort_key(resource: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(resource.get("namespace")),
        _text(resource.get("kind")),
        _text(resource.get("name")),
        _text(resource.get("uid")),
    )


__all__ = ["KubernetesOntologyProjection", "build_kubernetes_ontology_projection"]

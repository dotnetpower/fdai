"""Content-safe snapshot codec for outbound Kubernetes inventory evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fdai_service_contracts.cluster_connector import ConnectorEvidence, connector_time

from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventorySnapshot,
    kubernetes_resource_id,
)
from fdai.shared.providers.inventory import ResourceRecord

_MAX_BYTES = 8_388_608
_MAX_OBJECTS = 20_000
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
_KINDS = {
    "namespace": ("v1", "Namespace", False),
    "node": ("v1", "Node", False),
    "pod": ("v1", "Pod", True),
    "service": ("v1", "Service", True),
    "endpoints": ("v1", "Endpoints", True),
    "persistent-volume-claim": ("v1", "PersistentVolumeClaim", True),
    "persistent-volume": ("v1", "PersistentVolume", False),
    "resource-quota": ("v1", "ResourceQuota", True),
    "limit-range": ("v1", "LimitRange", True),
    "endpoint-slice": ("discovery.k8s.io/v1", "EndpointSlice", True),
    "job": ("batch/v1", "Job", True),
    "cron-job": ("batch/v1", "CronJob", True),
    "deployment": ("apps/v1", "Deployment", True),
    "replica-set": ("apps/v1", "ReplicaSet", True),
    "daemon-set": ("apps/v1", "DaemonSet", True),
    "stateful-set": ("apps/v1", "StatefulSet", True),
    "horizontal-pod-autoscaler": ("autoscaling/v2", "HorizontalPodAutoscaler", True),
    "pod-disruption-budget": ("policy/v1", "PodDisruptionBudget", True),
    "ingress": ("networking.k8s.io/v1", "Ingress", True),
    "ingress-class": ("networking.k8s.io/v1", "IngressClass", False),
    "network-policy": ("networking.k8s.io/v1", "NetworkPolicy", True),
    "storage-class": ("storage.k8s.io/v1", "StorageClass", False),
}
_TEXT = frozenset(
    """
api_version cluster_ref kind name resource_version uid namespace created_at controller_uid
root_controller_uid service_name node_name provider_resource_ref ingress_class_name node_pool
phase ready_status progressing_status progressing_reason qos_class reason restart_policy
priority_class_name scheduler_name service_account_name storage_class_name volume_mode volume_name
requested_storage capacity_storage reclaim_policy claim_name claim_namespace claim_uid provisioner
volume_binding_mode scale_target_name scale_target_kind scale_target_api_version address_type
max_unavailable min_available
""".split()
)
_COUNTS = frozenset(
    """
container_count ready_container_count restart_count available_replicas desired_replicas
ready_replicas unavailable_replicas updated_replicas observed_generation current_replicas
init_container_count init_container_ready_count init_container_restart_count
ephemeral_container_count
ephemeral_container_ready_count ephemeral_container_restart_count min_replicas max_replicas
current_healthy desired_healthy disruptions_allowed expected_pods ingress_rule_count
egress_rule_count endpoint_count port_count ready ready_unknown serving serving_unknown
terminating terminating_unknown
""".split()
)
_FLAGS = frozenset({"selector_matches_all", "allow_volume_expansion"})
_MAPS = frozenset({"labels", "selector", "node_selector", "quota_hard", "quota_used"})
_LISTS = frozenset(
    """
owner_uids backend_service_names pvc_claim_names target_uids access_modes policy_types
affinity_kinds
termination_reasons container_waiting_reasons init_container_termination_reasons
init_container_waiting_reasons ephemeral_container_termination_reasons
ephemeral_container_waiting_reasons
""".split()
)
_RECORDS = {
    "diagnostic_conditions": frozenset({"type", "status", "reason", "last_transition_time"}),
    "container_resources": frozenset({"container_name", "requests", "limits"}),
    "container_terminations": frozenset(
        {"container_name", "observation_kind", "reason", "exit_code", "signal", "finished_at"}
    ),
    "probe_kinds": frozenset({"container_name", "probe_kind"}),
    "tolerations": frozenset({"key", "operator", "value", "effect", "seconds"}),
    "limit_summaries": frozenset(
        {"type", "max", "min", "default", "default_request", "max_limit_request_ratio"}
    ),
}
_REQUIRED_RECORD_FIELDS = {
    "diagnostic_conditions": {"type", "status"},
    "container_resources": {"container_name", "requests", "limits"},
    "container_terminations": {"container_name", "observation_kind", "exit_code"},
    "probe_kinds": {"container_name", "probe_kind"},
    "tolerations": set(),
    "limit_summaries": {"type"},
}


class ConnectorArtifactError(ValueError):
    """Reject an artifact without exposing its contents or source identifiers."""


def snapshot_bytes(snapshot: KubernetesApiInventorySnapshot) -> bytes:
    """Encode only a previously normalized complete inventory snapshot."""
    body = {
        "schema_version": "1.0.0",
        "observed_at": connector_time(snapshot.observed_at).isoformat(),
        "resources": [
            {
                "resource_id": record.resource_id,
                "type": record.type,
                "props": dict(record.props),
                "provider_ref": record.provider_ref,
                "last_seen": record.last_seen,
            }
            for record in snapshot.resources
        ],
    }
    try:
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise ConnectorArtifactError("connector snapshot is not serializable") from None
    if not 1 <= len(encoded) <= _MAX_BYTES:
        raise ConnectorArtifactError("connector snapshot exceeds its byte limit")
    return encoded


def artifact_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def decode_snapshot(
    content: bytes,
    packet: ConnectorEvidence,
    *,
    allow_cluster_resources: bool,
) -> KubernetesApiInventorySnapshot:
    """Verify exact bytes, identity, scope and allowlisted normalized properties.

    Cluster-scoped reads require an independent server-owned permission. A complete snapshot
    must include every namespace represented in the envelope and no objects outside those
    namespaces. Authentication, freshness and inventory promotion remain the receiver's job.
    """
    packet = ConnectorEvidence.model_validate_json(packet.model_dump_json())
    if (
        packet.capability != "inventory.snapshot"
        or not packet.complete
        or len(content) != packet.artifact_bytes
        or len(content) > _MAX_BYTES
        or artifact_digest(content) != packet.artifact_digest
    ):
        raise ConnectorArtifactError("connector snapshot does not match its envelope")
    try:
        body = json.loads(content, object_pairs_hook=_unique_object)
        if not isinstance(body, dict) or set(body) != {
            "schema_version",
            "observed_at",
            "resources",
        }:
            raise ValueError
        if (
            body["schema_version"] != "1.0.0"
            or connector_time(body["observed_at"]) != packet.observed_at
        ):
            raise ValueError
        rows = body["resources"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_OBJECTS:
            raise ValueError
        resources = tuple(_record(row, packet, allow_cluster_resources) for row in rows)
        namespaces = {
            record.props["name"] for record in resources if record.type == "kubernetes.namespace"
        }
        if namespaces != set(packet.namespaces):
            raise ValueError
        if len({record.props["uid"] for record in resources}) != len(resources):
            raise ValueError
        return KubernetesApiInventorySnapshot(resources, packet.observed_at)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ConnectorArtifactError(
            "connector snapshot violates the content or identity contract"
        ) from None


def _record(
    row: object, packet: ConnectorEvidence, allow_cluster_resources: bool
) -> ResourceRecord:
    if not isinstance(row, dict) or set(row) != {
        "resource_id",
        "type",
        "props",
        "provider_ref",
        "last_seen",
    }:
        raise ValueError
    resource_type = row["type"]
    if not isinstance(resource_type, str) or not resource_type.startswith("kubernetes."):
        raise ValueError
    api_version, kind, namespaced = _KINDS[resource_type.removeprefix("kubernetes.")]
    props = row["props"]
    if not isinstance(props, dict) or not {
        "api_version",
        "cluster_ref",
        "kind",
        "name",
        "resource_version",
        "uid",
    } <= set(props):
        raise ValueError
    if (
        props["api_version"] != api_version
        or props["kind"] != kind
        or props["cluster_ref"] != packet.scope.cluster_ref
    ):
        raise ValueError
    for key in ("name", "uid", "resource_version"):
        if not isinstance(props[key], str) or not _IDENTITY.fullmatch(props[key]):
            raise ValueError
    namespace = props.get("namespace")
    if namespaced or kind == "Namespace":
        if namespace not in packet.namespaces or (
            kind == "Namespace" and namespace != props["name"]
        ):
            raise ValueError
    elif namespace is not None or allow_cluster_resources is not True:
        raise ValueError
    expected_id = kubernetes_resource_id(
        cluster_ref=packet.scope.cluster_ref,
        resource_type=resource_type,
        uid=props["uid"],
        namespace=namespace if namespaced else None,
    )
    if row["resource_id"] != expected_id or row["provider_ref"] != f"kubernetes-uid:{props['uid']}":
        raise ValueError
    if connector_time(row["last_seen"]) != packet.observed_at:
        raise ValueError
    for key, value in props.items():
        if key == "ready" and kind in {"Pod", "Node"}:
            if type(value) is not bool:
                raise ValueError
        else:
            _property(key, value)
    return ResourceRecord(expected_id, resource_type, props, row["provider_ref"], row["last_seen"])


def _property(key: str, value: object) -> None:
    if key in _TEXT:
        if key in {"min_available", "max_unavailable"} and type(value) is int and value >= 0:
            return
        _text(value)
        if key == "created_at":
            connector_time(value)
    elif key in _COUNTS:
        if type(value) is not int or not 0 <= value <= 2**63 - 1:
            raise ValueError
    elif key in _FLAGS:
        if type(value) is not bool:
            raise ValueError
    elif key in _MAPS:
        _string_map(value)
    elif key == "status_counts":
        if not isinstance(value, dict) or set(value) - {
            "active",
            "failed",
            "ready",
            "succeeded",
            "terminating",
            "current_number_scheduled",
            "desired_number_scheduled",
            "number_available",
            "number_misscheduled",
            "number_ready",
            "number_unavailable",
            "updated_number_scheduled",
            "available_replicas",
            "current_replicas",
            "ready_replicas",
            "replicas",
            "updated_replicas",
        }:
            raise ValueError
        if any(type(item) is not int or not 0 <= item <= 2**63 - 1 for item in value.values()):
            raise ValueError
    elif key in _LISTS:
        if not isinstance(value, list) or len(value) > 128:
            raise ValueError
        for item in value:
            _text(item)
    elif key in _RECORDS:
        maximum = 384 if key == "probe_kinds" else 256 if key == "container_terminations" else 128
        if not isinstance(value, list) or len(value) > maximum:
            raise ValueError
        for record in value:
            if (
                not isinstance(record, dict)
                or set(record) - _RECORDS[key]
                or not _REQUIRED_RECORD_FIELDS[key] <= set(record)
            ):
                raise ValueError
            for item_key, item in record.items():
                if item_key in {
                    "requests",
                    "limits",
                    "max",
                    "min",
                    "default",
                    "default_request",
                    "max_limit_request_ratio",
                }:
                    _string_map(item)
                elif item_key in {"exit_code", "signal", "seconds"}:
                    if type(item) is not int or not 0 <= item <= 2**63 - 1:
                        raise ValueError
                else:
                    _text(item)
                if item_key in {"last_transition_time", "finished_at"}:
                    connector_time(item)
            if key == "diagnostic_conditions" and record["status"] not in (
                "True",
                "False",
                "Unknown",
            ):
                raise ValueError
            if key == "container_terminations" and record["observation_kind"] not in (
                "current",
                "previous",
            ):
                raise ValueError
            if key == "probe_kinds" and record["probe_kind"] not in (
                "liveness",
                "readiness",
                "startup",
            ):
                raise ValueError
    else:
        raise ValueError


def _text(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 1024
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError


def _string_map(value: object) -> None:
    if not isinstance(value, dict) or len(value) > 128:
        raise ValueError
    for key, item in value.items():
        _text(key)
        _text(item)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result

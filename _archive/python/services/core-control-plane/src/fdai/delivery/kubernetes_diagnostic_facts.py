"""Extract bounded content-safe Kubernetes diagnostic facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final, cast

_MAX_CONDITIONS: Final[int] = 128
_MAX_CONTAINERS: Final[int] = 128
_MAX_SCHEDULING_ITEMS: Final[int] = 128
_MAX_TEXT: Final[int] = 512
_CONDITION_TYPES: Final[Mapping[str, frozenset[str]]] = {
    "kubernetes.node": frozenset(
        {"DiskPressure", "MemoryPressure", "NetworkUnavailable", "PIDPressure", "Ready"}
    ),
    "kubernetes.pod": frozenset(
        {
            "ContainersReady",
            "Initialized",
            "PodReadyToStartContainers",
            "PodScheduled",
            "Ready",
        }
    ),
    "kubernetes.deployment": frozenset({"Available", "Progressing", "ReplicaFailure"}),
    "kubernetes.daemon-set": frozenset({"Available", "Progressing"}),
    "kubernetes.stateful-set": frozenset({"Available", "Progressing"}),
    "kubernetes.job": frozenset({"Complete", "Failed", "Suspended"}),
    "kubernetes.horizontal-pod-autoscaler": frozenset(
        {"AbleToScale", "ScalingActive", "ScalingLimited"}
    ),
}
_STATUS_COUNT_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "kubernetes.daemon-set": (
        "currentNumberScheduled",
        "desiredNumberScheduled",
        "numberAvailable",
        "numberMisscheduled",
        "numberReady",
        "numberUnavailable",
        "updatedNumberScheduled",
    ),
    "kubernetes.stateful-set": (
        "availableReplicas",
        "currentReplicas",
        "readyReplicas",
        "replicas",
        "updatedReplicas",
    ),
    "kubernetes.job": ("active", "failed", "ready", "succeeded", "terminating"),
}


def diagnostic_properties(
    *,
    resource_type: str,
    spec: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Return allowlisted diagnostic facts without raw provider-controlled text."""

    props: dict[str, object] = {}
    if status is not None:
        conditions = _conditions(status.get("conditions"), resource_type=resource_type)
        if conditions:
            props["diagnostic_conditions"] = conditions
        counts = _status_counts(status, resource_type=resource_type)
        if counts:
            props["status_counts"] = counts
        qos_class = _optional_text(status.get("qosClass"))
        if resource_type == "kubernetes.pod" and qos_class is not None:
            props["qos_class"] = qos_class
        pod_reason = _optional_text(status.get("reason"))
        if resource_type == "kubernetes.pod" and pod_reason is not None:
            props["reason"] = pod_reason
        for source_name, prefix in (
            ("initContainerStatuses", "init_container"),
            ("ephemeralContainerStatuses", "ephemeral_container"),
        ):
            summary = _container_status_summary(status.get(source_name))
            for key, value in summary.items():
                props[f"{prefix}_{key}"] = value
    if spec is not None and resource_type == "kubernetes.pod":
        props.update(_pod_spec_properties(spec))
    if resource_type == "kubernetes.persistent-volume-claim":
        props.update(_persistent_volume_claim_properties(spec=spec, status=status))
    elif resource_type == "kubernetes.persistent-volume":
        props.update(_persistent_volume_properties(spec=spec, status=status))
    elif resource_type == "kubernetes.storage-class" and body is not None:
        props.update(_storage_class_properties(body))
    elif resource_type == "kubernetes.horizontal-pod-autoscaler":
        props.update(_horizontal_pod_autoscaler_properties(spec=spec, status=status))
    elif resource_type == "kubernetes.pod-disruption-budget":
        props.update(_pod_disruption_budget_properties(spec=spec, status=status))
    elif resource_type == "kubernetes.network-policy" and spec is not None:
        props.update(_network_policy_properties(spec))
    elif resource_type == "kubernetes.resource-quota" and status is not None:
        props.update(_resource_quota_properties(status))
    elif resource_type == "kubernetes.limit-range" and spec is not None:
        props.update(_limit_range_properties(spec))
    elif resource_type == "kubernetes.endpoint-slice" and body is not None:
        props.update(_endpoint_slice_properties(body))
    return props


def _endpoint_slice_properties(body: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    address_type = _optional_text(body.get("addressType"))
    if address_type is not None:
        props["address_type"] = address_type
    ports = _mapping_sequence(
        body.get("ports"),
        field="EndpointSlice ports",
        limit=_MAX_SCHEDULING_ITEMS,
        allow_none=True,
    )
    props["port_count"] = len(ports)
    endpoints = _mapping_sequence(
        body.get("endpoints"),
        field="EndpointSlice endpoints",
        limit=_MAX_SCHEDULING_ITEMS,
        allow_none=True,
    )
    target_uids: set[str] = set()
    condition_counts = {
        "ready": 0,
        "ready_unknown": 0,
        "serving": 0,
        "serving_unknown": 0,
        "terminating": 0,
        "terminating_unknown": 0,
    }
    for endpoint in endpoints:
        target = endpoint.get("targetRef")
        if target is not None:
            if not isinstance(target, Mapping):
                raise ValueError("Kubernetes EndpointSlice targetRef MUST be an object")
            if target.get("kind") == "Pod":
                uid = _optional_text(target.get("uid"))
                if uid is not None:
                    target_uids.add(uid)
        conditions = endpoint.get("conditions")
        if conditions is None:
            conditions = {}
        if not isinstance(conditions, Mapping):
            raise ValueError("Kubernetes EndpointSlice conditions MUST be an object")
        for name in ("ready", "serving", "terminating"):
            value = conditions.get(name)
            if value is None:
                condition_counts[f"{name}_unknown"] += 1
            elif isinstance(value, bool):
                condition_counts[name] += int(value)
            else:
                raise ValueError(f"Kubernetes EndpointSlice {name} MUST be boolean or null")
    props["endpoint_count"] = len(endpoints)
    props.update(condition_counts)
    if target_uids:
        props["target_uids"] = tuple(sorted(target_uids))
    return props


def _persistent_volume_claim_properties(
    *,
    spec: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
) -> dict[str, object]:
    props: dict[str, object] = {}
    if spec is not None:
        for source_name, output_name in (
            ("storageClassName", "storage_class_name"),
            ("volumeMode", "volume_mode"),
            ("volumeName", "volume_name"),
        ):
            value = _optional_text(spec.get(source_name))
            if value is not None:
                props[output_name] = value
        access_modes = _string_sequence(spec.get("accessModes"), field="PVC accessModes")
        if access_modes:
            props["access_modes"] = access_modes
        resources = spec.get("resources")
        if resources is not None and not isinstance(resources, Mapping):
            raise ValueError("Kubernetes PVC resources MUST be an object")
        requests = resources.get("requests") if isinstance(resources, Mapping) else None
        if isinstance(requests, Mapping):
            requested = _optional_text(requests.get("storage"))
            if requested is not None:
                props["requested_storage"] = requested
    if status is not None:
        phase = _optional_text(status.get("phase"))
        if phase is not None:
            props["phase"] = phase
        capacity = status.get("capacity")
        if isinstance(capacity, Mapping):
            storage = _optional_text(capacity.get("storage"))
            if storage is not None:
                props["capacity_storage"] = storage
    return props


def _persistent_volume_properties(
    *,
    spec: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
) -> dict[str, object]:
    props: dict[str, object] = {}
    if spec is not None:
        for source_name, output_name in (
            ("persistentVolumeReclaimPolicy", "reclaim_policy"),
            ("storageClassName", "storage_class_name"),
            ("volumeMode", "volume_mode"),
        ):
            value = _optional_text(spec.get(source_name))
            if value is not None:
                props[output_name] = value
        capacity = spec.get("capacity")
        if isinstance(capacity, Mapping):
            storage = _optional_text(capacity.get("storage"))
            if storage is not None:
                props["capacity_storage"] = storage
        claim_ref = spec.get("claimRef")
        if claim_ref is not None:
            if not isinstance(claim_ref, Mapping):
                raise ValueError("Kubernetes PV claimRef MUST be an object")
            for source_name, output_name in (
                ("name", "claim_name"),
                ("namespace", "claim_namespace"),
                ("uid", "claim_uid"),
            ):
                value = _optional_text(claim_ref.get(source_name))
                if value is not None:
                    props[output_name] = value
    if status is not None:
        phase = _optional_text(status.get("phase"))
        if phase is not None:
            props["phase"] = phase
        reason = _optional_text(status.get("reason"))
        if reason is not None:
            props["reason"] = reason
    return props


def _storage_class_properties(body: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    for source_name, output_name in (
        ("provisioner", "provisioner"),
        ("reclaimPolicy", "reclaim_policy"),
        ("volumeBindingMode", "volume_binding_mode"),
    ):
        value = _optional_text(body.get(source_name))
        if value is not None:
            props[output_name] = value
    expansion = body.get("allowVolumeExpansion")
    if expansion is not None:
        if not isinstance(expansion, bool):
            raise ValueError("Kubernetes StorageClass allowVolumeExpansion MUST be boolean")
        props["allow_volume_expansion"] = expansion
    return props


def _horizontal_pod_autoscaler_properties(
    *,
    spec: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
) -> dict[str, object]:
    props: dict[str, object] = {}
    if spec is not None:
        target = spec.get("scaleTargetRef")
        if target is not None:
            if not isinstance(target, Mapping):
                raise ValueError("Kubernetes HPA scaleTargetRef MUST be an object")
            for source_name, output_name in (
                ("apiVersion", "scale_target_api_version"),
                ("kind", "scale_target_kind"),
                ("name", "scale_target_name"),
            ):
                value = _optional_text(target.get(source_name))
                if value is not None:
                    props[output_name] = value
        for source_name, output_name in (
            ("minReplicas", "min_replicas"),
            ("maxReplicas", "max_replicas"),
        ):
            value = spec.get(source_name)
            if value is not None:
                props[output_name] = _non_negative_int(value, field=f"HPA {source_name}")
    if status is not None:
        for source_name, output_name in (
            ("currentReplicas", "current_replicas"),
            ("desiredReplicas", "desired_replicas"),
        ):
            value = status.get(source_name)
            if value is not None:
                props[output_name] = _non_negative_int(value, field=f"HPA {source_name}")
    return props


def _pod_disruption_budget_properties(
    *,
    spec: Mapping[str, Any] | None,
    status: Mapping[str, Any] | None,
) -> dict[str, object]:
    props: dict[str, object] = {}
    if spec is not None:
        selector = _match_labels(spec.get("selector"))
        if selector:
            props["selector"] = selector
        for source_name, output_name in (
            ("minAvailable", "min_available"),
            ("maxUnavailable", "max_unavailable"),
        ):
            value = spec.get(source_name)
            if isinstance(value, (int, str)) and not isinstance(value, bool):
                props[output_name] = str(value)
    if status is not None:
        for source_name, output_name in (
            ("currentHealthy", "current_healthy"),
            ("desiredHealthy", "desired_healthy"),
            ("disruptionsAllowed", "disruptions_allowed"),
            ("expectedPods", "expected_pods"),
        ):
            value = status.get(source_name)
            if value is not None:
                props[output_name] = _non_negative_int(value, field=f"PDB {source_name}")
    return props


def _network_policy_properties(spec: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    raw_selector = spec.get("podSelector")
    selector = _match_labels(raw_selector)
    if selector:
        props["selector"] = selector
    elif isinstance(raw_selector, Mapping):
        props["selector"] = {}
        props["selector_matches_all"] = True
    policy_types = _string_sequence(spec.get("policyTypes"), field="NetworkPolicy policyTypes")
    if policy_types:
        props["policy_types"] = policy_types
    for source_name, output_name in (
        ("ingress", "ingress_rule_count"),
        ("egress", "egress_rule_count"),
    ):
        value = spec.get(source_name)
        if value is not None:
            props[output_name] = len(
                _mapping_sequence(
                    value,
                    field=f"NetworkPolicy {source_name}",
                    limit=_MAX_SCHEDULING_ITEMS,
                )
            )
    return props


def _resource_quota_properties(status: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    for source_name, output_name in (("hard", "quota_hard"), ("used", "quota_used")):
        values = _bounded_text_mapping(
            status.get(source_name), field=f"ResourceQuota {source_name}"
        )
        if values:
            props[output_name] = values
    return props


def _limit_range_properties(spec: Mapping[str, Any]) -> dict[str, object]:
    rows = _mapping_sequence(
        spec.get("limits"),
        field="LimitRange limits",
        limit=_MAX_SCHEDULING_ITEMS,
        allow_none=True,
    )
    summaries: list[dict[str, object]] = []
    for row in rows:
        summary: dict[str, object] = {"type": _required_text(row.get("type"), field="limit type")}
        for source_name, output_name in (
            ("default", "default"),
            ("defaultRequest", "default_request"),
            ("max", "max"),
            ("min", "min"),
        ):
            values = _bounded_text_mapping(row.get(source_name), field=f"LimitRange {source_name}")
            if values:
                summary[output_name] = values
        summaries.append(summary)
    return {"limit_summaries": tuple(summaries)} if summaries else {}


def _match_labels(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Kubernetes label selector MUST be an object")
    expressions = value.get("matchExpressions")
    if expressions not in (None, []):
        raise ValueError("Kubernetes diagnostic selector expressions are not supported")
    return _string_mapping(value.get("matchLabels"))


def _conditions(value: object, *, resource_type: str) -> tuple[dict[str, object], ...]:
    allowed = _CONDITION_TYPES.get(resource_type)
    if allowed is None or value is None:
        return ()
    rows = _mapping_sequence(value, field="conditions", limit=_MAX_CONDITIONS)
    selected: dict[str, dict[str, object]] = {}
    for row in rows:
        condition_type = _required_text(row.get("type"), field="condition.type")
        if condition_type not in allowed:
            continue
        status = _required_text(row.get("status"), field="condition.status")
        if status not in {"True", "False", "Unknown"}:
            raise ValueError("Kubernetes diagnostic condition status is invalid")
        condition: dict[str, object] = {"status": status, "type": condition_type}
        reason = _optional_text(row.get("reason"))
        if reason is not None:
            condition["reason"] = reason
        transition = _optional_time(row.get("lastTransitionTime"))
        if transition is not None:
            condition["last_transition_time"] = transition
        if condition_type in selected:
            raise ValueError("Kubernetes diagnostic condition type is duplicated")
        selected[condition_type] = condition
    return tuple(selected[key] for key in sorted(selected))


def _status_counts(status: Mapping[str, Any], *, resource_type: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for field in _STATUS_COUNT_FIELDS.get(resource_type, ()):
        value = status.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Kubernetes status {field} MUST be a non-negative integer")
        counts[_snake_case(field)] = value
    return counts


def _pod_spec_properties(spec: Mapping[str, Any]) -> dict[str, object]:
    props: dict[str, object] = {}
    for source_name, output_name in (
        ("priorityClassName", "priority_class_name"),
        ("restartPolicy", "restart_policy"),
        ("schedulerName", "scheduler_name"),
        ("serviceAccountName", "service_account_name"),
    ):
        value = _optional_text(spec.get(source_name))
        if value is not None:
            props[output_name] = value
    node_selector = _string_mapping(spec.get("nodeSelector"))
    if node_selector:
        props["node_selector"] = node_selector
    tolerations = _tolerations(spec.get("tolerations"))
    if tolerations:
        props["tolerations"] = tolerations
    affinity = spec.get("affinity")
    if affinity is not None:
        if not isinstance(affinity, Mapping):
            raise ValueError("Kubernetes Pod affinity MUST be an object")
        kinds = tuple(
            key
            for key in ("nodeAffinity", "podAffinity", "podAntiAffinity")
            if isinstance(affinity.get(key), Mapping)
        )
        if kinds:
            props["affinity_kinds"] = kinds
    containers = _mapping_sequence(
        spec.get("containers"),
        field="containers",
        limit=_MAX_CONTAINERS,
        allow_none=True,
    )
    resource_specs = _container_resource_specs(containers)
    if resource_specs:
        props["container_resources"] = resource_specs
    probe_kinds = _probe_kinds(containers)
    if probe_kinds:
        props["probe_kinds"] = probe_kinds
    claims = _pvc_claim_names(spec.get("volumes"))
    if claims:
        props["pvc_claim_names"] = claims
    return props


def _container_resource_specs(
    containers: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, object], ...]:
    specs: list[dict[str, object]] = []
    for container in containers:
        name = _required_text(container.get("name"), field="container.name")
        resources = container.get("resources")
        if resources is None:
            continue
        if not isinstance(resources, Mapping):
            raise ValueError("Kubernetes container resources MUST be an object")
        requests = _quantity_mapping(resources.get("requests"))
        limits = _quantity_mapping(resources.get("limits"))
        if requests or limits:
            specs.append({"container_name": name, "limits": limits, "requests": requests})
    return tuple(sorted(specs, key=lambda item: str(item["container_name"])))


def _probe_kinds(containers: tuple[Mapping[str, Any], ...]) -> tuple[dict[str, str], ...]:
    probes: list[dict[str, str]] = []
    for container in containers:
        name = _required_text(container.get("name"), field="container.name")
        for field, kind in (
            ("livenessProbe", "liveness"),
            ("readinessProbe", "readiness"),
            ("startupProbe", "startup"),
        ):
            value = container.get(field)
            if value is not None and not isinstance(value, Mapping):
                raise ValueError(f"Kubernetes container {field} MUST be an object")
            if isinstance(value, Mapping):
                probes.append({"container_name": name, "probe_kind": kind})
    return tuple(sorted(probes, key=lambda item: (item["container_name"], item["probe_kind"])))


def _container_status_summary(value: object) -> dict[str, object]:
    rows = _mapping_sequence(
        value,
        field="container statuses",
        limit=_MAX_CONTAINERS,
        allow_none=True,
    )
    if not rows:
        return {}
    ready_count = 0
    restart_count = 0
    waiting_reasons: set[str] = set()
    termination_reasons: set[str] = set()
    for row in rows:
        ready = row.get("ready")
        if not isinstance(ready, bool):
            raise ValueError("Kubernetes diagnostic container ready MUST be boolean")
        ready_count += int(ready)
        restart = row.get("restartCount")
        if isinstance(restart, bool) or not isinstance(restart, int) or restart < 0:
            raise ValueError("Kubernetes diagnostic restartCount MUST be non-negative")
        restart_count += restart
        for state_key in ("state", "lastState"):
            state = row.get(state_key)
            if state is None:
                continue
            if not isinstance(state, Mapping):
                raise ValueError("Kubernetes diagnostic container state MUST be an object")
            waiting = state.get("waiting")
            terminated = state.get("terminated")
            if isinstance(waiting, Mapping):
                reason = _optional_text(waiting.get("reason"))
                if reason is not None:
                    waiting_reasons.add(reason)
            if isinstance(terminated, Mapping):
                reason = _optional_text(terminated.get("reason"))
                if reason is not None:
                    termination_reasons.add(reason)
    summary: dict[str, object] = {
        "count": len(rows),
        "ready_count": ready_count,
        "restart_count": restart_count,
    }
    if waiting_reasons:
        summary["waiting_reasons"] = tuple(sorted(waiting_reasons))
    if termination_reasons:
        summary["termination_reasons"] = tuple(sorted(termination_reasons))
    return summary


def _tolerations(value: object) -> tuple[dict[str, str], ...]:
    rows = _mapping_sequence(
        value,
        field="tolerations",
        limit=_MAX_SCHEDULING_ITEMS,
        allow_none=True,
    )
    output: list[dict[str, str]] = []
    for row in rows:
        item = {
            key: text
            for key in ("effect", "key", "operator", "value")
            if (text := _optional_text(row.get(key))) is not None
        }
        if item:
            output.append(item)
    return tuple(sorted(output, key=lambda item: tuple(sorted(item.items()))))


def _pvc_claim_names(value: object) -> tuple[str, ...]:
    rows = _mapping_sequence(
        value,
        field="volumes",
        limit=_MAX_SCHEDULING_ITEMS,
        allow_none=True,
    )
    claims: set[str] = set()
    for row in rows:
        claim = row.get("persistentVolumeClaim")
        if claim is None:
            continue
        if not isinstance(claim, Mapping):
            raise ValueError("Kubernetes persistentVolumeClaim MUST be an object")
        claims.add(_required_text(claim.get("claimName"), field="persistentVolumeClaim.claimName"))
    return tuple(sorted(claims))


def _quantity_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 32:
        raise ValueError("Kubernetes resource quantities MUST be a bounded object")
    allowed = {"cpu", "ephemeral-storage", "memory"}
    output: dict[str, str] = {}
    for key, raw in value.items():
        if key not in allowed:
            continue
        output[str(key)] = _required_text(raw, field=f"resource quantity {key}")
    return dict(sorted(output.items()))


def _bounded_text_mapping(value: object, *, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _MAX_SCHEDULING_ITEMS:
        raise ValueError(f"Kubernetes {field} MUST be a bounded object")
    return dict(
        sorted(
            (
                _required_text(key, field=f"{field} key"),
                _required_text(item, field=f"{field} value"),
            )
            for key, item in value.items()
        )
    )


def _string_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > _MAX_SCHEDULING_ITEMS:
        raise ValueError("Kubernetes diagnostic string mapping MUST be bounded")
    return dict(
        sorted(
            (
                _required_text(key, field="mapping key"),
                _required_text(item, field="mapping value"),
            )
            for key, item in value.items()
        )
    )


def _string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > _MAX_SCHEDULING_ITEMS
    ):
        raise ValueError(f"Kubernetes {field} MUST be a bounded array")
    return tuple(sorted({_required_text(item, field=field) for item in value}))


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Kubernetes {field} MUST be a non-negative integer")
    return value


def _mapping_sequence(
    value: object,
    *,
    field: str,
    limit: int,
    allow_none: bool = False,
) -> tuple[Mapping[str, Any], ...]:
    if value is None and allow_none:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > limit:
        raise ValueError(f"Kubernetes {field} MUST be a bounded array")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"Kubernetes {field} entries MUST be objects")
    return cast(tuple[Mapping[str, Any], ...], tuple(value))


def _required_text(value: object, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"Kubernetes {field} MUST be bounded non-empty text")
    return text


def _optional_text(value: object) -> str | None:
    return (
        value.strip()
        if isinstance(value, str) and value.strip() and len(value) <= _MAX_TEXT
        else None
    )


def _optional_time(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Kubernetes diagnostic timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise ValueError("Kubernetes diagnostic timestamp MUST include timezone")
    return parsed.isoformat()


def _snake_case(value: str) -> str:
    output: list[str] = []
    for character in value:
        if character.isupper() and output:
            output.append("_")
        output.append(character.casefold())
    return "".join(output)


__all__ = ["diagnostic_properties"]

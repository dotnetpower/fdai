"""Conservative A0 analysis of additive pod-to-pod Kubernetes network policies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest


class UnsupportedPolicyError(ValueError):
    """Signal incomplete or unsupported semantics, never infer an allowed connection."""


@dataclass(frozen=True, slots=True)
class PodPolicyEndpoint:
    """Snapshot of one exact Pod and the labels used for policy matching."""

    cluster_ref: str
    namespace: str
    uid: str
    labels: tuple[tuple[str, str], ...]
    namespace_labels: tuple[tuple[str, str], ...]
    host_network: bool = False


@dataclass(frozen=True, slots=True)
class PolicyFlowAssessment:
    """Describe policy configuration only; no traffic observation or action authority."""

    disposition: Literal["allowed", "blocked", "unknown"]
    reason: str
    policy_digest: str | None
    execution_authority: Literal[False] = False


def assess_policy_flow(
    *,
    source: PodPolicyEndpoint,
    destination: PodPolicyEndpoint,
    policies: tuple[Mapping[str, object], ...],
    port: int,
    protocol: str,
    complete: bool,
    observed_at: datetime,
    now: datetime,
    max_age_seconds: int = 300,
) -> PolicyFlowAssessment:
    """Evaluate a complete namespaced policy set for one same-cluster Pod flow.

    Policies use the native NetworkPolicy shape. Only metadata identity and the spec
    participate. Named ports, ipBlock/NAT, host networking, mixed clusters, stale input,
    malformed fields and unknown extensions remain unknown. API acceptance and this
    analysis are not evidence that a CNI has installed or enforced the policy.
    """
    try:
        current, cutoff = connector_time(now), connector_time(observed_at)
        if (
            complete is not True
            or type(port) is not int
            or not 1 <= port <= 65535
            or protocol not in {"TCP", "UDP", "SCTP"}
            or type(max_age_seconds) is not int
            or not 1 <= max_age_seconds <= 3600
            or not timedelta(0) <= current - cutoff < timedelta(seconds=max_age_seconds)
            or len(policies) > 256
        ):
            raise UnsupportedPolicyError("incomplete_or_stale_policy_context")
        _endpoint(source)
        _endpoint(destination)
        if source.cluster_ref != destination.cluster_ref or source.uid == destination.uid:
            raise UnsupportedPolicyError("unsupported_endpoint_relationship")
        normalized: list[tuple[str, Mapping[str, object]]] = []
        identities: set[tuple[str, str]] = set()
        material: list[dict[str, object]] = []
        _bound_tree(policies)
        for policy in policies:
            policy = _mapping(policy)
            if (
                policy.get("apiVersion") != "networking.k8s.io/v1"
                or policy.get("kind") != "NetworkPolicy"
            ):
                raise UnsupportedPolicyError("unsupported_policy_kind")
            metadata = _mapping(policy.get("metadata"))
            identity = (_text(metadata.get("namespace")), _text(metadata.get("name")))
            _text(metadata.get("uid"))
            _text(metadata.get("resourceVersion"))
            if identity in identities:
                raise UnsupportedPolicyError("duplicate_policy_identity")
            identities.add(identity)
            spec = _mapping(policy.get("spec"))
            if set(spec) - {"podSelector", "policyTypes", "ingress", "egress"}:
                raise UnsupportedPolicyError("unsupported_policy_spec")
            _selector(spec.get("podSelector"), {})
            for direction in ("ingress", "egress"):
                _sequence(spec.get(direction, []))
            normalized.append((identity[0], spec))
            material.append(
                {
                    "identity": list(identity),
                    "uid": metadata["uid"],
                    "revision": metadata["resourceVersion"],
                    "spec": dict(spec),
                }
            )
        outgoing = _direction(normalized, source, destination, "Egress", port, protocol)
        incoming = _direction(normalized, destination, source, "Ingress", port, protocol)
        material.sort(key=lambda record: str(record["identity"]))
        digest = canonical_digest(
            {
                "policies": material,
                "cluster_ref": source.cluster_ref,
                "observed_at": cutoff.isoformat(),
            }
        )
        return PolicyFlowAssessment(
            "allowed" if outgoing and incoming else "blocked",
            "configuration_only_not_enforcement_evidence",
            digest,
        )
    except (UnsupportedPolicyError, ValueError, TypeError, KeyError):
        return PolicyFlowAssessment("unknown", "incomplete_or_unsupported_policy_context", None)


def _bound_tree(policies: tuple[Mapping[str, object], ...]) -> None:
    pending: list[tuple[object, int]] = [(policy, 0) for policy in policies]
    remaining = 20_000
    while pending:
        value, depth = pending.pop()
        remaining -= 1
        if remaining < 0 or depth > 12 or len(pending) > 20_000:
            raise UnsupportedPolicyError("policy_analysis_budget_exceeded")
        if isinstance(value, Mapping):
            if len(value) > 128:
                raise UnsupportedPolicyError("policy_mapping_budget_exceeded")
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            if len(value) > 128:
                raise UnsupportedPolicyError("policy_sequence_budget_exceeded")
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str) and len(value) > 2048:
            raise UnsupportedPolicyError("policy_text_budget_exceeded")


def _endpoint(endpoint: PodPolicyEndpoint) -> None:
    if endpoint.host_network is not False:
        raise UnsupportedPolicyError("host_network_not_supported")
    for value in (endpoint.cluster_ref, endpoint.namespace, endpoint.uid):
        _text(value)
    for pairs in (endpoint.labels, endpoint.namespace_labels):
        if len(pairs) > 64 or len(dict(pairs)) != len(pairs):
            raise UnsupportedPolicyError("invalid_endpoint_labels")
        _labels(dict(pairs))
    if dict(endpoint.namespace_labels).get("kubernetes.io/metadata.name") != endpoint.namespace:
        raise UnsupportedPolicyError("namespace_identity_not_bound")


def _direction(
    policies: list[tuple[str, Mapping[str, object]]],
    target: PodPolicyEndpoint,
    peer: PodPolicyEndpoint,
    direction: str,
    port: int,
    protocol: str,
) -> bool:
    isolated = False
    allowed = False
    for namespace, spec in policies:
        types = spec.get(
            "policyTypes", ["Ingress", "Egress"] if spec.get("egress") else ["Ingress"]
        )
        if (
            not isinstance(types, list)
            or not types
            or any(value not in ("Ingress", "Egress") for value in types)
            or len(types) != len(set(types))
        ):
            raise UnsupportedPolicyError("unsupported_policy_types")
        if namespace != target.namespace or direction not in types:
            continue
        if not _selector(spec["podSelector"], dict(target.labels)):
            continue
        isolated = True
        rules = _sequence(spec.get(direction.lower(), []))
        for raw_rule in rules:
            rule = _mapping(raw_rule)
            peer_key = "from" if direction == "Ingress" else "to"
            if set(rule) - {peer_key, "ports"}:
                raise UnsupportedPolicyError("unsupported_policy_rule")
            peers = _sequence(rule.get(peer_key, []))
            ports = _sequence(rule.get("ports", []))
            peer_matches = [_peer(_mapping(value), peer, namespace) for value in peers]
            port_matches = [_port(_mapping(value), port, protocol) for value in ports]
            if (not peers or any(peer_matches)) and (not ports or any(port_matches)):
                allowed = True
    return not isolated or allowed


def _peer(value: Mapping[str, object], endpoint: PodPolicyEndpoint, namespace: str) -> bool:
    if set(value) - {"namespaceSelector", "podSelector"}:
        raise UnsupportedPolicyError("ipblock_or_unknown_peer_not_supported")
    namespace_matches = True
    if "namespaceSelector" in value:
        namespace_matches = _selector(value["namespaceSelector"], dict(endpoint.namespace_labels))
    elif "podSelector" in value:
        namespace_matches = endpoint.namespace == namespace
    pod_matches = "podSelector" not in value or _selector(
        value["podSelector"], dict(endpoint.labels)
    )
    return namespace_matches and pod_matches


def _port(value: Mapping[str, object], port: int, protocol: str) -> bool:
    if set(value) - {"port", "endPort", "protocol"}:
        raise UnsupportedPolicyError("unsupported_port_fields")
    selected_protocol = value.get("protocol", "TCP")
    if selected_protocol not in ("TCP", "UDP", "SCTP"):
        raise UnsupportedPolicyError("unsupported_protocol")
    minimum = value.get("port", 1)
    maximum = value.get("endPort", value.get("port", 65535))
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or not 1 <= minimum <= maximum <= 65535
        or ("endPort" in value and "port" not in value)
    ):
        raise UnsupportedPolicyError("named_or_invalid_port_not_supported")
    return selected_protocol == protocol and minimum <= port <= maximum


def _selector(value: object, labels: Mapping[str, str]) -> bool:
    selector = _mapping(value)
    if set(selector) - {"matchLabels", "matchExpressions"}:
        raise UnsupportedPolicyError("unsupported_selector")
    required = _labels(selector.get("matchLabels", {}))
    matched = all(labels.get(key) == expected for key, expected in required.items())
    for raw_expression in _sequence(selector.get("matchExpressions", [])):
        expression = _mapping(raw_expression)
        if set(expression) - {"key", "operator", "values"}:
            raise UnsupportedPolicyError("unsupported_selector_expression")
        key = _text(expression.get("key"))
        operator = expression.get("operator")
        values = [_text(item) for item in _sequence(expression.get("values", []))]
        if operator in ("In", "NotIn") and values:
            match = labels.get(key) in values
            matched = matched and (match if operator == "In" else not match)
        elif operator in ("Exists", "DoesNotExist") and not values:
            matched = matched and ((key in labels) if operator == "Exists" else (key not in labels))
        else:
            raise UnsupportedPolicyError("unsupported_selector_operator")
    return matched


def _mapping(value: object) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or len(value) > 128
        or any(not isinstance(key, str) for key in value)
    ):
        raise UnsupportedPolicyError("invalid_policy_mapping")
    return value


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list) or len(value) > 128:
        raise UnsupportedPolicyError("invalid_policy_sequence")
    return value


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
    ):
        raise UnsupportedPolicyError("invalid_policy_text")
    return value


def _labels(value: object) -> dict[str, str]:
    labels = _mapping(value)
    if len(labels) > 64:
        raise UnsupportedPolicyError("label_limit")
    return {_text(key): _text(item) for key, item in labels.items()}

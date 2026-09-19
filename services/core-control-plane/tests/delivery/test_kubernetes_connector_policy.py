"""Policy unions never substitute for CNI enforcement or execution authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.kubernetes_connector_policy import PodPolicyEndpoint, assess_policy_flow

NOW = datetime(2026, 9, 19, tzinfo=UTC)
SOURCE = PodPolicyEndpoint(
    "example",
    "frontend",
    "source",
    (("role", "web"),),
    (("kubernetes.io/metadata.name", "frontend"),),
)
DESTINATION = PodPolicyEndpoint(
    "example",
    "backend",
    "destination",
    (("role", "api"),),
    (("kubernetes.io/metadata.name", "backend"),),
)


def policy(
    spec: dict[str, object], *, name: str = "example", namespace: str = "backend"
) -> dict[str, object]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": namespace, "uid": name, "resourceVersion": "1"},
        "spec": {"podSelector": {}, **spec},
    }


def assess(*policies: dict[str, object], **changes: object):
    arguments = dict(
        source=SOURCE,
        destination=DESTINATION,
        policies=policies,
        port=443,
        protocol="TCP",
        complete=True,
        observed_at=NOW,
        now=NOW,
    )
    arguments.update(changes)
    return assess_policy_flow(**arguments)


def test_unisolated_and_deny_all() -> None:
    assert assess().disposition == "allowed"
    assert assess(policy({"policyTypes": ["Ingress"]})).disposition == "blocked"


def test_allow_all_union_defeats_added_deny_all() -> None:
    result = assess(
        policy({"ingress": [{}]}, name="allow"), policy({"policyTypes": ["Ingress"]}, name="deny")
    )
    assert result.disposition == "allowed"
    assert result.execution_authority is False
    assert result.reason == "configuration_only_not_enforcement_evidence"


def test_both_directions_must_allow() -> None:
    assert (
        assess(
            policy({"ingress": [{}]}),
            policy({"policyTypes": ["Egress"]}, name="egress", namespace="frontend"),
        ).disposition
        == "blocked"
    )


def test_namespace_and_pod_selectors_are_intersection() -> None:
    peer = {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "frontend"}},
        "podSelector": {"matchLabels": {"role": "web"}},
    }
    matching = policy({"ingress": [{"from": [peer], "ports": [{"port": 443}]}]})
    assert assess(matching).disposition == "allowed"
    assert (
        assess(matching, source=replace(SOURCE, labels=(("role", "other"),))).disposition
        == "blocked"
    )
    assert assess(matching, port=80).disposition == "blocked"


def test_pod_selector_without_namespace_selector_is_local() -> None:
    assert assess(policy({"ingress": [{"from": [{"podSelector": {}}]}]})).disposition == "blocked"
    assert assess(policy({"ingress": [{"from": [{}]}]})).disposition == "allowed"


@pytest.mark.parametrize(
    "operator,values,expected",
    [
        ("In", ["web"], "allowed"),
        ("NotIn", ["web"], "blocked"),
        ("Exists", [], "allowed"),
        ("DoesNotExist", [], "blocked"),
    ],
)
def test_selector_expressions(operator: str, values: list[str], expected: str) -> None:
    peer = {
        "namespaceSelector": {},
        "podSelector": {
            "matchExpressions": [{"key": "role", "operator": operator, "values": values}]
        },
    }
    assert assess(policy({"ingress": [{"from": [peer]}]})).disposition == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"observed_at": NOW - timedelta(minutes=5)},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"source": replace(SOURCE, host_network=True)},
        {"source": replace(SOURCE, cluster_ref="other")},
        {"source": replace(SOURCE, namespace_labels=())},
        {"port": True},
    ],
)
def test_incomplete_context_is_unknown(changes: dict[str, object]) -> None:
    assert assess(**changes).disposition == "unknown"


@pytest.mark.parametrize(
    "rule",
    [
        {"ports": [{"port": "https"}]},
        {"from": [{"ipBlock": {"cidr": "192.0.2.0/24"}}]},
        {"from": [{"podSelector": {"unknown": True}}]},
        {"ports": [{"port": True}]},
        {"ports": [{"endPort": 443}]},
    ],
)
def test_unsupported_semantics_remain_unknown(rule: dict[str, object]) -> None:
    assert assess(policy({"ingress": [rule]})).disposition == "unknown"


def test_duplicate_policy_and_port_range() -> None:
    document = policy({"ingress": [{"ports": [{"port": 440, "endPort": 450}]}]})
    assert assess(document).disposition == "allowed"
    assert assess(document, port=451).disposition == "blocked"
    assert assess(document, document).disposition == "unknown"


def test_policy_digest_is_independent_of_list_order() -> None:
    allowed = policy({"ingress": [{}]}, name="allow")
    blocked = policy({"ingress": []}, name="deny")
    assert assess(allowed, blocked).policy_digest == assess(blocked, allowed).policy_digest


def test_cyclic_and_oversized_policy_inputs_are_bounded() -> None:
    cyclic: dict[str, object] = {}
    cyclic["cycle"] = cyclic
    assert assess(policy(cyclic)).disposition == "unknown"
    assert assess(policy({"ingress": [{}] * 129})).disposition == "unknown"
    documents = [policy({"ingress": [{}] * 128}, name=f"example-{number}") for number in range(256)]
    assert assess(*documents).disposition == "unknown"

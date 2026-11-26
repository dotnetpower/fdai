"""Kubernetes cluster binding boundary tests."""

from __future__ import annotations

import json

import pytest
from fdai.delivery.kubernetes_cluster_binding import parse_kubernetes_cluster_bindings

CLUSTER_ONE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-one/"
    "providers/Microsoft.ContainerService/managedClusters/aks-one"
)
CLUSTER_TWO = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-two/"
    "providers/Microsoft.ContainerService/managedClusters/aks-two"
)


def _binding(*, cluster_ref: str, api_server: str) -> dict[str, str]:
    return {
        "api_server": api_server,
        "cluster_ref": cluster_ref,
        "auth_mode": "workload-identity",
        "ca_path": "/var/run/fdai/ca.crt",
        "audience": "api://aks-reader/.default",
    }


def test_parses_multiple_exact_cluster_bindings() -> None:
    bindings = parse_kubernetes_cluster_bindings(
        json.dumps(
            [
                _binding(cluster_ref=CLUSTER_ONE, api_server="https://one.example"),
                _binding(cluster_ref=CLUSTER_TWO, api_server="https://two.example"),
            ]
        )
    )

    assert [binding.cluster_ref for binding in bindings] == [CLUSTER_ONE, CLUSTER_TWO]
    assert len({binding.scope_digest for binding in bindings}) == 2
    assert all(binding.scope_digest.startswith("sha256:") for binding in bindings)


@pytest.mark.parametrize(
    "payload,match",
    [
        (
            [
                _binding(cluster_ref=CLUSTER_ONE, api_server="https://one.example"),
                _binding(cluster_ref=CLUSTER_ONE, api_server="https://two.example"),
            ],
            "cluster_ref values MUST be unique",
        ),
        (
            [
                _binding(cluster_ref=CLUSTER_ONE, api_server="https://one.example"),
                _binding(cluster_ref=CLUSTER_TWO, api_server="https://one.example"),
            ],
            "api_server values MUST be unique",
        ),
        (
            [
                {
                    **_binding(cluster_ref=CLUSTER_ONE, api_server="https://one.example"),
                    "token": "not-accepted",
                }
            ],
            "only supported fields",
        ),
    ],
)
def test_rejects_ambiguous_or_credential_bearing_bindings(
    payload: list[dict[str, str]],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_kubernetes_cluster_bindings(json.dumps(payload))

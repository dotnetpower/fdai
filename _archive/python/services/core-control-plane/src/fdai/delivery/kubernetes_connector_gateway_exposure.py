"""Choose how a connector gateway is reachable from an observer's network.

The decision reads only network topology. An internal load balancer is the simpler path when the
observer's network is the gateway's network, is peered with it, or can be peered because the
address spaces are disjoint. Private Link is used when peering is impossible (overlapping address
space) or the observer's network cannot be read (for example another tenant), because it needs no
route between the networks. Unknown topology is never treated as connectivity.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.kubernetes_connector_azure_preflight import (
    CLUSTER_API_VERSION,
    ManagementReader,
)

NETWORK_API_VERSION = "2024-05-01"
Exposure = Literal["internal_load_balancer", "private_link_service"]
Reason = Literal[
    "same_network", "peered", "peering_possible", "address_overlap", "observer_network_unreadable"
]


@dataclass(frozen=True, slots=True)
class NetworkTopology:
    """One network as ARM reports it; `None` means it could not be read."""

    vnet_id: str
    address_prefixes: tuple[str, ...]
    connected_peers: frozenset[str]


@dataclass(frozen=True, slots=True)
class ExposureDecision:
    exposure: Exposure
    reason: Reason
    requires_peering: bool
    evidence_digest: str


def decide_gateway_exposure(
    gateway: NetworkTopology, observer: NetworkTopology | None
) -> ExposureDecision:
    """Pick the least complex reachable exposure; never infer a route that was not observed."""
    evidence = canonical_digest(
        {
            "gateway": [gateway.vnet_id.casefold(), sorted(gateway.address_prefixes)],
            "observer": None
            if observer is None
            else [observer.vnet_id.casefold(), sorted(observer.address_prefixes)],
        }
    )
    if observer is None:
        return ExposureDecision(
            "private_link_service", "observer_network_unreadable", False, evidence
        )
    if observer.vnet_id.casefold() == gateway.vnet_id.casefold():
        return ExposureDecision("internal_load_balancer", "same_network", False, evidence)
    if (
        observer.vnet_id.casefold() in gateway.connected_peers
        or gateway.vnet_id.casefold() in observer.connected_peers
    ):
        return ExposureDecision("internal_load_balancer", "peered", False, evidence)
    if _overlaps(gateway.address_prefixes, observer.address_prefixes):
        return ExposureDecision("private_link_service", "address_overlap", False, evidence)
    return ExposureDecision("internal_load_balancer", "peering_possible", True, evidence)


def _overlaps(left: Sequence[str], right: Sequence[str]) -> bool:
    try:
        first = [ipaddress.ip_network(item, strict=False) for item in left]
        second = [ipaddress.ip_network(item, strict=False) for item in right]
    except ValueError:
        return True
    return any(a.overlaps(b) for a in first for b in second if a.version == b.version)


async def read_cluster_network(reader: ManagementReader, cluster_id: str) -> NetworkTopology | None:
    """Read the network that hosts a cluster's nodes; return None when any read fails."""
    try:
        cluster = await reader.get(cluster_id, CLUSTER_API_VERSION)
        properties = cluster.get("properties") or {}
        pools = properties.get("agentPoolProfiles") or []
        subnet = next((p.get("vnetSubnetID") for p in pools if p.get("vnetSubnetID")), None)
        if subnet:
            vnet_id = subnet.rsplit("/subnets/", 1)[0]
        else:
            vnet_id = await _managed_network(reader, cluster_id, properties)
        return _topology(await reader.get(vnet_id, NETWORK_API_VERSION))
    except (ValueError, OSError, KeyError, StopIteration):
        return None


async def _managed_network(
    reader: ManagementReader, cluster_id: str, properties: Mapping[str, Any]
) -> str:
    subscription = cluster_id.split("/")[2]
    node_group = str(properties["nodeResourceGroup"])
    listing = await reader.get(
        f"/subscriptions/{subscription}/resourceGroups/{node_group}"
        "/providers/Microsoft.Network/virtualNetworks",
        NETWORK_API_VERSION,
    )
    networks = listing.get("value") or []
    if len(networks) != 1:
        raise ValueError("managed cluster network is ambiguous")
    return str(networks[0]["id"])


def _topology(vnet: Mapping[str, Any]) -> NetworkTopology:
    properties = vnet.get("properties") or {}
    peers = frozenset(
        str(
            (peering.get("properties") or {}).get("remoteVirtualNetwork", {}).get("id", "")
        ).casefold()
        for peering in properties.get("virtualNetworkPeerings") or []
        if (peering.get("properties") or {}).get("peeringState") == "Connected"
    )
    prefixes = tuple(
        str(item) for item in (properties.get("addressSpace") or {}).get("addressPrefixes") or []
    )
    if not vnet.get("id") or not prefixes:
        raise ValueError("network response is incomplete")
    return NetworkTopology(str(vnet["id"]), prefixes, peers - {""})

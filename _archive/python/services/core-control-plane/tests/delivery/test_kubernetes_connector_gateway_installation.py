"""The gateway is an ordinary restricted workload whose exposure follows observed topology."""

import copy
import json
from datetime import UTC, datetime

import pytest
from fdai.delivery.kubernetes_connector_gateway_exposure import (
    NetworkTopology,
    decide_gateway_exposure,
    read_cluster_network,
)
from fdai.delivery.kubernetes_connector_gateway_installation import (
    GatewayInstallationInput,
    render_gateway_installation,
)
from fdai.delivery.kubernetes_connector_material import MATERIAL_FILES, material_digest

NOW = datetime(2026, 1, 1, tzinfo=UTC)
GATEWAY = NetworkTopology("/subscriptions/s/vnet-gateway", ("10.1.0.0/16",), frozenset())


def topology(vnet, prefixes, peers=()):
    return NetworkTopology(vnet, tuple(prefixes), frozenset(peers))


@pytest.mark.parametrize(
    ("observer", "exposure", "reason", "peering"),
    [
        (
            topology("/SUBSCRIPTIONS/s/vnet-gateway", ["10.1.0.0/16"]),
            "internal_load_balancer",
            "same_network",
            False,
        ),
        (
            topology(
                "/subscriptions/s/vnet-observer", ["10.2.0.0/16"], ["/subscriptions/s/vnet-gateway"]
            ),
            "internal_load_balancer",
            "peered",
            False,
        ),
        (
            topology("/subscriptions/s/vnet-observer", ["10.2.0.0/16"]),
            "internal_load_balancer",
            "peering_possible",
            True,
        ),
        (
            topology("/subscriptions/s/vnet-observer", ["10.1.5.0/24"]),
            "private_link_service",
            "address_overlap",
            False,
        ),
        (None, "private_link_service", "observer_network_unreadable", False),
    ],
)
def test_exposure_follows_what_the_topology_proves(observer, exposure, reason, peering) -> None:
    decision = decide_gateway_exposure(GATEWAY, observer)
    assert (decision.exposure, decision.reason, decision.requires_peering) == (
        exposure,
        reason,
        peering,
    )
    assert decision.evidence_digest.startswith("sha256:")


def test_a_peering_seen_from_either_side_counts_and_invalid_prefixes_never_look_disjoint() -> None:
    gateway = topology(
        "/subscriptions/s/vnet-gateway", ["10.1.0.0/16"], ["/subscriptions/s/vnet-observer"]
    )
    assert (
        decide_gateway_exposure(
            gateway, topology("/subscriptions/s/vnet-observer", ["10.2.0.0/16"])
        ).reason
        == "peered"
    )
    broken = topology("/subscriptions/s/vnet-observer", ["not-a-network"])
    assert decide_gateway_exposure(GATEWAY, broken).reason == "address_overlap"


class Reader:
    def __init__(self, responses):
        self.responses = responses

    async def get(self, path, api_version):
        if path not in self.responses:
            raise ValueError("unavailable")
        return self.responses[path]


def vnet(vnet_id, prefixes, peers=()):
    return {
        "id": vnet_id,
        "properties": {
            "addressSpace": {"addressPrefixes": prefixes},
            "virtualNetworkPeerings": [
                {"properties": {"peeringState": state, "remoteVirtualNetwork": {"id": peer}}}
                for peer, state in peers
            ],
        },
    }


CLUSTER = (
    "/subscriptions/s1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks"
)


@pytest.mark.asyncio
async def test_a_cluster_network_is_read_from_its_subnet_or_its_managed_resource_group() -> None:
    custom = {
        CLUSTER: {
            "properties": {
                "agentPoolProfiles": [{"vnetSubnetID": "/subscriptions/s1/v/vnet-a/subnets/nodes"}]
            }
        },
        "/subscriptions/s1/v/vnet-a": vnet(
            "/subscriptions/s1/v/vnet-a",
            ["10.9.0.0/16"],
            [
                ("/subscriptions/s1/v/vnet-b", "Connected"),
                ("/subscriptions/s1/v/vnet-c", "Disconnected"),
            ],
        ),
    }
    found = await read_cluster_network(Reader(custom), CLUSTER)
    assert found.address_prefixes == ("10.9.0.0/16",)
    assert found.connected_peers == frozenset({"/subscriptions/s1/v/vnet-b"})
    managed = {
        CLUSTER: {"properties": {"agentPoolProfiles": [{}], "nodeResourceGroup": "MC_rg"}},
        "/subscriptions/s1/resourceGroups/MC_rg/providers/Microsoft.Network/virtualNetworks": {
            "value": [{"id": "/subscriptions/s1/v/aks-vnet"}]
        },
        "/subscriptions/s1/v/aks-vnet": vnet("/subscriptions/s1/v/aks-vnet", ["10.224.0.0/12"]),
    }
    assert (await read_cluster_network(Reader(managed), CLUSTER)).vnet_id.endswith("aks-vnet")


@pytest.mark.asyncio
async def test_an_unreadable_ambiguous_or_incomplete_network_is_none() -> None:
    assert await read_cluster_network(Reader({}), CLUSTER) is None
    two = {
        CLUSTER: {"properties": {"agentPoolProfiles": [{}], "nodeResourceGroup": "MC_rg"}},
        "/subscriptions/s1/resourceGroups/MC_rg/providers/Microsoft.Network/virtualNetworks": {
            "value": [{"id": "a"}, {"id": "b"}]
        },
    }
    assert await read_cluster_network(Reader(two), CLUSTER) is None
    empty = {
        CLUSTER: {"properties": {"agentPoolProfiles": [{"vnetSubnetID": "/x/vnet-a/subnets/n"}]}},
        "/x/vnet-a": {"id": "/x/vnet-a", "properties": {"addressSpace": {"addressPrefixes": []}}},
    }
    assert await read_cluster_network(Reader(empty), CLUSTER) is None


def material(tmp_path, **config):
    value = {
        "role": "gateway",
        "registration_path": "/private/material/registrations.json",
        "tls_ca_path": "/private/material/ca.pem",
        "tls_certificate_path": "/private/material/client.pem",
        "tls_key_path": "/private/material/client.key",
        "listen_host": "0.0.0.0",  # noqa: S104
        "listen_port": 8443,
        **config,
    }
    files = {name: b"x" for name in MATERIAL_FILES}
    files["config.json"] = json.dumps(value).encode()
    for name, content in files.items():
        path = tmp_path / name
        path.write_bytes(content)
        path.chmod(0o600)
    return material_digest(files)


def inputs(digest, **changes):
    value = {
        "namespace": "fdai-gateway",
        "name": "fdai-gateway-example",
        "image": "registry.example/core@sha256:" + "a" * 64,
        "material_secret": "gateway-material",
        "material_digest": digest,
        "database_secret": "gateway-database",
        "database_cidrs": ["10.1.2.0/24"],
        "ingress_cidrs": ["10.2.0.0/16"],
        "dns_cidrs": ["10.0.0.0/24"],
        "exposure": "internal_load_balancer",
        **changes,
    }
    return GatewayInstallationInput.model_validate(value)


def render(tmp_path, **changes):
    digest = material(tmp_path)
    decision = decide_gateway_exposure(
        GATEWAY, topology("/subscriptions/s/o", ["10.2.0.0/16"], ["/subscriptions/s/vnet-gateway"])
    )
    given = inputs(digest, **changes)
    if given.exposure == "private_link_service":
        decision = decide_gateway_exposure(GATEWAY, None)
    return render_gateway_installation(given, decision, now=NOW, material_directory=tmp_path)


def by_kind(rendered):
    return {item["kind"]: item for item in rendered["documents"]}


def test_the_recipe_is_restricted_and_has_no_kubernetes_api_access(tmp_path) -> None:
    rendered = render(tmp_path)
    documents = by_kind(rendered)
    assert set(documents) == {"ServiceAccount", "Deployment", "Service", "NetworkPolicy"}
    pod = documents["Deployment"]["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert all(pod[key] is False for key in ("hostNetwork", "hostPID", "hostIPC"))
    for container in [*pod["initContainers"], *pod["containers"]]:
        security = container["securityContext"]
        assert security["privileged"] is False and security["readOnlyRootFilesystem"] is True
        assert security["capabilities"] == {"drop": ["ALL"]}
    env = pod["containers"][0]["env"]
    dsn = next(item for item in env if item["name"] == "FDAI_STATE_STORE_DSN")
    assert "value" not in dsn and dsn["valueFrom"]["secretKeyRef"]["name"] == "gateway-database"
    assert rendered["execution_authority"] is False and rendered["approval_required"] is True
    assert documents["Deployment"]["spec"]["replicas"] == 2


def test_the_service_is_never_public_and_private_link_adds_only_its_annotations(tmp_path) -> None:
    internal = by_kind(render(tmp_path))["Service"]
    annotations = internal["metadata"]["annotations"]
    assert annotations["service.beta.kubernetes.io/azure-load-balancer-internal"] == "true"
    assert not [key for key in annotations if "azure-pls" in key]
    link = by_kind(
        render(
            tmp_path,
            exposure="private_link_service",
            private_link_subnet="pls-nat",
            private_link_subscriptions=["subscription-example"],
        )
    )["Service"]["metadata"]["annotations"]
    assert link["service.beta.kubernetes.io/azure-pls-create"] == "true"
    assert link["service.beta.kubernetes.io/azure-pls-ip-configuration-subnet"] == "pls-nat"
    assert link["service.beta.kubernetes.io/azure-load-balancer-internal"] == "true"


def test_ingress_and_egress_are_bounded(tmp_path) -> None:
    policy = by_kind(render(tmp_path))["NetworkPolicy"]["spec"]
    assert policy["ingress"][0]["from"] == [{"ipBlock": {"cidr": "10.2.0.0/16"}}]
    assert [rule["ports"][0]["port"] for rule in policy["egress"]] == [5432, 53]


def test_a_decision_that_disagrees_with_the_input_or_the_material_is_refused(tmp_path) -> None:
    digest = material(tmp_path)
    decision = decide_gateway_exposure(GATEWAY, None)
    with pytest.raises(ValueError, match="differs from the topology"):
        render_gateway_installation(inputs(digest), decision, now=NOW, material_directory=tmp_path)
    good = decide_gateway_exposure(
        GATEWAY, topology("/subscriptions/s/o", ["10.2.0.0/16"], ["/subscriptions/s/vnet-gateway"])
    )
    with pytest.raises(ValueError, match="digest differs"):
        render_gateway_installation(
            inputs("sha256:" + "0" * 64), good, now=NOW, material_directory=tmp_path
        )
    other = tmp_path / "other"
    other.mkdir()
    bad = material(other, listen_host="127.0.0.1")
    with pytest.raises(ValueError, match="listen on every Pod address"):
        render_gateway_installation(inputs(bad), good, now=NOW, material_directory=other)
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    changed = material(wrong, tls_key_path="/elsewhere/client.key")
    with pytest.raises(ValueError, match="fixed recipe paths"):
        render_gateway_installation(inputs(changed), good, now=NOW, material_directory=wrong)


@pytest.mark.parametrize(
    "change",
    [
        {"namespace": "kube-system"},
        {"namespace": "default"},
        {"name": "other-name"},
        {"image": "registry.example/core:latest"},
        {"database_cidrs": ["0.0.0.0/0"]},
        {"ingress_cidrs": ["10.0.0.0/8"]},
        {"ingress_cidrs": ["fd00::/32"]},
        {"replicas": 0},
        {"exposure": "private_link_service"},
    ],
)
def test_unsafe_inputs_are_refused(tmp_path, change) -> None:
    with pytest.raises(ValueError):
        inputs(material(tmp_path), **change)


def test_an_in_cluster_state_store_is_selected_by_pod_labels(tmp_path) -> None:
    rendered = render(
        tmp_path,
        database_cidrs=[],
        database_peer={"namespace": "fdai-database", "labels": {"app": "postgres"}},
    )
    peer = by_kind(rendered)["NetworkPolicy"]["spec"]["egress"][0]["to"]
    assert peer == [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "fdai-database"}},
            "podSelector": {"matchLabels": {"app": "postgres"}},
        }
    ]
    with pytest.raises(ValueError, match="state store needs"):
        inputs(material(tmp_path), database_cidrs=[])


def test_a_same_cluster_observer_is_admitted_by_labels_not_addresses(tmp_path) -> None:
    rendered = render(
        tmp_path,
        ingress_cidrs=[],
        ingress_peers=[{"namespace": "fdai-observers", "labels": {"app": "observer"}}],
    )
    rule = by_kind(rendered)["NetworkPolicy"]["spec"]["ingress"][0]["from"]
    assert rule == [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "fdai-observers"}},
            "podSelector": {"matchLabels": {"app": "observer"}},
        }
    ]
    with pytest.raises(ValueError, match="ingress networks or in-cluster peers"):
        inputs(material(tmp_path), ingress_cidrs=[])


def test_the_deployed_venue_is_set_so_a_remote_database_is_allowed(tmp_path) -> None:
    pod = by_kind(render(tmp_path))["Deployment"]["spec"]["template"]["spec"]
    env = {item["name"]: item.get("value") for item in pod["containers"][0]["env"]}
    assert env["FDAI_EXECUTION_VENUE"] == "deployed"


def test_rendering_is_deterministic_and_does_not_mutate_inputs(tmp_path) -> None:
    first, second = render(tmp_path), render(tmp_path)
    assert first["manifest_digest"] == second["manifest_digest"]
    assert copy.deepcopy(first) == second

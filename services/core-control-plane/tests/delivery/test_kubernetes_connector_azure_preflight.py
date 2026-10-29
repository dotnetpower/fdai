"""Azure management and ownership constraint evidence is necessary-condition only."""

import asyncio
import hashlib
import json
import ssl
from datetime import timedelta

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fdai.delivery.kubernetes_connector_azure_preflight import (
    AzureManagementPreflight,
)
from fdai.delivery.kubernetes_connector_management_reader import AzCliManagementReader
from fdai.delivery.kubernetes_connector_management_runtime import (
    collect_azure_preflight,
    collect_ownership_preflight,
)
from fdai.delivery.kubernetes_connector_ownership_preflight import (
    KubernetesObserverOwnershipPreflight,
)

from .test_kubernetes_connector_installation import install_inputs
from .test_kubernetes_connector_spool import NOW

SUB = "00000000-0000-0000-0000-00000000aaaa"
CLUSTER = (
    f"/subscriptions/{SUB}/resourceGroups/rg-example/providers/"
    "Microsoft.ContainerService/managedClusters/aks-example"
)
POLICY_PATH = f"{CLUSTER}/providers/Microsoft.Authorization/policyAssignments"
DEFINITION = "/providers/Microsoft.Authorization/policyDefinitions/definition-one"
SET = "/providers/Microsoft.Authorization/policySetDefinitions/set-one"


class FakeReader:
    def __init__(self, responses):
        self.responses, self.paths = responses, []

    async def get(self, path, api_version):
        self.paths.append(path)
        if path not in self.responses:
            raise ValueError("unavailable")
        return self.responses[path]


def cluster(**profile):
    body = {
        "id": CLUSTER,
        "properties": {
            "powerState": {"code": profile.pop("power", "Running")},
            "apiServerAccessProfile": {"enablePrivateCluster": True, **profile},
            "networkProfile": {"outboundType": profile.pop("outbound", "loadBalancer")},
        },
    }
    return body


def collector(responses, *, origin="https://10.0.0.4:8443", allows=True, resolver=None):
    return AzureManagementPreflight(
        cluster_id=CLUSTER,
        reader=FakeReader(responses),
        gateway_origin=origin,
        run_command_profile_allows=allows,
        now=lambda: NOW,
        resolver=resolver,
    )


def states(facts):
    return {fact.name: fact.state for fact in facts}


def base(**changes):
    responses = {CLUSTER: cluster(), POLICY_PATH: {"value": []}}
    responses.update(changes)
    return responses


@pytest.mark.asyncio
async def test_an_unreadable_cluster_leaves_every_fact_unknown() -> None:
    facts = await collector({}).collect()
    assert set(states(facts).values()) == {"unknown"}
    assert len(facts) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "allows", "expected"),
    [
        ({}, True, "allowed"),
        ({"disableRunCommand": True}, True, "denied"),
        ({}, False, "denied"),
        ({"power": "Stopped"}, True, "unknown"),
    ],
)
async def test_run_command_needs_an_enabled_feature_a_running_cluster_and_the_profile(
    profile, allows, expected
) -> None:
    facts = await collector(base(**{CLUSTER: cluster(**profile)}), allows=allows).collect()
    assert states(facts)["run_command_authorized"] == expected


@pytest.mark.asyncio
async def test_no_assignment_means_no_policy_blocker() -> None:
    facts = await collector(base()).collect()
    assert states(facts)["azure_policy"] == "allowed"


def assignment(definition=DEFINITION, **properties):
    return {
        "value": [
            {
                "properties": {
                    "policyDefinitionId": definition,
                    "enforcementMode": "Default",
                    **properties,
                }
            }
        ]
    }


def definition(effect, *, mode="All", defaults=None):
    return {
        "properties": {
            "mode": mode,
            "parameters": {"effect": {"defaultValue": defaults}} if defaults else {},
            "policyRule": {
                "if": {"field": "type", "equals": "Microsoft.ContainerService/managedClusters"},
                "then": {"effect": effect},
            },
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "assigned", "expected"),
    [
        (definition("deny"), {}, "unknown"),
        (definition("audit"), {}, "allowed"),
        (definition("[parameters('effect')]", defaults="Audit"), {}, "allowed"),
        (
            definition("[parameters('effect')]", defaults="Audit"),
            {"parameters": {"effect": {"value": "Deny"}}},
            "unknown",
        ),
        (definition("[parameters('missing')]"), {}, "unknown"),
        (definition("deny", mode="Microsoft.Kubernetes.Data"), {}, "allowed"),
        (definition("deny"), {"enforcementMode": "DoNotEnforce"}, "allowed"),
    ],
)
async def test_only_a_deny_capable_cluster_policy_needs_review(body, assigned, expected) -> None:
    responses = base(**{POLICY_PATH: assignment(**assigned), DEFINITION: body})
    facts = await collector(responses).collect()
    assert states(facts)["azure_policy"] == expected


@pytest.mark.asyncio
async def test_a_policy_set_resolves_the_member_effect_through_its_parameters() -> None:
    responses = base(
        **{
            POLICY_PATH: assignment(SET, parameters={"setEffect": {"value": "Deny"}}),
            SET: {
                "properties": {
                    "parameters": {"setEffect": {"defaultValue": "Audit"}},
                    "policyDefinitions": [
                        {
                            "policyDefinitionId": DEFINITION,
                            "parameters": {"effect": {"value": "[parameters('setEffect')]"}},
                        }
                    ],
                }
            },
            DEFINITION: definition("[parameters('effect')]"),
        }
    )
    assert states(await collector(responses).collect())["azure_policy"] == "unknown"
    responses[POLICY_PATH] = assignment(SET)
    assert states(await collector(responses).collect())["azure_policy"] == "allowed"


@pytest.mark.asyncio
async def test_an_incomplete_policy_read_never_becomes_permission() -> None:
    paged = base(**{POLICY_PATH: {"value": [], "nextLink": "https://example/next"}})
    assert states(await collector(paged).collect())["azure_policy"] == "unknown"
    missing = base(
        **{
            POLICY_PATH: assignment(),
        }
    )
    assert states(await collector(missing).collect())["azure_policy"] == "unknown"
    bad = base(**{POLICY_PATH: assignment("/subscriptions/x/other")})
    assert states(await collector(bad).collect())["azure_policy"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "outbound", "private", "public"),
    [
        ("https://10.0.0.4:8443", "loadBalancer", "allowed", "denied"),
        ("https://93.184.216.34:8443", "loadBalancer", "denied", "allowed"),
        ("https://93.184.216.34:8443", "userDefinedRouting", "denied", "unknown"),
    ],
)
async def test_route_classification_follows_the_gateway_address(
    origin, outbound, private, public
) -> None:
    body = cluster()
    body["properties"]["networkProfile"]["outboundType"] = outbound
    facts = await collector(base(**{CLUSTER: body}), origin=origin).collect()
    assert (states(facts)["private_egress"], states(facts)["public_egress"]) == (private, public)


@pytest.mark.asyncio
async def test_a_name_is_resolved_and_an_unresolved_name_is_unknown() -> None:
    async def private(_):
        return ["10.1.2.3"]

    async def failing(_):
        raise OSError

    named = "https://gateway.example:8443"
    ok = await collector(base(), origin=named, resolver=private).collect()
    assert states(ok)["private_egress"] == "allowed"
    unresolved = await collector(base(), origin=named, resolver=failing).collect()
    assert states(unresolved)["private_egress"] == "unknown"
    assert states(unresolved)["public_egress"] == "unknown"


def test_the_cluster_resource_id_and_gateway_origin_are_strict() -> None:
    with pytest.raises(ValueError, match="resource id"):
        AzureManagementPreflight(
            cluster_id="/subscriptions/x",
            reader=FakeReader({}),
            gateway_origin="https://10.0.0.4",
            run_command_profile_allows=True,
            now=lambda: NOW,
        )
    with pytest.raises(ValueError, match="HTTPS"):
        collector({}, origin="http://10.0.0.4")


@pytest.mark.asyncio
async def test_the_request_budget_is_bounded_and_answers_are_shared() -> None:
    prefix = "/providers/Microsoft.Authorization/policyDefinitions/definition-"
    members = [
        {"properties": {"policyDefinitionId": f"{prefix}{index}", "enforcementMode": "Default"}}
        for index in range(700)
    ]
    responses = base(**{POLICY_PATH: {"value": members}})
    responses.update({f"{prefix}{index}": definition("audit") for index in range(700)})
    reader = FakeReader(responses)
    facts = await AzureManagementPreflight(
        cluster_id=CLUSTER,
        reader=reader,
        gateway_origin="https://10.0.0.4",
        run_command_profile_allows=True,
        now=lambda: NOW,
    ).collect()
    assert states(facts)["azure_policy"] == "unknown"
    assert len(reader.paths) == 512
    same = base(
        **{POLICY_PATH: {"value": [assignment()["value"][0]] * 50}, DEFINITION: definition("audit")}
    )
    shared = FakeReader(same)
    await AzureManagementPreflight(
        cluster_id=CLUSTER,
        reader=shared,
        gateway_origin="https://10.0.0.4",
        run_command_profile_allows=True,
        now=lambda: NOW,
    ).collect()
    assert shared.paths.count(DEFINITION) == 1


def test_the_cli_reader_rejects_paths_that_could_change_the_request() -> None:
    reader = AzCliManagementReader()
    for path in ("relative", "/a?b=c", "/a b", "/a;b"):
        with pytest.raises(ValueError, match="invalid"):
            asyncio.run(reader.get(path, "2022-06-01"))


def signing_files(tmp_path, target, facts):
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "key.pem"
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    key_path.chmod(0o600)
    public = key.public_key().public_bytes_raw()
    grant = {
        "issuer_ref": "issuer-example",
        "key_ref": "sha256:" + hashlib.sha256(public).hexdigest(),
        "public_key": public.hex(),
        "target_ref": target,
        "allowed_facts": facts,
        "producer_revision": "sha256:" + "b" * 64,
        "valid_from": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    grants = tmp_path / "grants.json"
    grants.write_text(json.dumps([grant]))
    grants.chmod(0o600)
    return key_path, grants


def config_file(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_signed_azure_receipt_carries_only_the_granted_sources(tmp_path) -> None:
    from fdai.delivery.azure.arg_projection import to_neutral_id

    target = to_neutral_id(CLUSTER)
    allowed = {
        "azure_policy": ["azure_management"],
        "run_command_authorized": ["azure_management"],
        "private_egress": ["network_probe"],
        "public_egress": ["network_probe"],
    }
    key_path, grants = signing_files(tmp_path, target, allowed)
    value = {
        "target_ref": target,
        "discovery_digest": "sha256:" + "c" * 64,
        "issuer_ref": "issuer-example",
        "producer_revision": "sha256:" + "b" * 64,
        "signing_key_path": str(key_path),
        "grants_path": str(grants),
        "cluster_id": CLUSTER,
        "gateway_origin": "https://10.0.0.4:8443",
        "run_command_profile_allows": True,
    }
    receipt = await collect_azure_preflight(
        config_file(tmp_path, "azure.json", value), now=lambda: NOW, reader=FakeReader(base())
    )
    assert {fact.name for fact in receipt.context.facts} == set(allowed)
    narrow = {**allowed, "azure_policy": ["operator_review"]}
    key_path, grants = signing_files(tmp_path, target, narrow)
    value.update(signing_key_path=str(key_path), grants_path=str(grants))
    with pytest.raises(ValueError, match="verifier is unavailable"):
        await collect_azure_preflight(
            config_file(tmp_path, "azure2.json", value),
            now=lambda: NOW,
            reader=FakeReader(base()),
        )
    value["cluster_id"] = CLUSTER.replace("aks-example", "aks-other")
    with pytest.raises(ValueError, match="target differs"):
        await collect_azure_preflight(
            config_file(tmp_path, "azure3.json", value),
            now=lambda: NOW,
            reader=FakeReader(base()),
        )


class Auth:
    async def headers(self):
        return {"Authorization": "Bearer example"}


def kube(objects, *, uid="cluster-uid"):
    def handler(request):
        path = request.url.path
        if path == "/api/v1/namespaces/kube-system":
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "kube-system", "uid": uid},
                },
            )
        if path in objects:
            return httpx.Response(200, json=objects[path])
        return httpx.Response(404)

    return handler


NAMESPACE = "/api/v1/namespaces/fdai-observers"
JOB = "/apis/batch/v1/namespaces/fdai-observers/cronjobs/fdai-observer-example"


def labeled(owner):
    return {"metadata": {"labels": {"app.kubernetes.io/managed-by": owner} if owner else {}}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("objects", "expected"),
    [
        ({}, "allowed"),
        ({NAMESPACE: labeled("fdai-observer-install")}, "allowed"),
        (
            {NAMESPACE: labeled("fdai-observer-install"), JOB: labeled("fdai-observer-install")},
            "allowed",
        ),
        ({NAMESPACE: labeled(None)}, "denied"),
        ({NAMESPACE: labeled("helm")}, "denied"),
        ({NAMESPACE: labeled("fdai-observer-install"), JOB: labeled("someone")}, "denied"),
    ],
)
async def test_ownership_is_known_only_when_no_foreign_owner_holds_the_target(
    objects, expected
) -> None:
    inputs = install_inputs()
    probe = KubernetesObserverOwnershipPreflight(
        origin="https://api.example",
        target_ref=inputs.target_ref,
        namespace_uid="cluster-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(kube(objects)),
    )
    fact = await probe.collect_ownership(inputs)
    assert (fact.name, fact.state, fact.source) == ("ownership_known", expected, "kubernetes_api")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong-cluster", "server-error", "wrong-target"])
async def test_ownership_never_concludes_from_a_wrong_or_failing_cluster(case) -> None:
    inputs = install_inputs()

    def handler(request):
        if case == "server-error" and request.url.path == NAMESPACE:
            return httpx.Response(500)
        return kube({}, uid="other-cluster" if case == "wrong-cluster" else "cluster-uid")(request)

    probe = KubernetesObserverOwnershipPreflight(
        origin="https://api.example",
        target_ref="another-cluster" if case == "wrong-target" else inputs.target_ref,
        namespace_uid="cluster-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    if case == "wrong-target":
        with pytest.raises(ValueError, match="differs"):
            await probe.collect_ownership(inputs)
        return
    assert (await probe.collect_ownership(inputs)).state == "unknown"


def test_ownership_collector_is_exported_for_the_deployment_cli() -> None:
    assert callable(collect_ownership_preflight)

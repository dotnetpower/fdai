"""Resource preflight never substitutes approximate or incomplete evidence for readiness."""

from copy import deepcopy

import pytest
from fdai.delivery.kubernetes_connector_resource_checks import (
    snapshot_has_capacity,
    storage_is_bound,
)
from fdai.delivery.kubernetes_resource_accounting import PodResourceRequests


def node():
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {
            "name": "node-example",
            "uid": "node-uid",
            "resourceVersion": "1",
            "labels": {
                "kubernetes.io/os": "linux",
                "kubernetes.io/arch": "amd64",
            },
        },
        "spec": {},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "allocatable": {"cpu": "1", "memory": "1Gi", "pods": "10"},
        },
    }


def pod():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "pod-example",
            "namespace": "example",
            "uid": "pod-uid",
            "resourceVersion": "1",
        },
        "spec": {
            "nodeName": "node-example",
            "containers": [
                {
                    "resources": {
                        "requests": {"cpu": "900m", "memory": "896Mi"},
                    }
                }
            ],
        },
        "status": {"phase": "Running"},
    }


def volumes():
    claim = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": "example-spool",
            "namespace": "example",
            "uid": "claim-uid",
            "resourceVersion": "1",
        },
        "spec": {
            "volumeName": "volume-example",
            "storageClassName": "example-csi",
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
        },
        "status": {"phase": "Bound", "capacity": {"storage": "1Gi"}},
    }
    volume = {
        "apiVersion": "v1",
        "kind": "PersistentVolume",
        "metadata": {"name": "volume-example", "uid": "volume-uid", "resourceVersion": "1"},
        "spec": {
            "storageClassName": "example-csi",
            "accessModes": ["ReadWriteOnce"],
            "capacity": {"storage": "1Gi"},
            "claimRef": {"name": "example-spool", "namespace": "example", "uid": "claim-uid"},
        },
        "status": {"phase": "Bound"},
    }
    return claim, volume


def bound(claim, volume):
    return storage_is_bound(
        claim,
        volume,
        namespace="example",
        name="example-spool",
        claim_uid="claim-uid",
        storage_class="example-csi",
        required_bytes=1024**3,
    )


def test_capacity_uses_requests_and_exact_fit() -> None:
    assert snapshot_has_capacity([node()], [pod()], PodResourceRequests(100, 128 * 1024**2))
    assert not snapshot_has_capacity([node()], [pod()], PodResourceRequests(101, 128 * 1024**2))


@pytest.mark.parametrize(
    "field,value", [("cpu", "999.9m"), ("memory", "1073741823.9"), ("pods", "1.9")]
)
def test_available_capacity_never_rounds_up(field, value) -> None:
    candidate = node()
    candidate["status"]["allocatable"][field] = value
    assert not snapshot_has_capacity([candidate], [pod()], PodResourceRequests(100, 128 * 1024**2))


@pytest.mark.parametrize("change", ["unassigned", "unknown", "resize", "bad_quantity"])
def test_incomplete_pod_evidence_withholds_capacity(change) -> None:
    current = pod()
    if change == "unassigned":
        current["spec"].pop("nodeName")
    elif change == "unknown":
        current["status"]["phase"] = "Unknown"
    elif change == "resize":
        current["status"]["resize"] = "InProgress"
    else:
        current["spec"]["containers"][0]["resources"]["requests"]["memory"] = "invalid"
    with pytest.raises(ValueError):
        snapshot_has_capacity([node()], [current], PodResourceRequests(100, 128))


@pytest.mark.parametrize("change", ["unschedulable", "taint", "unready", "windows", "deleting"])
def test_ineligible_node_never_offers_capacity(change) -> None:
    candidate = node()
    if change == "unschedulable":
        candidate["spec"]["unschedulable"] = True
    elif change == "taint":
        candidate["spec"]["taints"] = [{"key": "example", "effect": "NoSchedule"}]
    elif change == "unready":
        candidate["status"]["conditions"][0]["status"] = "False"
    elif change == "windows":
        candidate["metadata"]["labels"]["kubernetes.io/os"] = "windows"
    else:
        candidate["metadata"]["deletionTimestamp"] = "2026-09-20T00:00:00Z"
    assert not snapshot_has_capacity([candidate], [], PodResourceRequests(100, 128))


def test_storage_requires_reciprocal_existing_binding() -> None:
    claim, volume = volumes()
    original = deepcopy((claim, volume))
    assert bound(claim, volume)
    assert (claim, volume) == original
    claim["spec"]["resources"]["requests"]["storage"] = "1G"
    claim["status"]["capacity"]["storage"] = "1G"
    volume["spec"]["capacity"]["storage"] = "1G"
    assert not bound(claim, volume)


@pytest.mark.parametrize(
    "change", ["uid", "reference", "class", "unbound", "block", "resize", "deleting"]
)
def test_uncertain_storage_never_passes(change) -> None:
    claim, volume = volumes()
    if change == "uid":
        claim["metadata"]["uid"] = "other-uid"
    elif change == "reference":
        volume["spec"]["claimRef"]["uid"] = "other-uid"
    elif change == "class":
        volume["spec"]["storageClassName"] = "other-class"
    elif change == "unbound":
        claim["status"]["phase"] = "Pending"
    elif change == "block":
        volume["spec"]["volumeMode"] = "Block"
    elif change == "resize":
        claim["status"]["conditions"] = [{"type": "Resizing", "status": "True"}]
    else:
        volume["metadata"]["deletionTimestamp"] = "2026-09-20T00:00:00Z"
    with pytest.raises(ValueError):
        bound(claim, volume)


def resource_probe(monkeypatch, handler, *, now=None):
    import ssl
    from types import SimpleNamespace

    import httpx
    from fdai.delivery.kubernetes_connector_resource_preflight import (
        KubernetesObserverResourcePreflight,
    )

    from .test_kubernetes_connector_planning import DIGEST, NOW

    class Auth:
        async def headers(self):
            return {}

    claim, _ = volumes()
    workload = pod()
    workload["spec"]["containers"][0]["resources"]["requests"] = {"cpu": "100m", "memory": "128Mi"}
    preview = {
        "inputs_digest": DIGEST,
        "manifest_digest": DIGEST,
        "documents": [
            claim,
            {
                "kind": "CronJob",
                "spec": {"jobTemplate": {"spec": {"template": workload}}},
            },
        ],
    }
    monkeypatch.setattr(
        "fdai.delivery.kubernetes_connector_resource_preflight.render_observer_installation",
        lambda *args, **kwargs: preview,
    )
    probe = KubernetesObserverResourcePreflight(
        origin="https://cluster.example",
        target_ref="cluster-example",
        namespace_uid="system-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=now or (lambda: NOW),
        transport=httpx.MockTransport(handler),
    )
    return (
        probe,
        SimpleNamespace(target_ref="cluster-example"),
        SimpleNamespace(expires_at=NOW.replace(minute=5)),
    )


def resource_response(request):
    import httpx

    claim, volume = volumes()
    path = request.url.path
    if path == "/api/v1/namespaces/kube-system":
        return httpx.Response(
            200,
            json={
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "kube-system", "uid": "system-uid"},
            },
        )
    if path in ("/api/v1/nodes", "/api/v1/pods"):
        item = node() if path.endswith("nodes") else pod()
        return httpx.Response(
            200,
            json={
                "apiVersion": "v1",
                "kind": item["kind"] + "List",
                "metadata": {"resourceVersion": "10"},
                "items": [item],
            },
        )
    return httpx.Response(200, json=claim if "persistentvolumeclaims" in path else volume)


@pytest.mark.parametrize("name", ["capacity", "persistent_storage"])
async def test_resource_collection_is_get_only_and_bound(tmp_path, monkeypatch, name) -> None:
    calls = []

    def handler(request):
        assert request.method == "GET"
        assert request.headers["Accept-Encoding"] == "identity"
        calls.append(request.url.path)
        return resource_response(request)

    probe, inputs, proposal = resource_probe(monkeypatch, handler)
    fact = await probe.collect_resources(
        inputs, proposal, material_directory=tmp_path, name=name, claim_uid="claim-uid"
    )
    assert fact.name == name and fact.state == "allowed" and fact.source == "kubernetes_api"
    assert calls[0] == calls[-1] == "/api/v1/namespaces/kube-system"
    assert len(calls) == (4 if name == "capacity" else 6)


@pytest.mark.parametrize(
    "case",
    ["redirect", "oversize", "truncated", "duplicate", "wrong_cluster", "drift", "missing_uid"],
)
async def test_resource_collection_incomplete_is_unknown(tmp_path, monkeypatch, case) -> None:
    import httpx

    calls = []

    def handler(request):
        calls.append(request.url.path)
        response = resource_response(request)
        value = response.json()
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://other.example"})
        if case == "oversize" and request.url.path.endswith("nodes"):
            return httpx.Response(200, content=b"x" * 1048577)
        if case == "wrong_cluster" and len(calls) == 4:
            value["metadata"]["uid"] = "different-system"
        if case == "drift" and len(calls) == 4:
            value["metadata"]["resourceVersion"] = "changed"
        if request.url.path.endswith("nodes"):
            if case == "truncated":
                value["metadata"]["remainingItemCount"] = 1
            elif case == "duplicate":
                value["items"] *= 2
        return httpx.Response(200, json=value)

    probe, inputs, proposal = resource_probe(monkeypatch, handler)
    name = "persistent_storage" if case in ("drift", "missing_uid") else "capacity"
    fact = await probe.collect_resources(
        inputs,
        proposal,
        material_directory=tmp_path,
        name=name,
        claim_uid=None if case == "missing_uid" else "claim-uid",
    )
    assert fact.state == "unknown"
    assert len(calls) <= 6


@pytest.mark.parametrize("case", ["complete", "version", "loop", "budget", "bad_cursor"])
async def test_resource_pagination_keeps_one_snapshot(tmp_path, monkeypatch, case) -> None:
    import httpx

    calls = []

    def handler(request):
        response = resource_response(request)
        if request.url.path != "/api/v1/nodes":
            return response
        calls.append(request)
        value = response.json()
        page = len(calls)
        value["items"][0]["metadata"].update(
            name="node-example" if page == 1 else f"node-{page}", uid=f"node-uid-{page}"
        )
        if page == 1 or case in ("loop", "budget", "bad_cursor"):
            value["metadata"]["continue"] = f"cursor+/{page}=" if case == "budget" else "cursor+/="
        if case == "version" and page == 2:
            value["metadata"]["resourceVersion"] = "changed"
        if case == "bad_cursor":
            value["metadata"]["continue"] = True
        return httpx.Response(200, json=value)

    probe, inputs, proposal = resource_probe(monkeypatch, handler)
    fact = await probe.collect_resources(
        inputs, proposal, material_directory=tmp_path, name="capacity"
    )
    assert fact.state == ("allowed" if case == "complete" else "unknown")
    assert len(calls) <= 8
    if len(calls) > 1:
        assert calls[1].url.params["continue"] == (
            "cursor+/1=" if case == "budget" else "cursor+/="
        )


@pytest.mark.parametrize("case", ["wrong_uid", "path", "resize", "malformed_readback"])
async def test_storage_changes_withhold_fact(tmp_path, monkeypatch, case) -> None:
    import httpx

    calls = []

    def handler(request):
        calls.append(request.url.path)
        value = resource_response(request).json()
        if value["kind"] == "PersistentVolumeClaim":
            if case == "wrong_uid":
                value["metadata"]["uid"] = "different-claim"
            if case == "path":
                value["spec"]["volumeName"] = "../../secrets"
            if case == "resize":
                value["spec"]["resources"]["requests"]["storage"] = "2Gi"
            if case == "malformed_readback" and len(calls) == 4:
                value["status"]["conditions"] = ["invalid"]
        return httpx.Response(200, json=value)

    probe, inputs, proposal = resource_probe(monkeypatch, handler)
    fact = await probe.collect_resources(
        inputs,
        proposal,
        material_directory=tmp_path,
        name="persistent_storage",
        claim_uid="claim-uid",
    )
    assert fact.state == "unknown"
    if case in ("wrong_uid", "path"):
        assert len(calls) == 2


async def test_cancellation_is_not_a_fact_or_retry(tmp_path, monkeypatch) -> None:
    import asyncio

    calls = []

    async def handler(request):
        calls.append(request)
        raise asyncio.CancelledError

    probe, inputs, proposal = resource_probe(monkeypatch, handler)
    with pytest.raises(asyncio.CancelledError):
        await probe.collect_resources(
            inputs, proposal, material_directory=tmp_path, name="capacity"
        )
    assert len(calls) == 1


async def test_expired_collection_cannot_refresh_its_original_timestamp(
    tmp_path, monkeypatch
) -> None:
    from datetime import timedelta

    from .test_kubernetes_connector_planning import NOW

    clock = [NOW]

    def handler(request):
        clock[0] = NOW + timedelta(minutes=5)
        return resource_response(request)

    probe, inputs, proposal = resource_probe(monkeypatch, handler, now=lambda: clock[0])
    with pytest.raises(ValueError, match="expired"):
        await probe.collect_resources(
            inputs, proposal, material_directory=tmp_path, name="capacity"
        )


def test_evidence_summary_excludes_environment_and_provider_messages() -> None:
    from fdai.delivery.kubernetes_connector_resource_preflight import _evidence

    current = pod()
    expected = _evidence(current)
    current["spec"]["containers"][0]["env"] = [{"name": "EXAMPLE", "value": "synthetic-private"}]
    current["status"]["message"] = "synthetic-provider-detail"
    assert _evidence(current) == expected


@pytest.mark.parametrize("name", ["capacity", "persistent_storage"])
async def test_resource_collector_crosses_real_tls_and_actual_renderer(tmp_path, name) -> None:
    import httpx
    from aiohttp import web
    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
    from fdai.delivery.kubernetes_connector_resource_preflight import (
        KubernetesObserverResourcePreflight,
    )

    from .test_kubernetes_connector_gateway import certificates
    from .test_kubernetes_connector_installation import install_inputs, installation_material
    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    (server_tls, _), (client_tls, _) = certificates(tmp_path)
    proposal = propose_observer_deployment(
        context(target_ref=target, facts=(), observed_at=NOW, expires_at=NOW.replace(minute=5)),
        now=NOW,
    )
    inputs = install_inputs(target_ref=target, material_digest=digest)
    preview = render_observer_installation(inputs, proposal, now=NOW, material_directory=directory)
    claim_template = next(
        item for item in preview["documents"] if item["kind"] == "PersistentVolumeClaim"
    )
    calls = []

    class Auth:
        async def headers(self):
            return {}

    async def endpoint(request):
        assert request.method == "GET"
        calls.append(request.path)
        value = resource_response(
            httpx.Request("GET", f"https://cluster.example{request.path}")
        ).json()
        if value["kind"] == "PersistentVolumeClaim":
            value["metadata"].update(claim_template["metadata"])
            value["spec"]["storageClassName"] = inputs.storage_class
        if value["kind"] == "PersistentVolume":
            value["spec"]["claimRef"].update(
                name=claim_template["metadata"]["name"], namespace=inputs.namespace
            )
            value["spec"]["storageClassName"] = inputs.storage_class
        return web.json_response(value)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", endpoint)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
        await site.start()
        probe = KubernetesObserverResourcePreflight(
            origin=f"https://127.0.0.1:{runner.addresses[0][1]}",
            target_ref=target,
            namespace_uid="system-uid",
            auth=Auth(),
            tls=client_tls,
            now=lambda: NOW,
        )
        fact = await probe.collect_resources(
            inputs, proposal, material_directory=directory, name=name, claim_uid="claim-uid"
        )
        assert fact.state == "allowed"
        assert len(calls) == (4 if name == "capacity" else 6)
    finally:
        await runner.cleanup()


async def test_resource_collection_has_a_total_deadline(tmp_path, monkeypatch) -> None:
    import asyncio

    calls = []
    original_timeout = asyncio.timeout

    async def blocked(request):
        calls.append(request)
        await asyncio.Event().wait()

    probe, inputs, proposal = resource_probe(monkeypatch, blocked)
    monkeypatch.setattr(
        "fdai.delivery.kubernetes_connector_resource_preflight.asyncio.timeout",
        lambda duration: original_timeout(0.01),
    )
    fact = await probe.collect_resources(
        inputs, proposal, material_directory=tmp_path, name="capacity"
    )
    assert fact.state == "unknown" and len(calls) == 1


@pytest.mark.parametrize("kind", ["capacity", "storage"])
def test_resource_commands_dispatch_only_the_selected_collector(
    tmp_path, monkeypatch, capsys, kind
) -> None:
    import json

    from fdai.delivery import kubernetes_connector_proposal_cli as cli

    from .test_kubernetes_connector_preflight import material

    _, receipt, _ = material()
    calls = []

    async def collect(path, *, now):
        calls.append(path)
        return receipt

    monkeypatch.setattr(cli, f"collect_{kind}_preflight", collect)
    config = tmp_path / "private.json"
    assert cli.main([f"collect-{kind}-preflight", "--config", str(config)]) == 0
    assert calls == [config]
    assert json.loads(capsys.readouterr().out) == receipt.model_dump(mode="json")

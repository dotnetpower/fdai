"""Real signatures bind preflight observations without granting installation authority."""

import hashlib
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.delivery.kubernetes_connector_preflight import (
    ObserverPreflightGrant,
    SignedObserverConstraints,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.observer_deployment import ObserverPreflightReceipt

from .test_kubernetes_connector_planning import DIGEST, NOW, context


class Grants:
    def __init__(self, grant):
        self.grant = grant

    async def read(self, target_ref, issuer_ref, key_ref):
        return self.grant


def material():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    inputs = context()
    grant = ObserverPreflightGrant(
        issuer_ref="preflight-example",
        key_ref="sha256:" + hashlib.sha256(public).hexdigest(),
        public_key=public.hex(),
        target_ref=inputs.target_ref,
        allowed_facts={fact.name: (fact.source,) for fact in inputs.facts},
        producer_revision=DIGEST,
        valid_from=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    receipt = ObserverPreflightReceipt(
        issuer_ref=grant.issuer_ref,
        key_ref=grant.key_ref,
        producer_revision=DIGEST,
        context=inputs,
        issued_at=NOW,
        signature="0" * 128,
    )
    receipt = receipt.model_copy(update={"signature": private.sign(receipt.signing_bytes()).hex()})
    return grant, receipt, private


async def test_signed_preflight_is_retained_once_and_revocation_is_current() -> None:
    grant, receipt, _ = material()
    grants, store = Grants(grant), InMemoryStateStore()
    source = SignedObserverConstraints(store, grants=grants, now=lambda: NOW)
    assert await source.retain(receipt)
    assert not await source.retain(receipt)
    assert (await source.read(receipt.context.target_ref, now=NOW)).facts == tuple(
        sorted(receipt.context.facts, key=lambda fact: fact.name)
    )
    assert len(list(store.audit_entries)) == 1
    grants.grant = grant.model_copy(update={"revoked": True})
    with pytest.raises(ValueError, match="enrollment"):
        await source.read(receipt.context.target_ref, now=NOW)
    assert await store.verify_chain()


async def test_same_verifier_keeps_independent_collector_receipts() -> None:
    grant, original, private = material()
    store = InMemoryStateStore()
    clock = [NOW]
    source = SignedObserverConstraints(store, grants=Grants(grant), now=lambda: clock[0])

    def signed_fact(name, *, state="allowed", issued=NOW):
        fact = next(item for item in original.context.facts if item.name == name).model_copy(
            update={"state": state}
        )
        receipt = original.model_copy(
            update={
                "context": original.context.model_copy(update={"facts": (fact,)}),
                "issued_at": issued,
            }
        )
        return receipt.model_copy(update={"signature": private.sign(receipt.signing_bytes()).hex()})

    for name in ("kubernetes_read", "admission", "mtls_gateway"):
        assert await source.retain(signed_fact(name))
    result = await source.read(original.context.target_ref, now=NOW)
    assert {fact.name for fact in result.facts} == {"kubernetes_read", "admission", "mtls_gateway"}
    clock[0] += timedelta(seconds=1)
    replacement = signed_fact("admission", state="denied", issued=clock[0])
    assert await source.retain(replacement)
    assert not await source.retain(replacement)
    result = await source.read(original.context.target_ref, now=clock[0])
    assert {fact.name: fact.state for fact in result.facts} == {
        "kubernetes_read": "allowed",
        "admission": "denied",
        "mtls_gateway": "allowed",
    }
    assert len(list(store.audit_entries)) == 4


async def test_same_verifier_cannot_replace_part_of_an_existing_signed_group() -> None:
    grant, original, private = material()
    store = InMemoryStateStore()
    source = SignedObserverConstraints(
        store, grants=Grants(grant), now=lambda: NOW + timedelta(seconds=1)
    )
    assert await source.retain(original)
    partial = original.model_copy(
        update={
            "context": original.context.model_copy(update={"facts": original.context.facts[:1]}),
            "issued_at": NOW + timedelta(seconds=1),
        }
    )
    partial = partial.model_copy(update={"signature": private.sign(partial.signing_bytes()).hex()})
    with pytest.raises(ValueError, match="overlap"):
        await source.retain(partial)
    assert (
        len((await source.read(original.context.target_ref, now=NOW + timedelta(seconds=1))).facts)
        == 16
    )
    assert len(list(store.audit_entries)) == 1


@pytest.mark.parametrize(
    "case", ["valid", "source", "signature", "digest", "oversize", "exit", "running"]
)
async def test_artifact_fact_uses_only_isolated_deployment_verifier(
    tmp_path, monkeypatch, case
) -> None:
    import asyncio
    import json
    import signal
    from pathlib import Path

    from fdai.delivery.kubernetes_connector_artifact_preflight import collect_artifact_fact
    from fdai_service_contracts.compatibility import canonical_digest

    source, image = "a" * 40, "sha256:" + "b" * 64
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "source_commit": source,
                "image_digest": image,
                "offline_kit": str(tmp_path / "kit"),
                "work_dir": str(tmp_path / "work"),
            }
        )
    )
    request.chmod(0o600)
    value = {
        "schema_version": "1.0.0",
        "source_commit": source,
        "image_digest": image,
        "platform_tag": "linux-x86_64",
        "runtime_digest": DIGEST,
        "bundle_digest": DIGEST,
        "release_signature_verified": True,
        "execution_authority": False,
    }
    if case == "source":
        value["source_commit"] = "f" * 40
    elif case == "signature":
        value["release_signature_verified"] = False
    value["evidence_digest"] = canonical_digest(value)
    if case == "digest":
        value["evidence_digest"] = "sha256:" + "0" * 64

    class Process:
        pid = 12345

        def __init__(self):
            self.returncode = None if case == "running" else 1 if case == "exit" else 0
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(
                b"x" * 8193 if case in {"oversize", "running"} else json.dumps(value).encode()
            )
            self.stdout.feed_eof()

        async def wait(self):
            return self.returncode

    calls = []
    processes, killed = [], []

    async def start(*args, **kwargs):
        calls.append(args)
        assert args == (
            "/verified/bin/python",
            "-I",
            "-m",
            "fdai_deployment_cli.observer_artifact",
            "--request",
            str(request),
        )
        assert "PYTHONPATH" not in kwargs["env"] and "PYTHONHOME" not in kwargs["env"]
        assert kwargs["start_new_session"] is True
        process = Process()
        processes.append(process)
        return process

    def kill(pid, received):
        assert pid == 12345 and received == signal.SIGKILL
        killed.append(pid)
        processes[-1].returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    from fdai.delivery import kubernetes_connector_artifact_preflight as artifact_module

    monkeypatch.setattr(artifact_module.os, "killpg", kill)
    fact = await collect_artifact_fact(
        deployment_python=Path("/verified/bin/python"),
        request_path=request,
        target_ref="cluster-example",
        source_commit=source,
        image_digest=image,
        now=lambda: NOW,
    )
    assert fact.state == ("allowed" if case == "valid" else "unknown")
    assert len(calls) == 1
    assert killed == ([12345] if case == "running" else [])
    if case == "valid":
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )
        from fdai.delivery.kubernetes_connector_preflight import verify_preflight
        from fdai.delivery.kubernetes_connector_preflight_runtime import (
            FileObserverPreflightGrants,
            collect_artifact_preflight,
        )

        grant, _, private = material()
        grant = grant.model_copy(
            update={"allowed_facts": {"artifact_verified": ("deployment_profile",)}}
        )
        config = {
            "target_ref": "cluster-example",
            "discovery_digest": DIGEST,
            "issuer_ref": grant.issuer_ref,
            "producer_revision": DIGEST,
            "signing_key_path": str(tmp_path / "key.pem"),
            "grants_path": str(tmp_path / "grants.json"),
            "deployment_python_path": "/verified/bin/python",
            "request_path": str(request),
            "source_commit": source,
            "image_digest": image,
        }
        files = {
            "key.pem": private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
            "grants.json": json.dumps([grant.model_dump(mode="json")]).encode(),
            "config.json": json.dumps(config).encode(),
        }
        for name, content in files.items():
            (tmp_path / name).write_bytes(content)
            (tmp_path / name).chmod(0o600)
        signed = await collect_artifact_preflight(tmp_path / "config.json", now=lambda: NOW)
        assert signed.context.facts == (fact,)
        await verify_preflight(
            signed, grants=FileObserverPreflightGrants(tmp_path / "grants.json"), now=NOW
        )


@pytest.mark.parametrize(
    "kind", ["signature", "target", "issuer", "scope", "revision", "expiry", "owner"]
)
async def test_invalid_preflight_never_persists(kind) -> None:
    grant, receipt, private = material()
    if kind == "signature":
        receipt = receipt.model_copy(update={"signature": "0" * 128})
    elif kind == "target":
        grant = grant.model_copy(update={"target_ref": "other-cluster"})
    elif kind == "issuer":
        grant = grant.model_copy(update={"issuer_ref": "other-issuer"})
    elif kind == "scope":
        grant = grant.model_copy(update={"allowed_facts": {"capacity": ("kubernetes_api",)}})
    elif kind == "revision":
        grant = grant.model_copy(update={"producer_revision": "sha256:" + "b" * 64})
    elif kind == "expiry":
        grant = grant.model_copy(update={"expires_at": NOW})
    else:
        receipt = receipt.model_copy(
            update={"context": receipt.context.model_copy(update={"existing_method": "gitops"})}
        )
        receipt = receipt.model_copy(
            update={"signature": private.sign(receipt.signing_bytes()).hex()}
        )
    store = InMemoryStateStore()
    source = SignedObserverConstraints(store, grants=Grants(grant), now=lambda: NOW)
    with pytest.raises(ValueError):
        await source.retain(receipt)
    assert not list(store.audit_entries)


async def test_private_registry_runtime_retains_receipt_and_observes_revocation(
    tmp_path, monkeypatch
) -> None:
    import json

    from fdai.delivery.kubernetes_connector_preflight_runtime import (
        PREFLIGHT_GRANTS_ENV,
        build_observer_constraints,
        retain_preflight_file,
    )

    grant, receipt, _ = material()
    grants_path = tmp_path / "grants.json"
    grants_path.write_text(json.dumps([grant.model_dump(mode="json")]))
    grants_path.chmod(0o600)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json())
    receipt_path.chmod(0o600)
    monkeypatch.setenv(PREFLIGHT_GRANTS_ENV, str(grants_path))
    store = InMemoryStateStore()
    assert await retain_preflight_file(receipt_path, store=store, now=lambda: NOW)
    reader = build_observer_constraints(store, now=lambda: NOW)
    assert (await reader.read(receipt.context.target_ref, now=NOW)).facts == tuple(
        sorted(receipt.context.facts, key=lambda fact: fact.name)
    )
    grants_path.write_text(
        json.dumps([grant.model_copy(update={"revoked": True}).model_dump(mode="json")])
    )
    with pytest.raises(ValueError, match="enrollment"):
        await reader.read(receipt.context.target_ref, now=NOW)


async def test_unsigned_legacy_facts_never_recommend_an_eligible_install() -> None:
    from fdai.delivery.kubernetes_connector_proposals import (
        OBSERVER_CONSTRAINT_PREFIX,
        StateStoreObserverConstraints,
    )
    from fdai_service_contracts.compatibility import canonical_digest

    store = InMemoryStateStore()
    inputs = context(existing_method="existing_host")
    await store.write_state(
        OBSERVER_CONSTRAINT_PREFIX + canonical_digest({"target_ref": inputs.target_ref}),
        {
            "context": inputs.model_dump(mode="json"),
            "context_digest": canonical_digest(inputs.model_dump(mode="json")),
        },
    )
    result = await StateStoreObserverConstraints(store).read(inputs.target_ref, now=NOW)
    assert result.facts == ()
    assert result.existing_method == "existing_host"


async def test_independent_verifiers_preserve_each_other_and_conflict_is_held() -> None:
    grant, receipt, private = material()
    second_grant, second, second_private = material()
    second_grant = second_grant.model_copy(update={"issuer_ref": "second-verifier"})

    def signed(base, key, **updates):
        base = base.model_copy(update=updates)
        return base.model_copy(update={"signature": key.sign(base.signing_bytes()).hex()})

    first = signed(
        receipt,
        private,
        context=receipt.context.model_copy(update={"facts": receipt.context.facts[:1]}),
    )
    second = signed(
        second,
        second_private,
        issuer_ref=second_grant.issuer_ref,
        context=second.context.model_copy(update={"facts": second.context.facts[1:]}),
    )

    class Registry:
        async def read(self, target_ref, issuer_ref, key_ref):
            return grant if issuer_ref == grant.issuer_ref else second_grant

    source = SignedObserverConstraints(
        InMemoryStateStore(), grants=Registry(), now=lambda: NOW + timedelta(seconds=1)
    )
    assert await source.retain(first)
    assert await source.retain(second)
    assert (
        len((await source.read(receipt.context.target_ref, now=NOW + timedelta(seconds=1))).facts)
        == 16
    )
    conflicting = signed(
        second,
        second_private,
        issued_at=NOW + timedelta(seconds=1),
        context=second.context.model_copy(
            update={"facts": (first.context.facts[0].model_copy(update={"state": "denied"}),)}
        ),
    )
    assert await source.retain(conflicting)
    with pytest.raises(ValueError, match="conflict"):
        await source.read(receipt.context.target_ref, now=NOW + timedelta(seconds=1))


async def test_grant_read_cannot_hide_expiry() -> None:
    grant, receipt, _ = material()
    clock = [NOW]

    class SlowGrants:
        async def read(self, target_ref, issuer_ref, key_ref):
            clock[0] += timedelta(hours=1)
            return grant

    store = InMemoryStateStore()
    source = SignedObserverConstraints(store, grants=SlowGrants(), now=lambda: clock[0])
    with pytest.raises(ValueError, match="lifetime"):
        await source.retain(receipt)
    assert not list(store.audit_entries)


async def test_real_tls_authorization_collection(tmp_path) -> None:
    from aiohttp import web
    from fdai.delivery.kubernetes_connector_read_preflight import (
        KubernetesObserverReadPreflight,
        snapshot_read_attributes,
    )

    from .test_kubernetes_connector_gateway import certificates

    (server_tls, _), (client_tls, _) = certificates(tmp_path)
    calls = []

    class Auth:
        async def headers(self):
            return {"Authorization": "Bearer ephemeral-test"}

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer ephemeral-test"
        calls.append(request.method)
        if request.method == "GET":
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "kube-system", "uid": "cluster-uid"},
                }
            )
        value = await request.json()
        value["status"] = {"allowed": True}
        return web.json_response(value, status=201)

    app = web.Application()
    app.router.add_get("/api/v1/namespaces/kube-system", handler)
    app.router.add_post("/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
        await site.start()
        probe = KubernetesObserverReadPreflight(
            origin=f"https://127.0.0.1:{runner.addresses[0][1]}",
            target_ref="cluster-example",
            namespace_uid="cluster-uid",
            auth=Auth(),
            tls=client_tls,
            now=lambda: NOW,
        )
        fact = await probe.collect()
        assert fact.state == "allowed"
        assert len(calls) == len(snapshot_read_attributes()) + 2
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("allowed", "allowed"),
        ("denied", "denied"),
        ("error", "unknown"),
        ("foreign", "unknown"),
        ("drift", "unknown"),
        ("redirect", "unknown"),
        ("forged", "unknown"),
        ("oversized", "unknown"),
    ],
)
async def test_read_preflight_uses_real_request_shape_and_exact_cluster(case, expected) -> None:
    import json
    import ssl

    import httpx
    from fdai.delivery.kubernetes_connector_read_preflight import (
        KubernetesObserverReadPreflight,
        snapshot_read_attributes,
    )

    class Auth:
        async def headers(self):
            return {"Authorization": "Bearer test-token"}

    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "GET":
            uid = (
                "other"
                if case == "foreign" or case == "drift" and len(requests) > 1
                else "cluster-uid"
            )
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "kube-system", "uid": uid},
                },
            )
        value = json.loads(request.content)
        assert value["spec"]["resourceAttributes"] in snapshot_read_attributes()
        if case == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.example"})
        if case == "oversized":
            return httpx.Response(200, content=b" " * 16385)
        value["status"] = {"allowed": case != "denied"}
        if case == "error":
            value["status"]["evaluationError"] = "not retained"
        if case == "forged":
            value["spec"]["resourceAttributes"]["resource"] = "secrets"
        return httpx.Response(201, json=value)

    probe = KubernetesObserverReadPreflight(
        origin="https://cluster.example",
        target_ref="cluster-example",
        namespace_uid="cluster-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    fact = await probe.collect()
    assert fact.state == expected
    assert fact.source == "kubernetes_api"
    if expected in {"allowed", "denied"}:
        assert len(requests) == len(snapshot_read_attributes()) + 2
    assert "test-token" not in fact.model_dump_json()
    assert "not retained" not in fact.model_dump_json()


async def test_read_collector_composition_signs_only_its_observed_fact(
    tmp_path, monkeypatch
) -> None:
    import json

    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from fdai.delivery import kubernetes_connector_preflight_runtime as runtime
    from fdai.delivery import kubernetes_connector_read_preflight as collector
    from fdai_service_contracts.schema import (
        JsonSchemaContractValidator,
        PackageResourceSchemaRegistry,
    )

    grant, original, private = material()
    key_path = tmp_path / "signing.pem"
    key_path.write_bytes(private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    key_path.chmod(0o600)
    grant = grant.model_copy(update={"allowed_facts": {"kubernetes_read": ("kubernetes_api",)}})
    grants_path = tmp_path / "grants.json"
    grants_path.write_text(json.dumps([grant.model_dump(mode="json")]))
    grants_path.chmod(0o600)
    fact = original.context.facts[0].model_copy(
        update={"name": "kubernetes_read", "source": "kubernetes_api"}
    )

    class Probe:
        def __init__(self, **kwargs):
            assert kwargs["namespace_uid"] == "cluster-uid"

        async def collect(self):
            return fact

    monkeypatch.setattr(collector, "KubernetesObserverReadPreflight", Probe)
    monkeypatch.setattr(runtime.ssl, "create_default_context", lambda **kwargs: object())
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "target_ref": grant.target_ref,
                "discovery_digest": DIGEST,
                "issuer_ref": grant.issuer_ref,
                "producer_revision": DIGEST,
                "api_origin": "https://cluster.example",
                "namespace_uid": "cluster-uid",
                "api_ca_path": str(tmp_path / "ca.pem"),
                "api_token_path": str(tmp_path / "token"),
                "signing_key_path": str(key_path),
                "grants_path": str(grants_path),
            }
        )
    )
    path.chmod(0o600)
    receipt = await runtime.collect_read_preflight(path, now=lambda: NOW)
    assert receipt.context.facts == (fact,)
    assert receipt.execution_authority is False
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "observer-preflight-receipt", receipt.model_dump(mode="json")
    )

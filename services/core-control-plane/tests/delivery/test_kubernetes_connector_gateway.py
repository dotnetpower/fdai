"""Real loopback TLS proves that client certificates, not headers, identify a connector."""

import hashlib
import ipaddress
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fdai.delivery.kubernetes_connector_gateway import create_connector_gateway
from fdai.delivery.kubernetes_connector_snapshot import (
    ConnectorInventorySource,
    ConnectorSnapshotInbox,
)
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.kubernetes_connector_transport import (
    ConnectorEvidenceTransport,
    ConnectorTransportConfig,
)
from fdai.shared.providers.testing import InMemoryStateStore

from .test_kubernetes_connector_spool import NOW, REVISION, registration, snapshot


def certificates(tmp_path):
    clock = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "connector-test-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(clock - timedelta(minutes=1))
        .not_valid_after(clock + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    result = []
    for role in ("server", "client"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, role)]))
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(clock - timedelta(minutes=1))
            .not_valid_after(clock + timedelta(hours=1))
            .add_extension(
                x509.ExtendedKeyUsage(
                    [
                        ExtendedKeyUsageOID.SERVER_AUTH
                        if role == "server"
                        else ExtendedKeyUsageOID.CLIENT_AUTH
                    ]
                ),
                critical=False,
            )
        )
        if role == "server":
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
        certificate = (
            builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        cert_path, key_path = tmp_path / f"{role}.pem", tmp_path / f"{role}.key"
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        context = ssl.create_default_context(
            ssl.Purpose.CLIENT_AUTH if role == "server" else ssl.Purpose.SERVER_AUTH,
            cafile=str(ca_path),
        )
        context.load_cert_chain(str(cert_path), str(key_path))
        context.verify_mode = ssl.CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        result.append(
            (
                context,
                "sha256:"
                + hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest(),
            )
        )
    return result


class Registrations:
    def __init__(self, principal):
        self.current = registration().model_copy(update={"principal_ref": principal})

    async def read(self, principal_ref):
        return self.current if self.current.principal_ref == principal_ref else None


async def test_real_mtls_snapshot_roundtrip_and_revocation(tmp_path) -> None:
    (server_context, _), (client_context, principal) = certificates(tmp_path)
    registrations = Registrations(principal)
    store = InMemoryStateStore()
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
    )
    application = create_connector_gateway(
        inbox=inbox, registrations=registrations, now=lambda: NOW
    )
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context)
    await site.start()
    port = runner.addresses[0][1]
    sender = ConnectorEvidenceTransport(
        ConnectorTransportConfig(f"https://127.0.0.1:{port}", "api://example"),
        tls_context=client_context,
    )
    outbox = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registrations.current,
        stream_id="example",
        allow_cluster_resources=False,
    )
    pending = await outbox.enqueue(
        snapshot(), registration=registrations.current, producer_revision=REVISION, now=NOW
    )
    try:
        receipt = await sender.send_snapshot(
            pending.evidence, pending.content, allow_cluster_resources=False
        )
        assert receipt.status == "accepted"
        assert (
            await sender.send_snapshot(
                pending.evidence, pending.content, allow_cluster_resources=False
            )
        ).status == "duplicate"
        assert (
            await ConnectorInventorySource(inbox, principal_ref=principal).collect() == snapshot()
        )
        await outbox.acknowledge(receipt)
        assert await outbox.oldest() is None
        assert len(list(store.audit_entries)) == 1
        async with httpx.AsyncClient(verify=client_context, trust_env=False) as client:
            url = f"https://127.0.0.1:{port}/v1/connector/snapshots"
            duplicate = await client.post(
                url,
                content=b'{"evidence":{},"evidence":{},"artifact":""}',
                headers={"Content-Type": "application/json"},
            )
            assert duplicate.status_code == 422
            compressed = await client.post(
                url,
                content=b"not-gzip",
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            )
            assert compressed.status_code == 415
            current = registrations.current
            registrations.current = current.model_copy(
                update={"principal_ref": "sha256:" + "a" * 64}
            )
            unregistered = await client.post(url, json={})
            assert unregistered.status_code == 403
            registrations.current = current
        registrations.current = registrations.current.model_copy(update={"revoked": True})
        async with httpx.AsyncClient(verify=client_context, trust_env=False) as client:
            response = await client.post(
                f"https://127.0.0.1:{port}/v1/connector/snapshots", json={}
            )
            assert response.status_code == 422
    finally:
        await sender.aclose()
        await runner.cleanup()


@pytest.mark.parametrize("path", ["snapshots", "preflight"])
async def test_cleartext_and_forged_identity_headers_are_denied(tmp_path, path) -> None:
    registrations = Registrations("sha256:" + "a" * 64)
    inbox = ConnectorSnapshotInbox(
        InMemoryStateStore(),
        registrations=registrations,
        allow_cluster_resources=False,
        now=lambda: NOW,
    )
    runner = web.AppRunner(
        create_connector_gateway(inbox=inbox, registrations=registrations, now=lambda: NOW),
        access_log=None,
    )
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(
                f"http://127.0.0.1:{runner.addresses[0][1]}/v1/connector/{path}",
                headers={"X-Client-Cert": "forged", "Authorization": "Bearer forged"},
                json={},
            )
            assert response.status_code == 401
    finally:
        await runner.cleanup()


def test_client_cannot_disable_tls_verification() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError):
        ConnectorEvidenceTransport(
            ConnectorTransportConfig("https://example.com", "api://example"), tls_context=context
        )


async def test_gateway_probe_real_mtls_scope_revocation_and_no_persistence(tmp_path) -> None:
    from fdai.delivery.kubernetes_connector_gateway_probe import GatewayObserverPreflight

    (server_tls, _), (client_tls, principal) = certificates(tmp_path)
    registrations, store = Registrations(principal), InMemoryStateStore()
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
    )
    runner = web.AppRunner(
        create_connector_gateway(inbox=inbox, registrations=registrations, now=lambda: NOW),
        access_log=None,
    )
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls).start()
        origin = f"https://127.0.0.1:{runner.addresses[0][1]}"
        probe = GatewayObserverPreflight(
            origin=origin, scope=registrations.current.scope, tls=client_tls, now=lambda: NOW
        )
        first = await probe.collect()
        assert first.name == "mtls_gateway" and first.state == "allowed"
        assert (await probe.collect()).evidence_digest != first.evidence_digest
        foreign = GatewayObserverPreflight(
            origin=origin,
            scope=registrations.current.scope.model_copy(update={"cluster_ref": "foreign-cluster"}),
            tls=client_tls,
            now=lambda: NOW,
        )
        assert (await foreign.collect()).state == "unknown"
        async with httpx.AsyncClient(verify=client_tls, trust_env=False) as client:
            oversized = await client.post(
                origin + "/v1/connector/preflight",
                content=b" " * 1025,
                headers={"Content-Type": "application/json"},
            )
            assert oversized.status_code == 413
            duplicated = await client.post(
                origin + "/v1/connector/preflight",
                content=b'{"nonce":"a","nonce":"b"}',
                headers={"Content-Type": "application/json"},
            )
            assert duplicated.status_code == 422
        registrations.current = registrations.current.model_copy(update={"revoked": True})
        assert (await probe.collect()).state == "unknown"
        assert list(store.audit_entries) == []
        assert not await store.read_states("kubernetes-connector:", limit=10)
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "case", ["nonce", "scope", "clock", "authority", "oversize", "redirect", "duplicate"]
)
async def test_gateway_probe_rejects_bad_receipts_without_retry(case) -> None:
    import json

    from fdai.delivery.kubernetes_connector_gateway_probe import GatewayObserverPreflight

    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        value = {**body, "observed_at": NOW.isoformat(), "execution_authority": False}
        if case == "nonce":
            value["nonce"] = "0" * 64
        elif case == "scope":
            value["scope_digest"] = "sha256:" + "f" * 64
        elif case == "clock":
            value["observed_at"] = (NOW - timedelta(minutes=1)).isoformat()
        elif case == "authority":
            value["execution_authority"] = True
        elif case == "oversize":
            return httpx.Response(200, content=b"a" * 4097)
        elif case == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.example"})
        elif case == "duplicate":
            return httpx.Response(200, content=b'{"nonce":"a","nonce":"b"}')
        return httpx.Response(200, json=value)

    probe = GatewayObserverPreflight(
        origin="https://gateway.example",
        scope=registration().scope,
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    assert (await probe.collect()).state == "unknown"
    assert len(calls) == 1


async def test_gateway_preflight_runtime_signs_real_challenge(tmp_path) -> None:
    import json

    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from fdai.delivery.kubernetes_connector_preflight import verify_preflight
    from fdai.delivery.kubernetes_connector_preflight_runtime import (
        FileObserverPreflightGrants,
        collect_gateway_preflight,
    )

    from .test_kubernetes_connector_preflight import material

    (server_tls, _), (_, principal) = certificates(tmp_path)
    registrations, store = Registrations(principal), InMemoryStateStore()
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
    )
    runner = web.AppRunner(
        create_connector_gateway(inbox=inbox, registrations=registrations, now=lambda: NOW),
        access_log=None,
    )
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls).start()
        grant, _, private = material()
        grant = grant.model_copy(
            update={
                "valid_from": NOW - timedelta(minutes=1),
                "expires_at": NOW + timedelta(hours=1),
                "allowed_facts": {"mtls_gateway": ("network_probe",)},
            }
        )
        observer = {
            "role": "observer",
            "registration_path": str(tmp_path / "registrations.json"),
            "tls_ca_path": str(tmp_path / "ca.pem"),
            "tls_certificate_path": str(tmp_path / "client.pem"),
            "tls_key_path": str(tmp_path / "client.key"),
            "gateway_origin": f"https://127.0.0.1:{runner.addresses[0][1]}",
            "observer_principal_ref": principal,
            "stream_id": "example",
            "producer_revision": REVISION,
            "spool_directory": str(tmp_path / "spool"),
            "api_server": "https://kubernetes.default.svc",
            "api_ca_path": str(tmp_path / "unused-ca"),
            "api_token_path": str(tmp_path / "unused-token"),
        }
        config = {
            "target_ref": registrations.current.scope.cluster_ref,
            "discovery_digest": REVISION,
            "issuer_ref": grant.issuer_ref,
            "producer_revision": grant.producer_revision,
            "signing_key_path": str(tmp_path / "signing.pem"),
            "grants_path": str(tmp_path / "grants.json"),
            "observer_config_path": str(tmp_path / "observer.json"),
        }
        files = {
            "registrations.json": json.dumps(
                [registrations.current.model_dump(mode="json")]
            ).encode(),
            "observer.json": json.dumps(observer).encode(),
            "grants.json": json.dumps([grant.model_dump(mode="json")]).encode(),
            "probe.json": json.dumps(config).encode(),
            "signing.pem": private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        }
        for name, contents in files.items():
            (tmp_path / name).write_bytes(contents)
            (tmp_path / name).chmod(0o600)
        receipt = await collect_gateway_preflight(tmp_path / "probe.json", now=lambda: NOW)
        assert [(fact.name, fact.state) for fact in receipt.context.facts] == [
            ("mtls_gateway", "allowed")
        ]
        await verify_preflight(
            receipt, grants=FileObserverPreflightGrants(tmp_path / "grants.json"), now=NOW
        )
        assert not list(store.audit_entries)
        registrations.current = registrations.current.model_copy(update={"revoked": True})
        denied = await collect_gateway_preflight(tmp_path / "probe.json", now=lambda: NOW)
        assert denied.context.facts[0].state == "unknown"
    finally:
        await runner.cleanup()

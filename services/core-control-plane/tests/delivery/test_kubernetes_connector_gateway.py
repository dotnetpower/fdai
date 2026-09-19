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


async def test_cleartext_and_forged_identity_headers_are_denied(tmp_path) -> None:
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
                f"http://127.0.0.1:{runner.addresses[0][1]}/v1/connector/snapshots",
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

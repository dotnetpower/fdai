from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import NativeScopeClaim, sign_native_scope

from fdai_lifecycle_agent import cli
from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError


@pytest.fixture
def proof():
    return sign_native_scope(
        NativeScopeClaim(
            schema_version="fdai.lifecycle-native-scope.v1",
            installation_id="installation-alpha",
            entity_id="application",
            product="example-app",
            scope_digest="sha256:" + "a" * 64,
            approval_digest="sha256:" + "b" * 64,
            creation_receipt_digest="sha256:" + "c" * 64,
        ),
        Ed25519PrivateKey.generate(),
    )


def test_proof_transport_uses_only_exact_post_and_keeps_conflicting_response(proof):
    seen = []

    def receive(request):
        seen.append(request)
        return httpx.Response(202, json={"received": True, "changed": True})

    with HttpHubClient(
        "https://hub.example.com",
        transport=httpx.MockTransport(receive),
        authorization=lambda: "synthetic-token",
    ) as client:
        client.submit_native_proof("installation-alpha", proof)
        with pytest.raises(ValueError, match="installation binding"):
            client.submit_native_proof("other-installation", proof)
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/v1/installations/installation-alpha/native-proofs"
    assert json.loads(seen[0].content) == proof.model_dump(mode="json")
    assert seen[0].headers["authorization"] == "Bearer synthetic-token"
    with HttpHubClient(
        "https://hub.example.com",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(409, json={"error": "native_proof_claim_conflict"})
        ),
    ) as client:
        with pytest.raises(HubProtocolError, match="native_proof_claim_conflict"):
            client.submit_native_proof("installation-alpha", proof)


@pytest.mark.parametrize("change", ["valid", "duplicate", "oversized", "installation", "network"])
def test_cli_preserves_private_file_and_never_prints_proof(
    proof, tmp_path, monkeypatch, capsys, change
):
    from fdai_lifecycle_agent import remote_auth

    path = tmp_path / "proof.json"
    body = proof.model_dump_json()
    if change == "duplicate":
        body = body[:-1] + ',"signature":"duplicate"}'
    if change == "oversized":
        body = " " * 8193
    path.write_text(body)
    sent = []
    closed = []

    class Authorization:
        def __init__(self, scope):
            assert scope == "api://hub/.default"

        def close(self):
            closed.append("authorization")

    class Client:
        def __init__(self, url, *, authorization, timeout_seconds):
            assert url == "https://hub.example.com"
            assert timeout_seconds == 10.0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append("client")

        def submit_native_proof(self, installation_id, value):
            sent.append((installation_id, value))
            if change == "network":
                raise HubProtocolError("private-provider-detail")

    monkeypatch.setattr(remote_auth, "WorkloadIdentityAuthorization", Authorization)
    monkeypatch.setattr(cli, "HttpHubClient", Client)
    identifier = "another-installation" if change == "installation" else "installation-alpha"
    result = cli.main(
        [
            "submit-native-proof",
            "--installation-id",
            identifier,
            "--proof",
            str(path),
            "--hub-url",
            "https://hub.example.com",
            "--hub-scope",
            "api://hub/.default",
        ]
    )
    assert result == (0 if change == "valid" else 2)
    assert path.read_text() == body
    output = capsys.readouterr()
    assert proof.signature not in output.out + output.err
    assert "private-provider-detail" not in output.out + output.err
    assert bool(sent) == (change in {"valid", "network"})
    assert closed == (["client", "authorization"] if sent else [])

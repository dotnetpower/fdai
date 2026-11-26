"""Outbound transport preserves credentials, exact acknowledgments and failure bounds."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.kubernetes_connector_transport import (
    ConnectorEvidenceTransport,
    ConnectorTransportConfig,
    ConnectorTransportError,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.cluster_connector import ConnectorEvidence

NOW = datetime(2026, 9, 19, tzinfo=UTC)


class Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken("synthetic-credential", NOW + timedelta(minutes=1), audience)


def packet() -> ConnectorEvidence:
    return ConnectorEvidence.model_validate(
        {
            "scope": {
                "deployment_ref": "example",
                "cluster_ref": "example",
                "connector_id": "example",
                "enrollment_revision": 1,
            },
            "capability": "inventory.snapshot",
            "stream_id": "example",
            "sequence": 1,
            "observed_at": NOW,
            "producer_revision": "sha256:" + "a" * 64,
            "artifact_digest": "sha256:" + "b" * 64,
            "artifact_bytes": 100,
            "namespaces": ["example"],
            "complete": True,
        }
    )


def acknowledgment(**changes: object) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "status": "accepted",
        "evidence_digest": packet().digest,
        "sequence": 1,
        **changes,
    }


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com?token=example",
        "https://example.com#fragment",
        "https://example.com\n",
        "https://example.com:99999",
        "https://example.com\\path",
    ],
)
def test_rejects_unsafe_origins(origin: str) -> None:
    with pytest.raises(ValueError):
        ConnectorTransportConfig(origin, "api://example")


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": True},
        {"sequence": 2},
        {"status": "succeeded"},
        {"status": []},
        {"status": {}},
        {"extra": True},
        {"evidence_digest": "sha256:" + "c" * 64},
    ],
)
async def test_rejects_mismatched_acknowledgments(changes: dict[str, object]) -> None:
    sender = ConnectorEvidenceTransport(
        ConnectorTransportConfig("https://example.com", "api://example"),
        identity=Identity(),
        now=lambda: NOW,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=acknowledgment(**changes))
        ),
    )
    try:
        with pytest.raises(ConnectorTransportError):
            await sender.send(packet())
    finally:
        await sender.aclose()


async def test_posts_exact_metadata_without_credentials_in_body() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/connector/evidence"
        assert request.method == "POST"
        assert request.headers["authorization"].startswith("Bearer ")
        assert b"synthetic-credential" not in request.content
        return httpx.Response(201, json=acknowledgment())

    sender = ConnectorEvidenceTransport(
        ConnectorTransportConfig("https://example.com", "api://example"),
        identity=Identity(),
        now=lambda: NOW,
        transport=httpx.MockTransport(respond),
    )
    try:
        result = await sender.send(packet())
        assert result.evidence_digest == packet().digest
        assert len(requests) == 1
    finally:
        await sender.aclose()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(307, headers={"location": "https://other.example.com"}),
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, content=b"x" * 8193),
        httpx.Response(200, content=b'{"status":"accepted","status":"duplicate"}'),
    ],
)
async def test_no_redirect_retry_or_unbounded_ack(response: httpx.Response) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    sender = ConnectorEvidenceTransport(
        ConnectorTransportConfig("https://example.com", "api://example"),
        identity=Identity(),
        now=lambda: NOW,
        transport=httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(ConnectorTransportError):
            await sender.send(packet())
        assert len(requests) == 1
    finally:
        await sender.aclose()


@pytest.mark.parametrize("failure", ["expired", "audience", "provider", "deadline", "cancelled"])
async def test_identity_failure_never_sends_a_request(failure: str) -> None:
    class FailedIdentity:
        async def get_token(self, audience: str) -> IdentityToken:
            if failure == "provider":
                raise RuntimeError("sensitive-provider-detail")
            if failure == "deadline":
                await asyncio.Event().wait()
            if failure == "cancelled":
                raise asyncio.CancelledError
            return IdentityToken(
                "synthetic-credential",
                NOW if failure == "expired" else NOW + timedelta(minutes=1),
                "other" if failure == "audience" else audience,
            )

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=acknowledgment())

    sender = ConnectorEvidenceTransport(
        ConnectorTransportConfig("https://example.com", "api://example", timeout_seconds=0.1),
        identity=FailedIdentity(),
        now=lambda: NOW,
        transport=httpx.MockTransport(respond),
    )
    try:
        if failure == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await sender.send(packet())
        else:
            with pytest.raises(ConnectorTransportError) as caught:
                await sender.send(packet())
            assert "sensitive-provider-detail" not in str(caught.value)
            if failure == "provider":
                assert caught.value.__suppress_context__
        assert requests == []
    finally:
        await sender.aclose()

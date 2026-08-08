from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.case_history_artifacts import (
    AzureBlobCaseHistoryArtifactStore,
    AzureBlobCaseHistoryConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            audience=audience,
        )


class _BlobTransport:
    def __init__(self) -> None:
        self.records: dict[str, tuple[bytes, str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path
        if request.method == "PUT":
            if key in self.records:
                return httpx.Response(412, request=request)
            content = request.content
            digest = request.headers["x-ms-meta-fdai-sha256"]
            self.records[key] = (content, digest)
            return httpx.Response(201, request=request)
        if request.method == "GET":
            record = self.records.get(key)
            if record is None:
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                headers={"x-ms-meta-fdai-sha256": record[1]},
                content=record[0],
                request=request,
            )
        if request.method == "DELETE":
            self.records.pop(key, None)
            return httpx.Response(202, request=request)
        return httpx.Response(405, request=request)


def _config() -> AzureBlobCaseHistoryConfig:
    return AzureBlobCaseHistoryConfig(
        container_url="https://example.blob.core.windows.net/case-history"
    )


async def _store(transport: _BlobTransport):
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return (
        AzureBlobCaseHistoryArtifactStore(
            config=_config(),
            identity=_Identity(),
            http_client=client,
        ),
        client,
    )


async def test_conditional_put_is_idempotent_for_same_content() -> None:
    transport = _BlobTransport()
    store, client = await _store(transport)
    content = b'{"case":"example"}'
    digest = hashlib.sha256(content).hexdigest()
    try:
        assert await store.put("case-history/case-1/1/artifact.json", content, digest=digest)
        assert not await store.put(
            "case-history/case-1/1/artifact.json",
            content,
            digest=digest,
        )
    finally:
        await client.aclose()


async def test_existing_reference_with_different_content_is_collision() -> None:
    transport = _BlobTransport()
    store, client = await _store(transport)
    first = b'{"case":"first"}'
    second = b'{"case":"second"}'
    try:
        await store.put(
            "case-history/case-1/1/artifact.json",
            first,
            digest=hashlib.sha256(first).hexdigest(),
        )
        with pytest.raises(ValueError, match="reference collision"):
            await store.put(
                "case-history/case-1/1/artifact.json",
                second,
                digest=hashlib.sha256(second).hexdigest(),
            )
    finally:
        await client.aclose()


async def test_get_rejects_corrupt_stored_bytes() -> None:
    transport = _BlobTransport()
    transport.records["/case-history/case-history/case-1/1/artifact.json"] = (
        b"corrupt",
        hashlib.sha256(b"original").hexdigest(),
    )
    store, client = await _store(transport)
    try:
        with pytest.raises(ValueError, match="stored artifact digest mismatch"):
            await store.get("case-history/case-1/1/artifact.json")
    finally:
        await client.aclose()


def test_config_and_storage_ref_reject_unsafe_urls_and_paths() -> None:
    with pytest.raises(ValueError, match="one HTTPS container"):
        AzureBlobCaseHistoryConfig(container_url="http://example.com/container")


@pytest.mark.parametrize(
    "storage_ref",
    (
        "case-history/%2e%2e/x.json",
        "case-history/%252e%252e/x.json",
        "case-history/../x.json",
        "case-history\\x.json",
    ),
)
async def test_storage_ref_rejects_path_aliases(storage_ref: str) -> None:
    store, client = await _store(_BlobTransport())
    try:
        with pytest.raises(ValueError, match="safe case-history path"):
            await store.get(storage_ref)
    finally:
        await client.aclose()

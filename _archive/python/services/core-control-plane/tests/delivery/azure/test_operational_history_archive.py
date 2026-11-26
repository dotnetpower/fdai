"""Private Azure operational-history artifact storage tests."""

from __future__ import annotations

import hashlib

import httpx
import pytest
from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
    AzureBlobOperationalHistoryConfig,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


def _identity() -> StaticWorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://storage.azure.com/",
        token="test-token",  # noqa: S106 - deterministic test credential
    )


async def test_blob_archive_write_and_verified_read_use_managed_identity() -> None:
    content = b'{"schema_version":"1.0.0"}\n'
    digest = hashlib.sha256(content).hexdigest()
    stored: bytes | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stored
        assert request.headers["authorization"] == "Bearer test-token"
        if request.method == "PUT":
            assert request.headers["x-ms-meta-fdai_sha256"] == digest
            stored = request.content
            return httpx.Response(201)
        return httpx.Response(
            200,
            content=stored,
            headers={"x-ms-meta-fdai_sha256": digest},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(
                container_url="https://example.blob.core.windows.net/history"
            ),
            identity=_identity(),
            http_client=client,
        )
        assert await store.put(
            "operational-history/example.json",
            content,
            digest=digest,
        )
        assert await store.get("operational-history/example.json") == content


@pytest.mark.parametrize(
    "storage_ref",
    (
        "../operational-history/example.json",
        "operational-history/../example.json",
        "other/example.json",
    ),
)
async def test_blob_archive_rejects_unsafe_storage_reference(storage_ref: str) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        store = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(
                container_url="https://example.blob.core.windows.net/history"
            ),
            identity=_identity(),
            http_client=client,
        )
        with pytest.raises(ValueError, match="storage_ref is unsafe"):
            await store.get(storage_ref)

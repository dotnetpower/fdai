"""Azure Blob rule-catalog snapshot store - fake transport, no live network."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.rule_catalog_snapshot_store import (
    AzureBlobRuleCatalogSnapshotConfig,
    AzureBlobRuleCatalogSnapshotStore,
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
        return httpx.Response(405, request=request)


def _config() -> AzureBlobRuleCatalogSnapshotConfig:
    return AzureBlobRuleCatalogSnapshotConfig(
        container_url="https://example.blob.core.windows.net/rule-catalog-snapshots"
    )


async def _store(transport: _BlobTransport):
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return (
        AzureBlobRuleCatalogSnapshotStore(
            config=_config(),
            identity=_Identity(),
            http_client=client,
        ),
        client,
    )


async def test_conditional_put_is_idempotent_for_same_content() -> None:
    transport = _BlobTransport()
    store, client = await _store(transport)
    content = b'{"source":"example"}'
    digest = hashlib.sha256(content).hexdigest()
    try:
        assert await store.put(
            "rule-catalog-snapshots/example-source/0/tree/a.yaml", content, digest=digest
        )
        assert not await store.put(
            "rule-catalog-snapshots/example-source/0/tree/a.yaml",
            content,
            digest=digest,
        )
    finally:
        await client.aclose()


async def test_existing_reference_with_different_content_is_collision() -> None:
    transport = _BlobTransport()
    store, client = await _store(transport)
    first = b'{"source":"first"}'
    second = b'{"source":"second"}'
    try:
        await store.put(
            "rule-catalog-snapshots/example-source/0/tree/a.yaml",
            first,
            digest=hashlib.sha256(first).hexdigest(),
        )
        with pytest.raises(ValueError, match="collision"):
            await store.put(
                "rule-catalog-snapshots/example-source/0/tree/a.yaml",
                second,
                digest=hashlib.sha256(second).hexdigest(),
            )
    finally:
        await client.aclose()


def test_config_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError, match="one HTTPS container"):
        AzureBlobRuleCatalogSnapshotConfig(container_url="http://example.com/container")


@pytest.mark.parametrize(
    "storage_ref",
    (
        "rule-catalog-snapshots/%2e%2e/x.json",
        "rule-catalog-snapshots/../x.json",
        "rule-catalog-snapshots\\x.json",
        "case-history/x.json",
    ),
)
async def test_storage_ref_rejects_unsafe_or_foreign_paths(storage_ref: str) -> None:
    store, client = await _store(_BlobTransport())
    try:
        with pytest.raises(ValueError, match="safe rule-catalog-snapshots/ path"):
            await store.get(storage_ref)
    finally:
        await client.aclose()

"""Exact normalized-envelope reads stay bounded, get-only, and source-private."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fdai.delivery.identity.handover_envelopes import HandoverEnvelopeReader
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts import DocumentEnvelope, ProtectionState, StructuralUnit


def envelope():
    return DocumentEnvelope(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=20,
        collection_id="manuals",
        purposes=("manual_distillation",),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="access:manuals",
        units=(
            StructuralUnit(
                unit_id="unit:1", kind="paragraph", locator="text/line:1", text="Synthetic text."
            ),
        ),
        extractor_name="synthetic",
        extractor_version="1",
    )


def local_file(tmp_path):
    source = envelope()
    path = (
        tmp_path
        / "derived/documents"
        / source.document_id.hex
        / "versions"
        / source.version_id.hex
        / "envelope.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(source.model_dump_json())
    return source, path


async def test_local_reader_returns_exact_original_units(tmp_path):
    source, _ = local_file(tmp_path)
    assert (
        await HandoverEnvelopeReader(local_root=tmp_path).read(
            source.document_id, source.version_id
        )
        == source
    )


@pytest.mark.parametrize("change", ["symlink", "fifo", "oversize", "identity", "duplicate"])
async def test_local_reader_rejects_ambiguous_or_unbounded_files(tmp_path, change):
    source, path = local_file(tmp_path)
    if change == "symlink":
        other = path.with_name("other.json")
        path.rename(other)
        path.symlink_to(other)
    elif change == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif change == "oversize":
        path.write_bytes(b"x" * 1_048_577)
    elif change == "identity":
        raw = source.model_dump(mode="json")
        raw["document_id"] = str(UUID(int=3))
        path.write_text(json.dumps(raw))
    else:
        path.write_text('{"schema_version":"1.0.0",' + source.model_dump_json()[1:])
    with pytest.raises((ValueError, OSError)):
        await HandoverEnvelopeReader(local_root=tmp_path).read(
            source.document_id, source.version_id
        )


@pytest.mark.parametrize("status", [301, 403, 429, 503])
async def test_remote_failure_never_redirects_or_retries(status):
    source = envelope()
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://example.com/other"})

    identity = SimpleNamespace(
        get_token=AsyncMock(
            return_value=IdentityToken(
                "synthetic-token",
                datetime(2026, 9, 15, tzinfo=UTC) + timedelta(minutes=5),
                "https://storage.azure.com/.default",
            )
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        reader = HandoverEnvelopeReader(
            account_url="https://example.dfs.core.windows.net",
            http_client=client,
            identity=identity,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await reader.read(source.document_id, source.version_id)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.host == "example.dfs.core.windows.net"
    identity.get_token.assert_awaited_once()


async def test_source_read_cancellation_is_not_unavailable_success(tmp_path, monkeypatch):
    source, _ = local_file(tmp_path)

    async def cancelled(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "to_thread", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await HandoverEnvelopeReader(local_root=tmp_path).read(
            source.document_id, source.version_id
        )

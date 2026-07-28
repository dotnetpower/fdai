"""Artifact broker custody, bounds, isolation, and cancellation tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fdai_evaluation_sdk import ArtifactPolicy, ArtifactSpec

from fdai.evaluation.artifacts import (
    ArtifactCustodyError,
    InMemoryArtifactBroker,
    InMemoryArtifactCustodySink,
    _storage_key,
    _StoredArtifact,
)

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _policy(**overrides: object) -> ArtifactPolicy:
    values: dict[str, object] = {
        "allowed_media_types": ("application/octet-stream", "text/x-diff"),
        "max_artifact_bytes": 16,
        "max_artifacts": 4,
        "max_ttl_seconds": 60,
    }
    values.update(overrides)
    return ArtifactPolicy.model_validate(values)


def _spec(**overrides: object) -> ArtifactSpec:
    values: dict[str, object] = {
        "name": "poc.bin",
        "media_type": "application/octet-stream",
        "max_bytes": 16,
        "ttl_seconds": 30,
    }
    values.update(overrides)
    return ArtifactSpec.model_validate(values)


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def _publish(
    broker: InMemoryArtifactBroker,
    *,
    spec: ArtifactSpec | None = None,
    chunks: AsyncIterator[bytes] | None = None,
):  # type: ignore[no-untyped-def]
    resolved = spec or _spec()
    return await broker.publish(
        session_id="session-1",
        task_id="task-1",
        spec=resolved,
        declared_outputs=(resolved,),
        chunks=chunks or _chunks(b"poc"),
        policy=_policy(),
        ttl_seconds=30,
    )


async def test_publishes_content_addressed_binary_and_verifies_read() -> None:
    custody = InMemoryArtifactCustodySink()
    broker = InMemoryArtifactBroker(custody_sink=custody, clock=lambda: _NOW, chunk_size=2)

    reference = await _publish(broker, chunks=_chunks(b"po", b"c"))
    content = b"".join(
        [chunk async for chunk in broker.read(session_id="session-1", artifact=reference)]
    )

    assert content == b"poc"
    assert reference.artifact_id == f"sha256:{reference.sha256}"
    assert [record.outcome for record in custody.records] == ["accepted", "accepted"]


async def test_rejects_oversized_and_disallowed_media_type() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    with pytest.raises(ArtifactCustodyError, match="byte limit"):
        await _publish(broker, chunks=_chunks(b"x" * 17))

    bad_spec = _spec(media_type="text/plain")
    with pytest.raises(ArtifactCustodyError, match="media type"):
        await broker.publish(
            session_id="session-1",
            task_id="task-1",
            spec=bad_spec,
            declared_outputs=(bad_spec,),
            chunks=_chunks(b"text"),
            policy=_policy(),
            ttl_seconds=30,
        )


async def test_rejects_undeclared_and_executable_output() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    spec = _spec()
    with pytest.raises(ArtifactCustodyError, match="undeclared"):
        await broker.publish(
            session_id="session-1",
            task_id="task-1",
            spec=spec,
            declared_outputs=(),
            chunks=_chunks(b"poc"),
            policy=_policy(),
            ttl_seconds=30,
        )
    executable = _spec(executable=True)
    with pytest.raises(ArtifactCustodyError, match="executable"):
        await broker.publish(
            session_id="session-1",
            task_id="task-1",
            spec=executable,
            declared_outputs=(executable,),
            chunks=_chunks(b"poc"),
            policy=_policy(),
            ttl_seconds=30,
        )


async def test_denies_cross_session_and_expired_reference() -> None:
    now = _NOW
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: now)
    reference = await _publish(broker)

    with pytest.raises(ArtifactCustodyError, match="cross-session"):
        _ = [chunk async for chunk in broker.read(session_id="session-2", artifact=reference)]

    now = _NOW + timedelta(seconds=31)
    with pytest.raises(ArtifactCustodyError, match="expired"):
        _ = [chunk async for chunk in broker.read(session_id="session-1", artifact=reference)]


async def test_detects_stored_content_digest_mismatch() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    reference = await _publish(broker)
    broker._records[_storage_key(reference)] = _StoredArtifact(  # noqa: SLF001
        reference=reference,
        content=b"tampered",
    )

    with pytest.raises(ArtifactCustodyError, match="digest mismatch"):
        _ = [chunk async for chunk in broker.read(session_id="session-1", artifact=reference)]


async def test_cancellation_keeps_partial_content_out_of_store() -> None:
    custody = InMemoryArtifactCustodySink()
    broker = InMemoryArtifactBroker(custody_sink=custody, clock=lambda: _NOW)

    async def cancelled_chunks() -> AsyncIterator[bytes]:
        yield b"partial"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _publish(broker, chunks=cancelled_chunks())

    assert broker._records == {}  # noqa: SLF001
    assert custody.records[-1].outcome == "rejected"


async def test_cleanup_removes_published_artifacts() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    reference = await _publish(broker)

    assert await broker.cleanup_session("session-1") == 1
    with pytest.raises(ArtifactCustodyError, match="unknown or altered"):
        _ = [chunk async for chunk in broker.read(session_id="session-1", artifact=reference)]

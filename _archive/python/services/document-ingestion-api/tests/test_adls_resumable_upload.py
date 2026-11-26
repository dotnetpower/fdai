"""Focused ADLS block-resume, digest, cancellation, and orphan tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from fdai_ingestion_api_service.adapters.storage import (
    AzureDataLakeConfig,
    AzureDataLakeObjectStore,
)


class Download:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self._data


class FileClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.exists = False
        self.data = bytearray()
        self.metadata: dict[str, str] = {}
        self.fail_append_once = False
        self.last_modified = datetime.now(tz=UTC)

    async def get_file_properties(self, **_kwargs: object) -> object:
        if not self.exists:
            raise ResourceNotFoundError("missing")
        return SimpleNamespace(
            size=len(self.data), metadata=self.metadata, last_modified=self.last_modified
        )

    async def create_file(self, **_kwargs: object) -> None:
        if self.exists:
            raise ResourceExistsError("exists")
        self.exists = True

    async def append_data(
        self, content: bytes, *, offset: int, length: int, **_kwargs: object
    ) -> None:
        assert offset == len(self.data)
        assert length == len(content)
        self.data.extend(content)
        if self.fail_append_once:
            self.fail_append_once = False
            raise OSError("transient")

    async def flush_data(self, _offset: int, **_kwargs: object) -> None:
        return None

    async def set_metadata(self, metadata: dict[str, str], **_kwargs: object) -> None:
        self.metadata = metadata

    async def download_file(self, **_kwargs: object) -> Download:
        return Download(bytes(self.data))

    async def delete_file(self, **_kwargs: object) -> None:
        if not self.exists:
            raise ResourceNotFoundError("missing")
        self.exists = False
        self.data.clear()
        self.metadata.clear()


class CreateRaceFileClient(FileClient):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.property_reads = 0

    async def get_file_properties(self, **kwargs: object) -> object:
        self.property_reads += 1
        if self.property_reads == 1:
            raise ResourceNotFoundError("raced")
        return await super().get_file_properties(**kwargs)

    async def create_file(self, **_kwargs: object) -> None:
        self.exists = True
        self.data.extend(b"abc")
        raise ResourceExistsError("concurrent creator")


class FileSystem:
    def __init__(self) -> None:
        self.files: dict[str, FileClient] = {}

    def get_file_client(self, name: str) -> FileClient:
        return self.files.setdefault(name, FileClient(name))

    async def get_paths(self, **_kwargs: object) -> AsyncIterator[object]:
        for client in self.files.values():
            if client.exists:
                yield SimpleNamespace(
                    name=client.name,
                    is_directory=False,
                    last_modified=client.last_modified,
                )


class ServiceClient:
    def __init__(self) -> None:
        self.file_system = FileSystem()

    def get_file_system_client(self, _name: str) -> FileSystem:
        return self.file_system

    async def close(self) -> None:
        return None


class Lease:
    def __init__(self, _client: object) -> None:
        self.acquired = False

    async def acquire(self, lease_duration: int = -1, **_kwargs: object) -> None:
        assert lease_duration == 60
        self.acquired = True

    async def renew(self, **_kwargs: object) -> None:
        assert self.acquired

    async def release(self, **_kwargs: object) -> None:
        assert self.acquired
        self.acquired = False


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


def _store(client: ServiceClient) -> AzureDataLakeObjectStore:
    return AzureDataLakeObjectStore(
        config=AzureDataLakeConfig(account_url="https://storage.example"),
        service_client=client,  # type: ignore[arg-type]
        lease_client_factory=Lease,  # type: ignore[arg-type]
    )


async def test_adls_upload_resumes_flushed_prefix_and_is_idempotent() -> None:
    client = ServiceClient()
    file_client = client.file_system.get_file_client("quarantine/1/upload")
    file_client.fail_append_once = True
    store = _store(client)

    with pytest.raises(OSError, match="transient"):
        await store.put_stream(
            "quarantine/1/upload",
            _chunks(b"abc", b"def"),
            expected_size=6,
            max_size=10,
        )
    assert bytes(file_client.data) == b"abc"

    result = await store.put_stream(
        "quarantine/1/upload",
        _chunks(b"ab", b"cdef"),
        expected_size=6,
        max_size=10,
    )
    repeated = await store.put_stream(
        "quarantine/1/upload",
        _chunks(b"different"),
        expected_size=6,
        max_size=10,
    )

    assert result == repeated
    assert result.size_bytes == 6
    assert result.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert file_client.metadata["fdai_upload_state"] == "complete"


async def test_adls_create_race_reloads_and_verifies_concurrent_prefix() -> None:
    client = ServiceClient()
    raced = CreateRaceFileClient("quarantine/1/upload")
    client.file_system.files[raced.name] = raced

    result = await _store(client).put_stream(
        raced.name,
        _chunks(b"abcdef"),
        expected_size=6,
        max_size=10,
    )

    assert bytes(raced.data) == b"abcdef"
    assert result.sha256 == hashlib.sha256(b"abcdef").hexdigest()


async def test_adls_upload_cancellation_preserves_restart_checkpoint() -> None:
    client = ServiceClient()
    store = _store(client)

    async def cancelled() -> AsyncIterator[bytes]:
        yield b"abc"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await store.put_stream(
            "quarantine/1/upload",
            cancelled(),
            expected_size=6,
            max_size=10,
        )

    result = await store.put_stream(
        "quarantine/1/upload",
        _chunks(b"abcdef"),
        expected_size=6,
        max_size=10,
    )
    assert result.sha256 == hashlib.sha256(b"abcdef").hexdigest()


async def test_adls_upload_prefix_mismatch_removes_partial_object() -> None:
    client = ServiceClient()
    file_client = client.file_system.get_file_client("quarantine/1/upload")
    file_client.exists = True
    file_client.data.extend(b"abc")

    with pytest.raises(ValueError, match="stored upload prefix"):
        await _store(client).put_stream(
            "quarantine/1/upload",
            _chunks(b"abd", b"ef"),
            expected_size=5,
            max_size=10,
        )

    assert file_client.exists is False


async def test_adls_orphan_cleanup_is_bounded_and_preserves_completed_uploads() -> None:
    client = ServiceClient()
    old = datetime.now(tz=UTC) - timedelta(hours=2)
    for name, completed in (
        ("quarantine/1/partial", False),
        ("quarantine/2/complete", True),
        ("quarantine/3/partial", False),
    ):
        item = client.file_system.get_file_client(name)
        item.exists = True
        item.data.extend(b"data")
        item.last_modified = old
        if completed:
            item.metadata["fdai_upload_state"] = "complete"

    deleted = await _store(client).cleanup_orphans(
        older_than=datetime.now(tz=UTC) - timedelta(hours=1), limit=1
    )

    assert deleted == 1
    assert client.file_system.get_file_client("quarantine/2/complete").exists is True
    assert sum(item.exists for item in client.file_system.files.values()) == 2

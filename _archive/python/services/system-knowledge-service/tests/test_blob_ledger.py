from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import fdai_system_knowledge_service.blob_ledger as blob_ledger_module
import pytest
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from fdai_system_knowledge_service.blob_ledger import (
    AzureBlobContainerAdapter,
    AzureBlobMessageLedger,
    _aware,
    _blob_name,
    _encode,
    _read,
)

KEY = "sha256:" + ("a" * 64)
FIXED_TIME = datetime(2026, 9, 10, tzinfo=UTC)


@dataclass
class _Stored:
    body: bytes
    etag: int


class _Download:
    def __init__(self, stored: _Stored) -> None:
        self._stored = stored
        self.properties = SimpleNamespace(etag=str(stored.etag))

    async def readall(self) -> bytes:
        return self._stored.body


class _Blob:
    def __init__(self, container: _Container, name: str) -> None:
        self._container = container
        self._name = name

    async def upload_blob(self, data: bytes, **kwargs: Any) -> None:
        current = self._container.records.get(self._name)
        if current is not None and kwargs.get("overwrite") is False:
            raise ResourceExistsError("exists")
        etag = kwargs.get("etag")
        if current is not None and etag is not None and str(current.etag) != etag:
            raise ResourceModifiedError("changed")
        self._container.records[self._name] = _Stored(
            body=data,
            etag=1 if current is None else current.etag + 1,
        )

    async def download_blob(self) -> _Download:
        try:
            return _Download(self._container.records[self._name])
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc

    async def delete_blob(self, **kwargs: Any) -> None:
        try:
            current = self._container.records[self._name]
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc
        if str(current.etag) != kwargs.get("etag"):
            raise ResourceModifiedError("changed")
        del self._container.records[self._name]


class _Container:
    def __init__(self) -> None:
        self.records: dict[str, _Stored] = {}
        self.probed = False
        self.closed = False

    async def _properties(self) -> object:
        self.probed = True
        return {}

    def get_container_properties(self, **_kwargs: Any) -> Any:
        return self._properties()

    async def _items(self, prefix: str) -> AsyncIterator[SimpleNamespace]:
        for name in sorted(self.records):
            if name.startswith(prefix):
                yield SimpleNamespace(name=name)

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        include: Any = None,
        **_kwargs: Any,
    ) -> AsyncIterator[SimpleNamespace]:
        del include
        return self._items(name_starts_with or "")

    def get_blob_client(
        self,
        blob: str,
        snapshot: str | None = None,
        *,
        version_id: str | None = None,
    ) -> _Blob:
        del snapshot, version_id
        return _Blob(self, blob)

    async def _close(self) -> None:
        self.closed = True

    def close(self) -> Any:
        return self._close()


class _Credential:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _ledger(
    container: _Container,
    credential: _Credential | None = None,
) -> AzureBlobMessageLedger:
    return AzureBlobMessageLedger(
        container=container,
        credential=credential or _Credential(),
        clock=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    )


async def test_blob_ledger_claims_and_delivers_exactly_once() -> None:
    container = _Container()
    credential = _Credential()
    ledger = _ledger(container, credential)
    await ledger.start()

    assert await ledger.claim(KEY) is True
    assert await ledger.claim(KEY) is False
    await ledger.mark_sending(KEY, "sha256:" + ("b" * 64))
    await ledger.mark_delivered(KEY, "provider-message")

    assert await ledger.state(KEY) == "delivered"
    await ledger.aclose()
    assert container.probed is True
    assert container.closed is True
    assert credential.closed is True


async def test_blob_ledger_reconciles_processing_and_sending_after_restart() -> None:
    container = _Container()
    ledger = _ledger(container)
    await ledger.start()
    assert await ledger.claim(KEY) is True
    await ledger.mark_sending(KEY, "sha256:" + ("b" * 64))

    other_key = "sha256:" + ("c" * 64)
    assert await ledger.claim(other_key) is True

    restarted = _ledger(container)
    await restarted.start()

    assert await restarted.state(KEY) == "ambiguous"
    assert await restarted.state(other_key) is None
    assert await restarted.claim(KEY) is False
    assert await restarted.claim(other_key) is True


async def test_blob_container_and_client_adapters_delegate_operations() -> None:
    calls: list[tuple[str, Any]] = []

    class _RawClient:
        async def upload_blob(self, data: bytes, **kwargs: Any) -> str:
            calls.append(("upload", (data, kwargs)))
            return "uploaded"

        async def download_blob(self) -> object:
            calls.append(("download", None))
            return _Download(_Stored(body=b"{}", etag=1))

        async def delete_blob(self, **kwargs: Any) -> None:
            calls.append(("delete", kwargs))

    class _RawContainer:
        async def get_container_properties(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(("props", kwargs))
            return {"ok": True}

        async def _iter(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
            calls.append(("list", kwargs))
            yield SimpleNamespace(name="claims/item.json")

        def list_blobs(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
            return self._iter(**kwargs)

        def get_blob_client(
            self,
            blob: str,
            snapshot: str | None = None,
            *,
            version_id: str | None = None,
        ) -> _RawClient:
            calls.append(("client", (blob, snapshot, version_id)))
            return _RawClient()

        async def close(self) -> None:
            calls.append(("close", None))

    adapter = AzureBlobContainerAdapter(_RawContainer())
    assert await adapter.get_container_properties(lease="lease-1", timeout=5) == {"ok": True}
    items = [item async for item in adapter.list_blobs(name_starts_with="claims/")]
    assert len(items) == 1
    client = adapter.get_blob_client("claims/item.json", "snap-1", version_id="v1")
    assert await client.upload_blob(b"payload", overwrite=True) == "uploaded"
    download = await client.download_blob()
    assert await download.readall() == b"{}"
    await client.delete_blob(etag="1")
    await adapter.close()
    assert [entry[0] for entry in calls] == [
        "props",
        "list",
        "client",
        "upload",
        "download",
        "delete",
        "close",
    ]


async def test_blob_ledger_transitions_release_and_reconcile_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _Container()
    ledger = _ledger(container)
    await ledger.start()

    assert await ledger.claim(KEY) is True
    await ledger.release_retryable(KEY)
    assert await ledger.state(KEY) is None

    assert await ledger.claim(KEY) is True
    await ledger.mark_sending(KEY, "sha256:" + ("b" * 64))
    await ledger.mark_ambiguous(KEY)
    assert await ledger.state(KEY) == "ambiguous"

    with pytest.raises(RuntimeError, match="retry release lost ownership"):
        await ledger.release_retryable(KEY)

    with pytest.raises(RuntimeError, match="transition lost ownership"):
        await ledger.mark_delivered(KEY, "act-1")

    missing_key = "sha256:" + ("d" * 64)
    with pytest.raises(RuntimeError, match="transition lost ownership"):
        await ledger.mark_sending(missing_key, "sha256:" + ("b" * 64))

    race_key = "sha256:" + ("e" * 64)
    assert await ledger.claim(race_key) is True
    orig_delete = _Blob.delete_blob

    async def _conflict_delete(self: _Blob, **kwargs: Any) -> None:
        raise ResourceModifiedError("race")

    monkeypatch.setattr(_Blob, "delete_blob", _conflict_delete)
    with pytest.raises(RuntimeError, match="retry release lost ownership"):
        await ledger.release_retryable(race_key)
    await ledger._reconcile(f"claims/{'e' * 64}.json")
    monkeypatch.setattr(_Blob, "delete_blob", orig_delete)

    no_digest_name = f"claims/{'f' * 64}.json"
    container.records[no_digest_name] = _Stored(
        body=b'{"schema_version":"1.0.0","state":"sending","updated_at":"2026-09-10T00:00:00+00:00"}',
        etag=1,
    )
    await ledger._reconcile(no_digest_name)
    assert await ledger.state("sha256:" + ("f" * 64)) == "ambiguous"

    await ledger.start()

    bad_state_name = f"claims/{'0' * 64}.json"
    container.records[bad_state_name] = _Stored(
        body=b'{"schema_version":"1.0.0","state":"bogus","updated_at":"2026-09-10T00:00:00+00:00"}',
        etag=1,
    )
    with pytest.raises(RuntimeError, match="invalid state"):
        await ledger.start()


async def test_blob_ledger_start_bounds_and_aclose_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _Container()
    container.records["claims/" + ("1" * 64) + ".json"] = _Stored(
        body=b'{"schema_version":"1.0.0","state":"delivered","updated_at":"2026-09-10T00:00:00+00:00"}',
        etag=1,
    )
    container.records["claims/" + ("2" * 64) + ".json"] = _Stored(
        body=b'{"schema_version":"1.0.0","state":"delivered","updated_at":"2026-09-10T00:00:00+00:00"}',
        etag=1,
    )
    monkeypatch.setattr(blob_ledger_module, "_MAX_RECONCILE_RECORDS", 1)
    with pytest.raises(RuntimeError, match="reconciliation exceeds its bound"):
        await _ledger(container).start()
    monkeypatch.undo()

    class _BadListContainer(_Container):
        async def _items(self, prefix: str) -> AsyncIterator[SimpleNamespace]:
            del prefix
            yield SimpleNamespace(name="invalid-prefix/item.json")

    with pytest.raises(RuntimeError, match="invalid name"):
        await _ledger(_BadListContainer()).start()

    class _FailingCloseContainer(_Container):
        async def _close(self) -> None:
            raise RuntimeError("container-close-error")

    class _FailingCredential(_Credential):
        async def close(self) -> None:
            raise RuntimeError("credential-close-error")

    with pytest.raises(RuntimeError, match="container-close-error"):
        await _ledger(_FailingCloseContainer(), _Credential()).aclose()

    with pytest.raises(RuntimeError, match="credential-close-error"):
        await _ledger(_Container(), _FailingCredential()).aclose()

    with pytest.raises(RuntimeError, match="container-close-error"):
        await _ledger(_FailingCloseContainer(), _FailingCredential()).aclose()


async def test_blob_ledger_helper_validation_guards() -> None:
    container = _Container()
    blob_name = "claims/" + ("9" * 64) + ".json"
    blob = container.get_blob_client(blob_name)

    container.records[blob_name] = _Stored(body=b"x" * 4097, etag=1)
    with pytest.raises(RuntimeError, match="exceeds its record bound"):
        await _read(blob)

    container.records[blob_name] = _Stored(body=b"{invalid", etag=1)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        await _read(blob)

    container.records[blob_name] = _Stored(body=b"[]", etag=1)
    with pytest.raises(RuntimeError, match="identity is invalid"):
        await _read(blob)

    with pytest.raises(ValueError, match="exceeds its record bound"):
        _encode({"value": "x" * 5000})

    with pytest.raises(ValueError, match="SHA-256 digest"):
        _blob_name("invalid-key")

    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        _blob_name("sha256:" + ("G" * 64))

    with pytest.raises(ValueError, match="timezone-aware"):
        _aware(datetime(2026, 9, 10))

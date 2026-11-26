"""Managed Identity Blob CAS ledger for deployed Teams reply ownership."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

_PREFIX = "claims/"
_MAX_RECORD_BYTES = 4096
_MAX_RECONCILE_RECORDS = 10_000


class BlobDownload(Protocol):
    """Bounded subset of the Azure Blob download stream."""

    properties: Any

    async def readall(self) -> bytes: ...


class BlobClient(Protocol):
    """Bounded subset of one Azure Blob client."""

    async def upload_blob(self, data: bytes, **kwargs: Any) -> Any: ...

    async def download_blob(self) -> BlobDownload: ...

    async def delete_blob(self, **kwargs: Any) -> Any: ...


class BlobContainer(Protocol):
    """Bounded container operations required by the delivery ledger."""

    def get_container_properties(
        self,
        *,
        lease: Any = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        include: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]: ...

    def get_blob_client(
        self,
        blob: str,
        snapshot: str | None = None,
        *,
        version_id: str | None = None,
    ) -> BlobClient: ...

    def close(self) -> Awaitable[None]: ...


class AsyncCredential(Protocol):
    """Close one service-owned Azure credential."""

    async def close(self) -> None: ...


class _AzureBlobClientAdapter:
    """Project the Azure SDK client onto the ledger's bounded blob protocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def upload_blob(self, data: bytes, **kwargs: Any) -> Any:
        return await self._client.upload_blob(data, **kwargs)

    async def download_blob(self) -> BlobDownload:
        return cast(BlobDownload, await self._client.download_blob())

    async def delete_blob(self, **kwargs: Any) -> Any:
        return await self._client.delete_blob(**kwargs)


class AzureBlobContainerAdapter:
    """Project the Azure SDK container onto the ledger's bounded protocol."""

    def __init__(self, container: Any) -> None:
        self._container = container

    def get_container_properties(
        self,
        *,
        lease: Any = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> Awaitable[Any]:
        return cast(
            Awaitable[Any],
            self._container.get_container_properties(
                lease=lease,
                timeout=timeout,
                **kwargs,
            ),
        )

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        include: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        return cast(
            AsyncIterator[Any],
            self._container.list_blobs(
                name_starts_with=name_starts_with,
                include=include,
                **kwargs,
            ),
        )

    def get_blob_client(
        self,
        blob: str,
        snapshot: str | None = None,
        *,
        version_id: str | None = None,
    ) -> BlobClient:
        return _AzureBlobClientAdapter(
            self._container.get_blob_client(
                blob,
                snapshot,
                version_id=version_id,
            )
        )

    def close(self) -> Awaitable[None]:
        return cast(Awaitable[None], self._container.close())


class AzureBlobMessageLedger:
    """Persist one content-free state blob per Teams message with ETag fencing."""

    def __init__(
        self,
        *,
        container: BlobContainer,
        credential: AsyncCredential,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._container = container
        self._credential = credential
        self._clock = clock or (lambda: datetime.now(UTC))

    async def start(self) -> None:
        """Probe the configured container and reconcile interrupted claims."""

        await self._container.get_container_properties()
        count = 0
        async for item in self._container.list_blobs(name_starts_with=_PREFIX):
            count += 1
            if count > _MAX_RECONCILE_RECORDS:
                raise RuntimeError("system knowledge claim reconciliation exceeds its bound")
            name = getattr(item, "name", None)
            if not isinstance(name, str) or not name.startswith(_PREFIX):
                raise RuntimeError("system knowledge claim listing returned an invalid name")
            await self._reconcile(name)

    async def claim(self, key: str) -> bool:
        """Create one processing claim only when no terminal record exists."""

        blob = self._container.get_blob_client(_blob_name(key))
        try:
            await blob.upload_blob(_record("processing", clock=self._clock), overwrite=False)
        except ResourceExistsError:
            return False
        return True

    async def mark_sending(self, key: str, response_digest: str) -> None:
        await self._transition(
            key,
            expected="processing",
            target="sending",
            response_digest=response_digest,
        )

    async def mark_delivered(self, key: str, provider_activity_id: str) -> None:
        await self._transition(
            key,
            expected="sending",
            target="delivered",
            provider_activity_id=provider_activity_id,
        )

    async def mark_ambiguous(self, key: str) -> None:
        await self._transition(key, expected="sending", target="ambiguous")

    async def release_retryable(self, key: str) -> None:
        name = _blob_name(key)
        blob = self._container.get_blob_client(name)
        current, etag = await _read(blob)
        if current.get("state") not in {"processing", "sending"}:
            raise RuntimeError("system knowledge retry release lost ownership")
        try:
            await blob.delete_blob(
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except (ResourceModifiedError, ResourceNotFoundError) as exc:
            raise RuntimeError("system knowledge retry release lost ownership") from exc

    async def state(self, key: str) -> str | None:
        blob = self._container.get_blob_client(_blob_name(key))
        try:
            current, _etag = await _read(blob)
        except ResourceNotFoundError:
            return None
        state = current.get("state")
        return state if isinstance(state, str) else None

    async def aclose(self) -> None:
        """Close the Azure client and its dedicated credential."""

        first_error: BaseException | None = None
        try:
            await self._container.close()
        except BaseException as exc:
            first_error = exc
        try:
            await self._credential.close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error

    async def _reconcile(self, name: str) -> None:
        blob = self._container.get_blob_client(name)
        current, etag = await _read(blob)
        state = current.get("state")
        if state == "processing":
            try:
                await blob.delete_blob(
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            except (ResourceModifiedError, ResourceNotFoundError):
                return
        elif state == "sending":
            await self._transition_blob(
                blob,
                current=current,
                etag=etag,
                expected="sending",
                target="ambiguous",
            )
        elif state not in {"delivered", "ambiguous"}:
            raise RuntimeError("system knowledge claim contains an invalid state")

    async def _transition(
        self,
        key: str,
        *,
        expected: str,
        target: str,
        response_digest: str | None = None,
        provider_activity_id: str | None = None,
    ) -> None:
        blob = self._container.get_blob_client(_blob_name(key))
        try:
            current, etag = await _read(blob)
            await self._transition_blob(
                blob,
                current=current,
                etag=etag,
                expected=expected,
                target=target,
                response_digest=response_digest,
                provider_activity_id=provider_activity_id,
            )
        except (ResourceModifiedError, ResourceNotFoundError) as exc:
            raise RuntimeError("system knowledge delivery transition lost ownership") from exc

    async def _transition_blob(
        self,
        blob: BlobClient,
        *,
        current: Mapping[str, object],
        etag: str,
        expected: str,
        target: str,
        response_digest: str | None = None,
        provider_activity_id: str | None = None,
    ) -> None:
        if current.get("state") != expected:
            raise RuntimeError("system knowledge delivery transition lost ownership")
        updated: dict[str, object] = {
            "schema_version": "1.0.0",
            "state": target,
            "updated_at": _aware(self._clock()).isoformat(),
        }
        retained_response = response_digest or current.get("response_digest")
        retained_activity = provider_activity_id or current.get("provider_activity_id")
        if retained_response is not None:
            updated["response_digest"] = retained_response
        if retained_activity is not None:
            updated["provider_activity_id"] = retained_activity
        await blob.upload_blob(
            _encode(updated),
            overwrite=True,
            etag=etag,
            match_condition=MatchConditions.IfNotModified,
        )


async def _read(blob: BlobClient) -> tuple[dict[str, object], str]:
    download = await blob.download_blob()
    body = await download.readall()
    if len(body) > _MAX_RECORD_BYTES:
        raise RuntimeError("system knowledge claim exceeds its record bound")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("system knowledge claim is invalid JSON") from exc
    etag = getattr(download.properties, "etag", None)
    if not isinstance(value, dict) or not isinstance(etag, str) or not etag:
        raise RuntimeError("system knowledge claim identity is invalid")
    return value, etag


def _record(state: str, *, clock: Callable[[], datetime]) -> bytes:
    return _encode(
        {
            "schema_version": "1.0.0",
            "state": state,
            "updated_at": _aware(clock()).isoformat(),
        }
    )


def _encode(value: Mapping[str, object]) -> bytes:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > _MAX_RECORD_BYTES:
        raise ValueError("system knowledge claim exceeds its record bound")
    return encoded


def _blob_name(key: str) -> str:
    if not key.startswith("sha256:") or len(key) != 71:
        raise ValueError("system knowledge message key MUST be a SHA-256 digest")
    digest = key.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("system knowledge message key MUST be lowercase hexadecimal")
    return f"{_PREFIX}{digest}.json"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("system knowledge ledger clock MUST be timezone-aware")
    return value


__all__ = [
    "AzureBlobContainerAdapter",
    "AzureBlobMessageLedger",
    "BlobClient",
    "BlobContainer",
    "BlobDownload",
]

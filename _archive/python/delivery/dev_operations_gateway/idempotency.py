"""Durable idempotency ledger for development gateway mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx

_STORAGE_AUDIENCE = "https://storage.azure.com/"
_STORAGE_API_VERSION = "2025-05-05"
_UTC = timezone.utc  # noqa: UP017 - deployed Function worker supports Python 3.10
_MAX_RECORD_BYTES = 262_144
_CLAIM_TIMEOUT = timedelta(seconds=90)
_RESOURCE_LEASE_SECONDS = "60"
_DRY_RUN_TTL = timedelta(minutes=5)


class IdempotencyError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class TokenProvider(Protocol):
    async def get_token(self, audience: str) -> str: ...


class IdempotencyLedger(Protocol):
    async def begin(
        self, idempotency_key: str, request_digest: str
    ) -> Mapping[str, object] | None: ...

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None: ...

    async def abort(self, idempotency_key: str, request_digest: str) -> None: ...

    async def lookup(self, idempotency_key: str) -> Mapping[str, object]: ...

    async def acquire_resource(self, resource_key: str) -> str: ...

    async def release_resource(self, resource_key: str, lease_id: str) -> None: ...

    async def renew_resource(self, resource_key: str, lease_id: str) -> None: ...

    async def update_response(
        self,
        idempotency_key: str,
        response: Mapping[str, object],
    ) -> None: ...

    async def issue_dry_run(self, request_digest: str) -> str: ...

    async def consume_dry_run(self, receipt: str, request_digest: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AzureBlobIdempotencyConfig:
    container_url: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.container_url)
        path_segments = tuple(segment for segment in parsed.path.split("/") if segment)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or len(path_segments) != 1
        ):
            raise ValueError("idempotency container URL MUST identify one HTTPS container")


class AzureBlobIdempotencyLedger:
    """Use conditional Blob writes to serialize mutation delivery by key."""

    def __init__(
        self,
        *,
        config: AzureBlobIdempotencyConfig,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._container_url = config.container_url.rstrip("/")
        self._tokens = token_provider
        self._http = http_client
        self._claims: dict[str, str] = {}

    async def begin(self, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        blob_url = self._blob_url(idempotency_key)
        record = self._pending_record(request_digest)
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
            }
        )
        response = await self._request(
            "PUT",
            blob_url,
            headers=headers,
            content=record,
        )
        if response.status_code == 201:
            etag = response.headers.get("ETag", "")
            if not etag:
                raise IdempotencyError(
                    503,
                    "idempotency_unavailable",
                    "idempotency claim response did not include an ETag",
                )
            self._claims[idempotency_key] = etag
            return None
        if response.status_code not in {409, 412}:
            self._raise_storage_error(response)

        existing, existing_etag = await self._read(blob_url)
        if existing.get("request_digest") != request_digest:
            raise IdempotencyError(
                409,
                "idempotency_conflict",
                "idempotency key was already used for a different request",
            )
        if existing.get("state") == "completed":
            result = existing.get("response")
            if isinstance(result, Mapping):
                return dict(result)
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "completed idempotency record did not contain a response",
            )
        if existing.get("state") == "pending":
            claimed_at = _parse_timestamp(existing.get("claimed_at"))
            if claimed_at is not None and datetime.now(_UTC) - claimed_at >= _CLAIM_TIMEOUT:
                await self._replace_stale_claim(
                    blob_url,
                    existing_etag,
                    idempotency_key,
                    request_digest,
                )
                return None
            raise IdempotencyError(
                409,
                "idempotency_in_progress",
                "an operation with this idempotency key is already in progress",
            )
        raise IdempotencyError(
            503,
            "idempotency_unavailable",
            "idempotency record state was invalid",
        )

    async def lookup(self, idempotency_key: str) -> Mapping[str, object]:
        response = await self._request(
            "GET",
            self._blob_url(idempotency_key),
            headers=await self._headers(),
        )
        if response.status_code == 404:
            raise IdempotencyError(404, "idempotency_not_found", "operation record was not found")
        if response.status_code != 200:
            self._raise_storage_error(response)
        record, _etag = self._decode_record(response)
        if record.get("state") == "pending":
            raise IdempotencyError(409, "idempotency_in_progress", "operation is still in progress")
        result = record.get("response")
        if record.get("state") != "completed" or not isinstance(result, Mapping):
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "operation record did not contain a completed response",
            )
        return dict(result)

    async def acquire_resource(self, resource_key: str) -> str:
        lock_url = self._lock_url(resource_key)
        create_headers = await self._headers()
        create_headers.update({"If-None-Match": "*", "x-ms-blob-type": "BlockBlob"})
        created = await self._request("PUT", lock_url, headers=create_headers, content=b"")
        if created.status_code not in {201, 409, 412}:
            self._raise_storage_error(created)

        lease_headers = await self._headers()
        lease_headers.update(
            {
                "x-ms-lease-action": "acquire",
                "x-ms-lease-duration": _RESOURCE_LEASE_SECONDS,
            }
        )
        leased = await self._request("PUT", f"{lock_url}?comp=lease", headers=lease_headers)
        if leased.status_code in {409, 412}:
            raise IdempotencyError(
                409,
                "resource_busy",
                "another mutation is already operating on this resource",
            )
        if leased.status_code != 201:
            self._raise_storage_error(leased)
        lease_id = leased.headers.get("x-ms-lease-id", "")
        if not isinstance(lease_id, str) or not lease_id:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "resource lease response did not include a lease id",
            )
        return lease_id

    async def release_resource(self, resource_key: str, lease_id: str) -> None:
        headers = await self._headers()
        headers.update({"x-ms-lease-action": "release", "x-ms-lease-id": lease_id})
        response = await self._request(
            "PUT",
            f"{self._lock_url(resource_key)}?comp=lease",
            headers=headers,
        )
        if response.status_code not in {200, 404, 409, 412}:
            self._raise_storage_error(response)

    async def renew_resource(self, resource_key: str, lease_id: str) -> None:
        headers = await self._headers()
        headers.update({"x-ms-lease-action": "renew", "x-ms-lease-id": lease_id})
        response = await self._request(
            "PUT",
            f"{self._lock_url(resource_key)}?comp=lease",
            headers=headers,
        )
        if response.status_code != 200:
            raise IdempotencyError(
                409,
                "resource_lock_lost",
                "resource lease could not be renewed",
            )

    async def update_response(
        self,
        idempotency_key: str,
        response: Mapping[str, object],
    ) -> None:
        blob_url = self._blob_url(idempotency_key)
        existing, etag = await self._read(blob_url)
        request_digest = existing.get("request_digest")
        if existing.get("state") != "completed" or not isinstance(request_digest, str):
            raise IdempotencyError(
                409,
                "idempotency_conflict",
                "operation response cannot be updated from its current state",
            )
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-Match": etag,
                "x-ms-blob-type": "BlockBlob",
            }
        )
        updated = await self._request(
            "PUT",
            blob_url,
            headers=headers,
            content=self._encode_record(
                {
                    "state": "completed",
                    "request_digest": request_digest,
                    "response": response,
                }
            ),
        )
        if updated.status_code in {409, 412}:
            raise IdempotencyError(
                409,
                "idempotency_conflict",
                "operation response changed concurrently",
            )
        if updated.status_code != 201:
            self._raise_storage_error(updated)

    async def issue_dry_run(self, request_digest: str) -> str:
        receipt = hashlib.sha256(f"fdai-dev-gateway-plan-v1:{request_digest}".encode()).hexdigest()
        expires_at = datetime.now(_UTC) + _DRY_RUN_TTL
        record = self._encode_record(
            {
                "state": "ready",
                "request_digest": request_digest,
                "expires_at": expires_at.isoformat(),
            }
        )
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
            }
        )
        response = await self._request(
            "PUT",
            self._dry_run_url(receipt),
            headers=headers,
            content=record,
        )
        if response.status_code in {409, 412}:
            existing, _etag = await self._read(self._dry_run_url(receipt))
            existing_expires_at = _parse_timestamp(existing.get("expires_at"))
            if (
                existing.get("state") == "ready"
                and existing.get("request_digest") == request_digest
                and existing_expires_at is not None
                and existing_expires_at > datetime.now(_UTC)
            ):
                return receipt
            raise IdempotencyError(
                409,
                "dry_run_invalid",
                "existing dry-run plan is expired or already consumed",
            )
        if response.status_code != 201:
            self._raise_storage_error(response)
        return receipt

    async def consume_dry_run(self, receipt: str, request_digest: str) -> None:
        response = await self._request(
            "GET",
            self._dry_run_url(receipt),
            headers=await self._headers(),
        )
        if response.status_code == 404:
            raise IdempotencyError(409, "dry_run_invalid", "dry-run receipt was not found")
        if response.status_code != 200:
            self._raise_storage_error(response)
        record, etag = self._decode_record(response)
        expires_at = _parse_timestamp(record.get("expires_at"))
        if (
            record.get("state") != "ready"
            or record.get("request_digest") != request_digest
            or expires_at is None
            or expires_at <= datetime.now(_UTC)
        ):
            raise IdempotencyError(
                409,
                "dry_run_invalid",
                "dry-run receipt is expired, consumed, or bound to another request",
            )
        consumed = self._encode_record(
            {
                "state": "consumed",
                "request_digest": request_digest,
                "expires_at": expires_at.isoformat(),
            }
        )
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-Match": etag,
                "x-ms-blob-type": "BlockBlob",
            }
        )
        updated = await self._request(
            "PUT",
            self._dry_run_url(receipt),
            headers=headers,
            content=consumed,
        )
        if updated.status_code in {409, 412}:
            raise IdempotencyError(409, "dry_run_invalid", "dry-run receipt was already consumed")
        if updated.status_code != 201:
            self._raise_storage_error(updated)

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None:
        etag = self._claims.get(idempotency_key)
        if not etag:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency claim was not held by this invocation",
            )
        record = self._encode_record(
            {
                "state": "completed",
                "request_digest": request_digest,
                "response": response,
            }
        )
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-Match": etag,
                "x-ms-blob-type": "BlockBlob",
            }
        )
        blob_url = self._blob_url(idempotency_key)
        try:
            result = await self._request(
                "PUT",
                blob_url,
                headers=headers,
                content=record,
            )
        except IdempotencyError as write_error:
            if await self._completion_matches(blob_url, request_digest, response):
                self._claims.pop(idempotency_key, None)
                return
            raise write_error
        if result.status_code != 201:
            if await self._completion_matches(blob_url, request_digest, response):
                self._claims.pop(idempotency_key, None)
                return
            self._raise_storage_error(result)
        self._claims.pop(idempotency_key, None)

    async def abort(self, idempotency_key: str, request_digest: str) -> None:
        del request_digest
        etag = self._claims.pop(idempotency_key, None)
        if not etag:
            return
        headers = await self._headers()
        headers["If-Match"] = etag
        response = await self._request(
            "DELETE",
            self._blob_url(idempotency_key),
            headers=headers,
        )
        if response.status_code not in {202, 404}:
            self._raise_storage_error(response)

    async def _read(self, blob_url: str) -> tuple[Mapping[str, object], str]:
        response = await self._request("GET", blob_url, headers=await self._headers())
        if response.status_code != 200:
            self._raise_storage_error(response)
        return self._decode_record(response)

    async def _completion_matches(
        self,
        blob_url: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> bool:
        try:
            existing, _etag = await self._read(blob_url)
        except IdempotencyError:
            return False
        return (
            existing.get("state") == "completed"
            and existing.get("request_digest") == request_digest
            and existing.get("response") == response
        )

    def _decode_record(self, response: httpx.Response) -> tuple[Mapping[str, object], str]:
        if len(response.content) > _MAX_RECORD_BYTES:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record exceeded its size limit",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record was not valid JSON",
            ) from exc
        etag = response.headers.get("ETag", "")
        if not isinstance(payload, Mapping) or not etag:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record was incomplete",
            )
        return payload, etag

    async def _replace_stale_claim(
        self,
        blob_url: str,
        etag: str,
        idempotency_key: str,
        request_digest: str,
    ) -> None:
        headers = await self._headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "If-Match": etag,
                "x-ms-blob-type": "BlockBlob",
            }
        )
        response = await self._request(
            "PUT",
            blob_url,
            headers=headers,
            content=self._pending_record(request_digest),
        )
        if response.status_code in {409, 412}:
            raise IdempotencyError(
                409,
                "idempotency_in_progress",
                "another invocation reclaimed this operation",
            )
        if response.status_code != 201:
            self._raise_storage_error(response)
        replacement_etag = response.headers.get("ETag", "")
        if not replacement_etag:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "replacement claim response did not include an ETag",
            )
        self._claims[idempotency_key] = replacement_etag

    async def _headers(self) -> dict[str, str]:
        token = await self._tokens.get_token(_STORAGE_AUDIENCE)
        return {
            "Authorization": f"Bearer {token}",
            "x-ms-date": format_datetime(datetime.now(_UTC), usegmt=True),
            "x-ms-version": _STORAGE_API_VERSION,
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None = None,
    ) -> httpx.Response:
        try:
            return await self._http.request(
                method,
                url,
                headers=headers,
                content=content,
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency storage request failed",
            ) from exc

    def _blob_url(self, idempotency_key: str) -> str:
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"{self._container_url}/{key_digest}.json"

    def _lock_url(self, resource_key: str) -> str:
        key_digest = hashlib.sha256(resource_key.encode("utf-8")).hexdigest()
        return f"{self._container_url}/locks/{key_digest}.lock"

    def _dry_run_url(self, receipt: str) -> str:
        receipt_digest = hashlib.sha256(receipt.encode("utf-8")).hexdigest()
        return f"{self._container_url}/dry-runs/{receipt_digest}.json"

    @staticmethod
    def _pending_record(request_digest: str) -> bytes:
        return AzureBlobIdempotencyLedger._encode_record(
            {
                "state": "pending",
                "request_digest": request_digest,
                "claimed_at": datetime.now(_UTC).isoformat(),
            }
        )

    @staticmethod
    def _encode_record(record: Mapping[str, object]) -> bytes:
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise IdempotencyError(
                503,
                "idempotency_unavailable",
                "idempotency record exceeded its size limit",
            )
        return encoded

    @staticmethod
    def _raise_storage_error(response: httpx.Response) -> None:
        raise IdempotencyError(
            503,
            "idempotency_unavailable",
            f"idempotency storage returned HTTP {response.status_code}",
        )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(_UTC)


__all__ = [
    "AzureBlobIdempotencyConfig",
    "AzureBlobIdempotencyLedger",
    "IdempotencyError",
    "IdempotencyLedger",
]

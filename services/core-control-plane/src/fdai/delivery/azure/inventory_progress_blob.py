"""Immutable private-Blob publisher for sanitized inventory progress records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fdai_service_contracts import InventoryProgressRecord

from fdai.shared.providers.workload_identity import WorkloadIdentity

_STORAGE_AUDIENCE = "https://storage.azure.com/.default"
_STORAGE_API_VERSION = "2025-05-05"
_MAX_RECORD_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class AzureBlobInventoryProgressConfig:
    """Credential-free HTTPS container binding for one private progress ledger."""

    container_url: str
    prefix: str = "inventory-progress/v1"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.container_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("inventory progress container URL MUST be credential-free HTTPS")
        if parsed.hostname is None or not parsed.hostname.endswith(".blob.core.windows.net"):
            raise ValueError("inventory progress container URL MUST use Azure Blob Storage")
        if len([part for part in parsed.path.split("/") if part]) != 1:
            raise ValueError("inventory progress container URL MUST name exactly one container")
        if not self.prefix or any(part in {"", ".", ".."} for part in self.prefix.split("/")):
            raise ValueError("inventory progress Blob prefix is invalid")
        if self.timeout_seconds <= 0:
            raise ValueError("inventory progress Blob timeout MUST be positive")


class AzureBlobInventoryProgressPublisher:
    """Append one content-addressed record and verify exact duplicate retries."""

    def __init__(
        self,
        *,
        config: AzureBlobInventoryProgressConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def append(self, record: InventoryProgressRecord) -> bool:
        """Create one immutable Blob or accept only byte-identical retained content."""

        payload = json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > _MAX_RECORD_BYTES:
            raise ValueError("inventory progress record exceeds its Blob byte bound")
        url = self._record_url(record)
        headers = await self._headers()
        response = await self._http.put(
            url,
            headers={
                **headers,
                "Content-Type": "application/json",
                "If-None-Match": "*",
                "x-ms-blob-type": "BlockBlob",
            },
            content=payload,
            timeout=self._config.timeout_seconds,
        )
        if response.status_code in {200, 201}:
            return True
        if response.status_code != 412:
            raise RuntimeError(
                f"inventory progress Blob append returned HTTP {response.status_code}"
            )
        retained = await self._http.get(
            url,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        if retained.status_code != 200:
            raise RuntimeError(
                f"inventory progress Blob duplicate read returned HTTP {retained.status_code}"
            )
        if len(retained.content) > _MAX_RECORD_BYTES or retained.content != payload:
            raise ValueError("inventory progress Blob duplicate conflicts with retained content")
        return False

    async def _headers(self) -> dict[str, str]:
        token = await self._identity.get_token(_STORAGE_AUDIENCE)
        return {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
            "x-ms-version": _STORAGE_API_VERSION,
        }

    def _record_url(self, record: InventoryProgressRecord) -> str:
        name = (
            f"{self._config.prefix}/{record.run_id}/{record.attempt_id}/"
            f"{record.sequence:020d}-{record.record_digest.removeprefix('sha256:')}.json"
        )
        return f"{self._config.container_url.rstrip('/')}/{name}"


__all__ = [
    "AzureBlobInventoryProgressConfig",
    "AzureBlobInventoryProgressPublisher",
]

"""Read exact normalized envelopes from the existing private same-venue document store.

This adapter has no authority to admit a source. Callers must first verify current document
admission and recheck it after reads. Coordinates are canonical UUIDs, not user URLs or paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fdai_service_contracts import DocumentEnvelope

from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_BYTES = 1_048_576


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("normalized envelope contains duplicate keys")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class HandoverEnvelopeReader:
    """GET-only remote or bounded local read, never reparse or reconstruct a source document."""

    local_root: Path | None = None
    account_url: str | None = None
    file_system: str = "derived"
    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None

    def __post_init__(self) -> None:
        if (self.local_root is None) == (self.account_url is None):
            raise ValueError("handover envelope requires one exact local or remote source")
        if self.account_url is not None and (
            re.fullmatch(r"https://[a-z0-9]{3,24}\.dfs\.core\.windows\.net", self.account_url)
            is None
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.file_system) is None
            or self.http_client is None
            or self.identity is None
        ):
            raise ValueError(
                "handover envelope remote source must use configured ADLS and read identity"
            )

    async def read(self, document: UUID, version: UUID) -> DocumentEnvelope:
        """Read at most one MiB in five seconds; every failure holds and cancellation propagates."""
        parts = ("documents", document.hex, "versions", version.hex, "envelope.json")
        async with asyncio.timeout(5):
            if self.local_root is not None:
                raw = await asyncio.to_thread(self._local, parts)
            else:
                if self.http_client is None or self.identity is None:
                    raise ValueError("handover envelope remote read binding is unavailable")
                token = await self.identity.get_token("https://storage.azure.com/.default")
                url = f"{self.account_url}/{self.file_system}/{'/'.join(parts)}"
                async with self.http_client.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {token.token}",
                        "x-ms-version": "2023-11-03",
                    },
                    follow_redirects=False,
                    timeout=5.0,
                ) as response:
                    response.raise_for_status()
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > _MAX_BYTES:
                            raise ValueError("normalized envelope exceeds its read bound")
                    raw = bytes(chunks)
            envelope = DocumentEnvelope.model_validate(json.loads(raw, object_pairs_hook=_pairs))
            if (
                envelope.document_id != document
                or envelope.version_id != version
                or not 1 <= len(envelope.units) <= 256
                or sum(len(unit.text) for unit in envelope.units) > 100_000
            ):
                raise ValueError("normalized envelope identity or extraction size is invalid")
            return envelope

    def _local(self, parts: tuple[str, ...]) -> bytes:
        if self.local_root is None:
            raise ValueError("handover local envelope root is unavailable")
        handles: list[int] = []
        try:
            handles.append(os.open(self.local_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
            for part in ("derived", *parts[:-1]):
                handles.append(
                    os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=handles[-1],
                    )
                )
            file = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=handles[-1]
            )
            handles.append(file)
            before = os.fstat(file)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
                raise ValueError("normalized envelope must be a bounded regular file")
            with os.fdopen(os.dup(file), "rb") as stream:
                raw = stream.read(_MAX_BYTES + 1)
            after = os.fstat(file)
            if (
                len(raw) > _MAX_BYTES
                or len(raw) != after.st_size
                or (before.st_mtime_ns, before.st_ctime_ns, before.st_size)
                != (after.st_mtime_ns, after.st_ctime_ns, after.st_size)
            ):
                raise ValueError("normalized envelope changed during its bounded read")
            return raw
        finally:
            for handle in reversed(handles):
                os.close(handle)


__all__ = ["HandoverEnvelopeReader"]

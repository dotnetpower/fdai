"""Durable bounded case-history artifacts stored through the StateStore seam."""

from __future__ import annotations

import base64
import hashlib
import re

from fdai.shared.providers.state_store import StateStore

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 1024 * 1024
_PREFIX = "catalog-review-case-artifact:"


class StateStoreCaseHistoryArtifactStore:
    """Persist frozen one-shot case artifacts without an in-memory fallback."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        if (
            not storage_ref
            or len(storage_ref) > 512
            or _DIGEST.fullmatch(digest) is None
            or not content
            or len(content) > _MAX_ARTIFACT_BYTES
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise ValueError("catalog review case artifact is invalid")
        key = _PREFIX + hashlib.sha256(storage_ref.encode()).hexdigest()
        value = {
            "storage_ref_digest": hashlib.sha256(storage_ref.encode()).hexdigest(),
            "content_digest": digest,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
        created = await self._store.write_state_if_absent(key, value)
        retained = await self._store.read_state(key)
        if retained != value:
            raise ValueError("catalog review case artifact idempotency conflict")
        return created

    async def get(self, storage_ref: str) -> bytes | None:
        key = _PREFIX + hashlib.sha256(storage_ref.encode()).hexdigest()
        value = await self._store.read_state(key)
        if value is None:
            return None
        encoded = value.get("content_base64")
        digest = value.get("content_digest")
        if not isinstance(encoded, str) or not isinstance(digest, str):
            raise ValueError("catalog review case artifact is invalid")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("catalog review case artifact encoding is invalid") from exc
        if len(content) > _MAX_ARTIFACT_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("catalog review case artifact digest differs")
        return content

    async def delete(self, storage_ref: str) -> None:
        raise RuntimeError("catalog review case artifacts are append-only")


__all__ = ["StateStoreCaseHistoryArtifactStore"]

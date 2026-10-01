"""Core-owned encrypted result-handle storage contracts."""

from __future__ import annotations

import base64
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.reasoning_handles import (
    ResultHandle,
    ResultHandleRef,
    TypedRowKey,
    decode_reasoning_record,
    encode_reasoning_record,
)
from pydantic import Field

from fdai.shared.providers.secret_provider import SecretProvider

_ENVELOPE_SCHEMA_VERSION = "1.0"
_ALGORITHM = "AES-256-GCM"
_NONCE_BYTES = 12
_HANDLE_REF_BYTES = 32
_DEFAULT_CURRENT_MATERIAL_REF = "FDAI_RESULT_HANDLE_MATERIAL"
_DEFAULT_PREVIOUS_MATERIAL_REF = "FDAI_RESULT_HANDLE_PREVIOUS_MATERIAL"


class ResultHandleGetStatus(StrEnum):
    """Typed binding outcomes used by prior-result clarification paths."""

    BOUND = "bound"
    FOREIGN = "prior_result_foreign"
    UNAVAILABLE = "prior_result_unavailable"
    EXPIRED = "prior_result_expired"


@dataclass(frozen=True, slots=True)
class ResultHandleBinding:
    """Request binding fields that must match before a handle body is usable."""

    deployment_scope_digest: str
    principal_digest: str
    conversation_id: str
    purpose: str
    manifest_digest: str
    now: datetime

    def __post_init__(self) -> None:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("result handle binding time MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResultHandleGetResult:
    """Loaded handle or the stable reason it did not bind."""

    status: ResultHandleGetStatus
    handle: ResultHandle | None = None


@dataclass(frozen=True, slots=True)
class ResultHandleKey:
    """One AES-GCM key version."""

    key_version: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise ValueError("result handle encryption keys MUST be 32 bytes")


class ResultHandleKeyProvider(Protocol):
    """Provide the current encryption key and retained decryption-only keys."""

    async def current_key(self) -> ResultHandleKey: ...

    async def key_for_version(self, key_version: str) -> ResultHandleKey | None: ...


class ResultHandleStore(Protocol):
    """Core-owned durable store for encrypted result handle bodies."""

    async def put(
        self,
        handle: ResultHandle,
        *,
        issued_at: datetime,
        expires_at: datetime,
    ) -> ResultHandleRef: ...

    async def get(
        self,
        reference: ResultHandleRef,
        *,
        binding: ResultHandleBinding,
        allowed_snapshot_fields: Iterable[str] = (),
    ) -> ResultHandleGetResult: ...

    async def delete_conversation(
        self,
        *,
        deployment_scope_digest: str,
        conversation_id: str,
    ) -> int: ...


class SecretProviderResultHandleKeyProvider:
    """Resolve current and previous result-handle AES-GCM keys through SecretProvider."""

    def __init__(
        self,
        secrets: SecretProvider,
        *,
        current_secret_name: str = _DEFAULT_CURRENT_MATERIAL_REF,
        previous_secret_name: str = _DEFAULT_PREVIOUS_MATERIAL_REF,
        current_key_version: str = "result-handle-key-v1",
        previous_key_version: str | None = None,
    ) -> None:
        self._secrets = secrets
        self._current_secret_name = current_secret_name
        self._previous_secret_name = previous_secret_name
        self._current_key_version = current_key_version
        self._previous_key_version = previous_key_version

    async def current_key(self) -> ResultHandleKey:
        value = await self._secrets.get(self._current_secret_name)
        return ResultHandleKey(self._current_key_version, _decode_key(value))

    async def key_for_version(self, key_version: str) -> ResultHandleKey | None:
        if key_version == self._current_key_version:
            return await self.current_key()
        if self._previous_key_version is not None and key_version == self._previous_key_version:
            value = await self._secrets.get(self._previous_secret_name)
            return ResultHandleKey(self._previous_key_version, _decode_key(value))
        return None


class StaticResultHandleKeyProvider:
    """Deterministic test/local key provider with one optional previous key."""

    def __init__(
        self,
        *,
        current: ResultHandleKey,
        previous: ResultHandleKey | None = None,
    ) -> None:
        self._current = current
        self._previous = previous

    async def current_key(self) -> ResultHandleKey:
        return self._current

    async def key_for_version(self, key_version: str) -> ResultHandleKey | None:
        if key_version == self._current.key_version:
            return self._current
        if self._previous is not None and key_version == self._previous.key_version:
            return self._previous
        return None


@dataclass(frozen=True, slots=True)
class _StoredHandle:
    handle_ref: str
    deployment_scope_digest: str
    principal_digest: str
    conversation_id: str
    purpose: str
    manifest_digest: str
    issued_at: datetime
    expires_at: datetime
    key_version: str
    envelope: Mapping[str, object]


class InMemoryResultHandleStore:
    """Encrypted in-memory implementation for local and focused tests."""

    def __init__(
        self,
        *,
        keys: ResultHandleKeyProvider,
        handle_ref_factory: Callable[[], str] | None = None,
    ) -> None:
        self._keys = keys
        self._handle_ref_factory = handle_ref_factory or _new_handle_ref
        self._records: dict[str, _StoredHandle] = {}

    async def put(
        self,
        handle: ResultHandle,
        *,
        issued_at: datetime,
        expires_at: datetime,
    ) -> ResultHandleRef:
        _validate_ref_times(issued_at, expires_at)
        key = await self._keys.current_key()
        handle_ref = self._handle_ref_factory()
        envelope = _encrypt_handle(handle, key=key, handle_ref=handle_ref)
        self._records[handle_ref] = _StoredHandle(
            handle_ref=handle_ref,
            deployment_scope_digest=handle.deployment_scope_digest,
            principal_digest=handle.principal_digest,
            conversation_id=handle.conversation_id,
            purpose=handle.purpose,
            manifest_digest=handle.manifest_digest,
            issued_at=issued_at,
            expires_at=expires_at,
            key_version=key.key_version,
            envelope=envelope,
        )
        return ResultHandleRef(
            handle_ref=handle_ref,
            key_version=key.key_version,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    async def get(
        self,
        reference: ResultHandleRef,
        *,
        binding: ResultHandleBinding,
        allowed_snapshot_fields: Iterable[str] = (),
    ) -> ResultHandleGetResult:
        record = self._records.get(reference.handle_ref)
        if record is None:
            return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
        return await _load_record(
            record,
            reference=reference,
            binding=binding,
            keys=self._keys,
            allowed_snapshot_fields=allowed_snapshot_fields,
        )

    async def delete_conversation(
        self,
        *,
        deployment_scope_digest: str,
        conversation_id: str,
    ) -> int:
        refs = [
            ref
            for ref, record in self._records.items()
            if record.deployment_scope_digest == deployment_scope_digest
            and record.conversation_id == conversation_id
        ]
        for ref in refs:
            del self._records[ref]
        return len(refs)


def rendered_order_digest(row_keys: tuple[TypedRowKey, ...]) -> str:
    """Digest the rows in the exact rendered order."""

    return cast(str, content_digest([row.model_dump(mode="json") for row in row_keys]))


def reauthorize_result_handle_rows(
    handle: ResultHandle,
    *,
    readable_rows: Iterable[TypedRowKey],
) -> ResultHandle:
    """Drop rows that a secured reread no longer authorizes."""

    readable = {row.model_dump_json() for row in readable_rows}
    rows = tuple(row for row in handle.row_keys if row.model_dump_json() in readable)
    snapshot_rows = tuple(
        row for row in handle.snapshot_cells if row.row_key.model_dump_json() in readable
    )
    return handle.model_copy(
        update={
            "row_keys": rows,
            "snapshot_cells": snapshot_rows,
            "rendered_order_digest": rendered_order_digest(rows),
        }
    )


async def _load_record(
    record: _StoredHandle,
    *,
    reference: ResultHandleRef,
    binding: ResultHandleBinding,
    keys: ResultHandleKeyProvider,
    allowed_snapshot_fields: Iterable[str],
) -> ResultHandleGetResult:
    if binding.now >= min(reference.expires_at, record.expires_at):
        return ResultHandleGetResult(ResultHandleGetStatus.EXPIRED)
    if reference.key_version != record.key_version:
        return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
    if (
        record.deployment_scope_digest != binding.deployment_scope_digest
        or record.principal_digest != binding.principal_digest
        or record.conversation_id != binding.conversation_id
        or record.purpose != binding.purpose
        or record.manifest_digest != binding.manifest_digest
    ):
        return ResultHandleGetResult(ResultHandleGetStatus.FOREIGN)
    key = await keys.key_for_version(record.key_version)
    if key is None:
        return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
    try:
        handle = _decrypt_handle(
            record.envelope,
            key=key,
            handle_ref=record.handle_ref,
            allowed_snapshot_fields=allowed_snapshot_fields,
        )
    except (InvalidTag, ValueError):
        return ResultHandleGetResult(ResultHandleGetStatus.UNAVAILABLE)
    return ResultHandleGetResult(ResultHandleGetStatus.BOUND, handle)


def _encrypt_handle(
    handle: ResultHandle,
    *,
    key: ResultHandleKey,
    handle_ref: str,
) -> dict[str, object]:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    associated = _associated_data(handle_ref, key.key_version)
    ciphertext = AESGCM(key.key).encrypt(
        nonce,
        encode_reasoning_record(handle).encode("utf-8"),
        associated,
    )
    return {
        "schema_version": _ENVELOPE_SCHEMA_VERSION,
        "algorithm": _ALGORITHM,
        "key_version": key.key_version,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def _decrypt_handle(
    envelope: Mapping[str, object],
    *,
    key: ResultHandleKey,
    handle_ref: str,
    allowed_snapshot_fields: Iterable[str],
) -> ResultHandle:
    if (
        envelope.get("schema_version") != _ENVELOPE_SCHEMA_VERSION
        or envelope.get("algorithm") != _ALGORITHM
        or envelope.get("key_version") != key.key_version
    ):
        raise ValueError("result handle envelope metadata mismatch")
    nonce = _decode_b64(envelope.get("nonce"), field="nonce")
    ciphertext = _decode_b64(envelope.get("ciphertext"), field="ciphertext")
    plaintext = AESGCM(key.key).decrypt(
        nonce,
        ciphertext,
        _associated_data(handle_ref, key.key_version),
    )
    return decode_reasoning_record(
        ResultHandle,
        plaintext,
        validation_context={"allowed_snapshot_fields": set(allowed_snapshot_fields)},
    )


def _associated_data(handle_ref: str, key_version: str) -> bytes:
    return f"fdai.result-handle\0{handle_ref}\0{key_version}".encode()


def _decode_key(value: str) -> bytes:
    stripped = value.strip()
    try:
        if len(stripped) == 64 and all(char in "0123456789abcdefABCDEF" for char in stripped):
            return bytes.fromhex(stripped)
        return base64.b64decode(stripped, validate=True)
    except ValueError as exc:
        raise ValueError("result handle key material is not valid hex or base64") from exc


def _decode_b64(value: object, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"result handle envelope {field} MUST be base64 text")
    return base64.b64decode(value, validate=True)


def _new_handle_ref() -> str:
    return secrets.token_urlsafe(_HANDLE_REF_BYTES)


def _validate_ref_times(issued_at: datetime, expires_at: datetime) -> None:
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("result handle issued_at MUST be timezone-aware")
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("result handle expires_at MUST be timezone-aware")
    if expires_at <= issued_at:
        raise ValueError("result handle expires_at MUST be after issued_at")


__all__ = [
    "InMemoryResultHandleStore",
    "ResultHandleBinding",
    "ResultHandleGetResult",
    "ResultHandleGetStatus",
    "ResultHandleKey",
    "ResultHandleKeyProvider",
    "ResultHandleStore",
    "SecretProviderResultHandleKeyProvider",
    "StaticResultHandleKeyProvider",
    "reauthorize_result_handle_rows",
    "rendered_order_digest",
]

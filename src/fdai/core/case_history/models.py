"""Canonical immutable case-history revisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import unquote

_MAX_SOURCE_BYTES = 16 * 1024
_MAX_ARTIFACT_BYTES = 1024 * 1024
_FORBIDDEN_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", value)
    for value in {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "bearer_token",
        "chain_of_thought",
        "client_secret",
        "connection_string",
        "credential",
        "credentials",
        "hidden_reasoning",
        "id_token",
        "passphrase",
        "password",
        "prompt",
        "proxy_authorization",
        "raw_cloud_payload",
        "raw_output",
        "raw_prompt",
        "refresh_token",
        "sas_token",
        "secret",
        "token",
        "tokens",
    }
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{16,}"),
    re.compile(
        r"(?i)(?:^|[?&;])(?:sig|accountkey|sharedaccesskey|sharedaccesssignature|"
        r"client[_-]?secret|password)=[^&;\s]+"
    ),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^:/\s]+:[^@\s/]+@"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
)


class CaseKind(StrEnum):
    PREDICTION = "prediction"
    INCIDENT = "incident"
    ACTION = "action"


@dataclass(frozen=True, slots=True)
class CaseSourceRecord:
    record_type: str
    record_id: str
    record_digest: str
    occurred_at: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.record_type or not self.record_id:
            raise ValueError("case source identity MUST be non-empty")
        _digest("source digest", self.record_digest)
        if self.occurred_at.tzinfo is None:
            raise ValueError("case source timestamp MUST be timezone-aware")
        normalized = {str(key): _freeze_value(value) for key, value in self.payload.items()}
        forbidden = _payload_keys(normalized).intersection(_FORBIDDEN_KEYS)
        if forbidden:
            raise ValueError(f"case source payload contains forbidden fields: {sorted(forbidden)}")
        if _contains_forbidden_value(normalized):
            raise ValueError("case source payload contains a secret-like value")
        encoded = _json_bytes(normalized)
        if len(encoded) > _MAX_SOURCE_BYTES:
            raise ValueError("case source payload exceeds its byte limit")
        object.__setattr__(self, "payload", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class CaseHistoryRevision:
    case_id: str
    revision: int
    kind: CaseKind
    correlation_id: str
    purpose: str
    access_scope_digest: str
    redaction_policy_version: str
    event_time_cutoff: datetime
    created_by_agent: str
    sealed_at: datetime
    parent_manifest_digest: str | None
    manifest_digest: str
    artifact_bytes: bytes
    sources: tuple[CaseSourceRecord, ...]


def build_case_history_revision(
    *,
    case_id: str,
    revision: int,
    kind: CaseKind,
    correlation_id: str,
    purpose: str,
    access_scope_digest: str,
    redaction_policy_version: str,
    event_time_cutoff: datetime,
    created_by_agent: str,
    sealed_at: datetime,
    parent_manifest_digest: str | None,
    sources: Sequence[CaseSourceRecord],
) -> CaseHistoryRevision:
    if not all((case_id, correlation_id, purpose, redaction_policy_version, created_by_agent)):
        raise ValueError("case revision identity fields MUST be non-empty")
    if revision < 1:
        raise ValueError("case revision MUST be positive")
    _digest("access scope digest", access_scope_digest)
    if parent_manifest_digest is not None:
        _digest("parent manifest digest", parent_manifest_digest)
    if event_time_cutoff.tzinfo is None or sealed_at.tzinfo is None:
        raise ValueError("case revision timestamps MUST be timezone-aware")
    if event_time_cutoff > sealed_at:
        raise ValueError("case event cutoff MUST NOT follow seal time")
    ordered = tuple(
        sorted(
            sources,
            key=lambda item: (item.occurred_at, item.record_type, item.record_id),
        )
    )
    if not ordered:
        raise ValueError("case revision MUST contain source evidence")
    identities = {(item.record_type, item.record_id) for item in ordered}
    if len(identities) != len(ordered):
        raise ValueError("case revision source identities MUST be unique")
    document = {
        "schema_version": "1.0.0",
        "case_id": case_id,
        "revision": revision,
        "kind": kind.value,
        "correlation_id": correlation_id,
        "purpose": purpose,
        "access_scope_digest": access_scope_digest,
        "redaction_policy_version": redaction_policy_version,
        "event_time_cutoff": event_time_cutoff.isoformat(),
        "created_by_agent": created_by_agent,
        "sealed_at": sealed_at.isoformat(),
        "parent_manifest_digest": parent_manifest_digest,
        "sources": [
            {
                "record_type": item.record_type,
                "record_id": item.record_id,
                "record_digest": item.record_digest,
                "occurred_at": item.occurred_at.isoformat(),
                "payload": item.payload,
            }
            for item in ordered
        ],
    }
    artifact_bytes = _json_bytes(document)
    if len(artifact_bytes) > _MAX_ARTIFACT_BYTES:
        raise ValueError("case history artifact exceeds its byte limit")
    manifest_digest = hashlib.sha256(artifact_bytes).hexdigest()
    return CaseHistoryRevision(
        case_id=case_id,
        revision=revision,
        kind=kind,
        correlation_id=correlation_id,
        purpose=purpose,
        access_scope_digest=access_scope_digest,
        redaction_policy_version=redaction_policy_version,
        event_time_cutoff=event_time_cutoff,
        created_by_agent=created_by_agent,
        sealed_at=sealed_at,
        parent_manifest_digest=parent_manifest_digest,
        manifest_digest=manifest_digest,
        artifact_bytes=artifact_bytes,
        sources=ordered,
    )


def _payload_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {_normalize_key(key) for key in value} | {
            nested for child in value.values() for nested in _payload_keys(child)
        }
    if isinstance(value, (list, tuple)):
        return {nested for child in value for nested in _payload_keys(child)}
    return set()


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _contains_forbidden_value(value: object) -> bool:
    if isinstance(value, str):
        decoded = unquote(value)
        return any(
            pattern.search(candidate) is not None
            for candidate in (value, decoded)
            for pattern in _FORBIDDEN_VALUE_PATTERNS
        )
    if isinstance(value, Mapping):
        return any(_contains_forbidden_value(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_value(child) for child in value)
    return False


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(child) for child in value)
    return value


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("case history content MUST be canonical JSON data") from exc


def _json_default(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported case history value: {type(value).__name__}")


def _digest(name: str, value: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"case {name} MUST be lowercase SHA-256")


__all__ = [
    "CaseHistoryRevision",
    "CaseKind",
    "CaseSourceRecord",
    "build_case_history_revision",
]

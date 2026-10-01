"""Versioned contracts for ontology reasoning result handles and continuations."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeVar

from pydantic import Field, ValidationInfo, field_validator, model_validator

from fdai_service_contracts.compatibility import CompatibilityError, SemVer
from fdai_service_contracts.ontology_query import QueryContract, canonical_json

SchemaVersion = Literal["1.0", "1.1"]

CURRENT_REASONING_HANDLE_SCHEMA_VERSION: Literal["1.1"] = "1.1"
PREVIOUS_REASONING_HANDLE_SCHEMA_VERSION: Literal["1.0"] = "1.0"
SUPPORTED_REASONING_HANDLE_SCHEMA_VERSIONS = (
    PREVIOUS_REASONING_HANDLE_SCHEMA_VERSION,
    CURRENT_REASONING_HANDLE_SCHEMA_VERSION,
)
SUPPORTED_RESULT_HANDLE_KEY_VERSIONS = ("result-handle-key-v1",)
MAX_RESULT_HANDLE_ROWS = 1_000

_CURRENT_MAJOR = 1
_CURRENT_MINOR = 1
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_MACHINE_TOKEN_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"
_OPAQUE_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_UUID_LIKE_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)

Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
MachineToken = Annotated[str, Field(pattern=_MACHINE_TOKEN_PATTERN)]
BoundedText = Annotated[str, Field(min_length=1, max_length=256)]
TRecord = TypeVar("TRecord", bound=QueryContract)


class ReasoningHandleErrorCode(StrEnum):
    """Stable fail-closed codes for rollout-safe stored-record decoding."""

    INVALID_RECORD = "invalid_record"
    INCOMPATIBLE_READER_VERSIONS = "incompatible_reader_versions"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNSUPPORTED_KEY_VERSION = "unsupported_key_version"


class ReasoningHandleCodecError(CompatibilityError):
    """Typed compatibility failure for reasoning handle persisted records."""

    def __init__(self, code: ReasoningHandleErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class LinkDirection(StrEnum):
    """Traversal direction for a typed path pushdown request."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class EvidenceCompleteness(StrEnum):
    """Completeness claim carried by one evidence manifest."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    PARTIAL = "partial"


class SortDirection(StrEnum):
    """Stable row ordering direction."""

    ASC = "asc"
    DESC = "desc"


class TypedRowKey(QueryContract):
    """Digest-only typed key for one rendered ontology row."""

    row_type: MachineToken
    row_digest: Digest


class SortTerm(QueryContract):
    """One deterministic rendered-order term."""

    field_name: MachineToken
    direction: SortDirection


class PageDescriptor(QueryContract):
    """Bounded page metadata for the rendered result."""

    page_number: Annotated[int, Field(strict=True, ge=1)]
    page_size: Annotated[int, Field(strict=True, ge=1, le=MAX_RESULT_HANDLE_ROWS)]


class SnapshotCell(QueryContract):
    """One retained already-rendered cell eligible for snapshot-reference answers."""

    field_name: MachineToken
    value_digest: Digest


class SnapshotRow(QueryContract):
    """Allowlisted snapshot cells for one row key."""

    row_key: TypedRowKey
    cells: Annotated[tuple[SnapshotCell, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def _cells_are_unique(self) -> SnapshotRow:
        field_names = tuple(cell.field_name for cell in self.cells)
        if len(field_names) != len(set(field_names)):
            raise ValueError("snapshot cell field names MUST be unique per row")
        return self


class ResultHandleRef(QueryContract):
    """Opaque reference that Operator may persist with a durable turn."""

    schema_version: SchemaVersion = CURRENT_REASONING_HANDLE_SCHEMA_VERSION
    handle_ref: str
    key_version: MachineToken
    issued_at: datetime
    expires_at: datetime

    @field_validator("handle_ref")
    @classmethod
    def _opaque_handle_ref(cls, value: str) -> str:
        if _OPAQUE_REF_PATTERN.fullmatch(value) is None or _UUID_LIKE_PATTERN.fullmatch(value):
            raise ValueError("handle_ref MUST be a random opaque token")
        return value

    @model_validator(mode="after")
    def _times_are_usable(self) -> ResultHandleRef:
        _require_aware("issued_at", self.issued_at)
        _require_aware("expires_at", self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at MUST be after issued_at")
        return self


class ResultHandle(QueryContract):
    """Core-only record for the exact rows shown by one answer."""

    schema_version: SchemaVersion = CURRENT_REASONING_HANDLE_SCHEMA_VERSION
    deployment_scope_digest: Digest
    principal_digest: Digest
    conversation_id: MachineToken
    purpose: MachineToken
    manifest_digest: Digest
    rendered_order_digest: Digest
    row_keys: Annotated[tuple[TypedRowKey, ...], Field(max_length=MAX_RESULT_HANDLE_ROWS)] = ()
    sort: tuple[SortTerm, ...] = ()
    page: PageDescriptor
    truncated: bool
    snapshot_cells: tuple[SnapshotRow, ...] = ()

    @model_validator(mode="after")
    def _rows_and_snapshot_are_bounded(self, info: ValidationInfo) -> ResultHandle:
        row_tokens = tuple(row.model_dump(mode="json") for row in self.row_keys)
        row_identities = tuple(canonical_json(row) for row in row_tokens)
        if len(row_identities) != len(set(row_identities)):
            raise ValueError("result handle row_keys MUST be unique")

        snapshot_row_identities = tuple(
            canonical_json(row.row_key.model_dump(mode="json")) for row in self.snapshot_cells
        )
        if len(snapshot_row_identities) != len(set(snapshot_row_identities)):
            raise ValueError("snapshot rows MUST be unique")
        unknown_rows = set(snapshot_row_identities) - set(row_identities)
        if unknown_rows:
            raise ValueError("snapshot rows MUST reference result handle row_keys")

        if self.snapshot_cells:
            allowed = _snapshot_allowlist(info)
            seen_fields = {
                cell.field_name
                for snapshot_row in self.snapshot_cells
                for cell in snapshot_row.cells
            }
            rejected = seen_fields - allowed
            if rejected:
                raise ValueError("snapshot cells contain fields outside the validation allowlist")
        return self


class EvidenceReference(QueryContract):
    """One cited evidence reference and the receipt digest that made it admissible."""

    evidence_ref: BoundedText
    receipt_digest: Digest


class EvidenceManifest(QueryContract):
    """Core-only manifest for cited evidence and row population accounting."""

    schema_version: SchemaVersion = CURRENT_REASONING_HANDLE_SCHEMA_VERSION
    cited_evidence: tuple[EvidenceReference, ...] = ()
    completeness: EvidenceCompleteness
    rows_digest: Digest

    @model_validator(mode="after")
    def _references_are_unique(self) -> EvidenceManifest:
        refs = tuple(reference.evidence_ref for reference in self.cited_evidence)
        if len(refs) != len(set(refs)):
            raise ValueError("evidence references MUST be unique")
        return self


class AggregatePushdown(QueryContract):
    """Exact aggregate pushdown without free query text."""

    kind: Literal["aggregate"] = "aggregate"
    operation: Literal["count"] = "count"
    group_by: Annotated[tuple[MachineToken, ...], Field(max_length=16)] = ()
    lineage_root: TypedRowKey | None = None

    @model_validator(mode="after")
    def _grouping_is_unique(self) -> AggregatePushdown:
        if len(self.group_by) != len(set(self.group_by)):
            raise ValueError("aggregate pushdown group_by fields MUST be unique")
        return self


class TypedPathPushdown(QueryContract):
    """Bounded typed-path pushdown over reviewed LinkTypes."""

    kind: Literal["typed_path"] = "typed_path"
    link_types: Annotated[tuple[MachineToken, ...], Field(min_length=1, max_length=32)]
    direction: LinkDirection
    depth_bound: Annotated[int, Field(strict=True, ge=1, le=8)]

    @model_validator(mode="after")
    def _link_types_are_unique(self) -> TypedPathPushdown:
        if len(self.link_types) != len(set(self.link_types)):
            raise ValueError("typed path LinkTypes MUST be unique")
        return self


PushdownRequest = Annotated[AggregatePushdown | TypedPathPushdown, Field(discriminator="kind")]


class OrderingTerm(QueryContract):
    """Continuation ordering term."""

    field_name: MachineToken
    direction: SortDirection


class KeysetCursor(QueryContract):
    """Digest-pinned keyset cursor for the next row page."""

    cursor_digest: Digest
    last_effective_at: datetime | None = None
    last_subject_digest: Digest | None = None

    @model_validator(mode="after")
    def _cursor_times_are_aware(self) -> KeysetCursor:
        if self.last_effective_at is not None:
            _require_aware("last_effective_at", self.last_effective_at)
        return self


class NextBatchDescriptor(QueryContract):
    """Descriptor for the next successive relation-plan batch."""

    batch_id: MachineToken
    plan_digest: Digest
    link_types: Annotated[tuple[MachineToken, ...], Field(min_length=1, max_length=32)]
    depth_bound: Annotated[int, Field(strict=True, ge=1, le=8)]

    @model_validator(mode="after")
    def _link_types_are_unique(self) -> NextBatchDescriptor:
        if len(self.link_types) != len(set(self.link_types)):
            raise ValueError("next batch LinkTypes MUST be unique")
        return self


class QueryContinuation(QueryContract):
    """Core-only pinned continuation for row pages or successive relation batches."""

    schema_version: SchemaVersion = CURRENT_REASONING_HANDLE_SCHEMA_VERSION
    deployment_scope_digest: Digest
    principal_digest: Digest
    conversation_id: MachineToken
    purpose: MachineToken
    admitted_goal_digest: Digest
    plan_digest: Digest
    manifest_digest: Digest
    query_version_digest: Digest
    window_start: datetime
    window_end: datetime
    cutoff: datetime
    ordering: Annotated[tuple[OrderingTerm, ...], Field(min_length=1, max_length=8)]
    keyset_cursor: KeysetCursor
    page_size: Annotated[int, Field(strict=True, ge=1, le=MAX_RESULT_HANDLE_ROWS)]
    expires_at: datetime
    remaining_rows: Annotated[int, Field(strict=True, ge=0)] | None = None
    remaining_batches: Annotated[int, Field(strict=True, ge=0)] | None = None
    next_batch: NextBatchDescriptor | None = None
    listed_endpoint_digest: Digest | None = None

    @model_validator(mode="after")
    def _continuation_is_pinned_and_accounted(self) -> QueryContinuation:
        for name, value in (
            ("window_start", self.window_start),
            ("window_end", self.window_end),
            ("cutoff", self.cutoff),
            ("expires_at", self.expires_at),
        ):
            _require_aware(name, value)
        if self.window_end <= self.window_start:
            raise ValueError("window_end MUST be after window_start")
        if self.expires_at <= self.cutoff:
            raise ValueError("expires_at MUST be after cutoff")

        has_row_account = self.remaining_rows is not None
        has_batch_account = (
            self.remaining_batches is not None
            or self.next_batch is not None
            or self.listed_endpoint_digest is not None
        )
        if has_row_account == has_batch_account:
            raise ValueError("query continuation MUST carry exactly one progress account")
        if has_batch_account and not (
            self.remaining_batches is not None
            and self.next_batch is not None
            and self.listed_endpoint_digest is not None
        ):
            raise ValueError(
                "batch continuation requires remaining_batches, next_batch, "
                "and listed_endpoint_digest"
            )
        return self


def encode_reasoning_record(record: QueryContract) -> str:
    """Return canonical JSON for one reasoning handle contract record."""

    return canonical_json(record.model_dump(mode="json"))


def decode_reasoning_record(
    record_type: type[TRecord],
    payload: str | bytes | Mapping[str, Any],
    *,
    key_versions: Iterable[str] = SUPPORTED_RESULT_HANDLE_KEY_VERSIONS,
    validation_context: Mapping[str, object] | None = None,
) -> TRecord:
    """Decode a stored record with N/N-1 schema and key-version fail-closed checks."""

    raw = _load_payload(payload)
    _ensure_decodable_schema_version(raw.get("schema_version"))
    if "key_version" in raw:
        _ensure_supported_key_version(raw["key_version"], key_versions)
    try:
        return record_type.model_validate(raw, context=validation_context)
    except ValueError as exc:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.INVALID_RECORD,
            "reasoning handle record failed validation",
        ) from exc


def negotiate_write_version(reader_versions: Iterable[Iterable[str]]) -> str:
    """Return the highest schema version supported by every running reader."""

    intersections: set[str] | None = None
    readers = 0
    for versions in reader_versions:
        readers += 1
        supported = {version for version in versions if _is_known_write_version(version)}
        intersections = supported if intersections is None else intersections & supported
    if readers == 0 or not intersections:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.INCOMPATIBLE_READER_VERSIONS,
            "no common reasoning handle schema version across readers",
        )
    return max(intersections, key=_schema_version_sort_key)


def _load_payload(payload: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    try:
        if isinstance(payload, bytes):
            decoded = payload.decode("utf-8")
        else:
            decoded = payload
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.INVALID_RECORD,
            "reasoning handle record is not valid canonical JSON",
        ) from exc
    if not isinstance(value, dict):
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.INVALID_RECORD,
            "reasoning handle record root must be an object",
        )
    if canonical_json(value) != decoded:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.INVALID_RECORD,
            "reasoning handle record must be canonical JSON",
        )
    return value


def _ensure_decodable_schema_version(value: object) -> None:
    if not isinstance(value, str):
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            "schema_version must be a major.minor string",
        )
    try:
        version = _parse_schema_version(value)
    except CompatibilityError as exc:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            "schema_version must be a supported major.minor version",
        ) from exc
    if version.major != _CURRENT_MAJOR or version.minor not in {_CURRENT_MINOR - 1, _CURRENT_MINOR}:
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            "reasoning handle schema_version is outside the N/N-1 window",
        )


def _ensure_supported_key_version(value: object, key_versions: Iterable[str]) -> None:
    if not isinstance(value, str) or value not in set(key_versions):
        raise ReasoningHandleCodecError(
            ReasoningHandleErrorCode.UNSUPPORTED_KEY_VERSION,
            "reasoning handle key_version is not supported",
        )


def _is_known_write_version(value: str) -> bool:
    try:
        version = _parse_schema_version(value)
    except CompatibilityError:
        return False
    return (
        version.major == _CURRENT_MAJOR
        and version.minor in {_CURRENT_MINOR - 1, _CURRENT_MINOR}
        and value in SUPPORTED_REASONING_HANDLE_SCHEMA_VERSIONS
    )


def _parse_schema_version(value: str) -> SemVer:
    if re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)", value) is None:
        raise CompatibilityError(f"invalid reasoning handle schema version: {value!r}")
    return SemVer.parse(f"{value}.0")


def _schema_version_sort_key(value: str) -> tuple[int, int]:
    version = _parse_schema_version(value)
    return (version.major, version.minor)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _snapshot_allowlist(info: ValidationInfo) -> set[str]:
    context = info.context
    if not isinstance(context, Mapping):
        raise ValueError("snapshot cell validation requires an allowed_snapshot_fields context")
    fields = context.get("allowed_snapshot_fields")
    if not isinstance(fields, Iterable) or isinstance(fields, (str, bytes)):
        raise ValueError("allowed_snapshot_fields MUST be a set of field-name strings")
    allowed = set(fields)
    if not all(isinstance(field, str) for field in allowed):
        raise ValueError("allowed_snapshot_fields MUST contain only strings")
    return allowed


__all__ = [
    "AggregatePushdown",
    "CURRENT_REASONING_HANDLE_SCHEMA_VERSION",
    "EvidenceCompleteness",
    "EvidenceManifest",
    "EvidenceReference",
    "KeysetCursor",
    "LinkDirection",
    "MAX_RESULT_HANDLE_ROWS",
    "NextBatchDescriptor",
    "OrderingTerm",
    "PREVIOUS_REASONING_HANDLE_SCHEMA_VERSION",
    "PageDescriptor",
    "PushdownRequest",
    "QueryContinuation",
    "ReasoningHandleCodecError",
    "ReasoningHandleErrorCode",
    "ResultHandle",
    "ResultHandleRef",
    "SUPPORTED_REASONING_HANDLE_SCHEMA_VERSIONS",
    "SUPPORTED_RESULT_HANDLE_KEY_VERSIONS",
    "SnapshotCell",
    "SnapshotRow",
    "SortDirection",
    "SortTerm",
    "TypedPathPushdown",
    "TypedRowKey",
    "decode_reasoning_record",
    "encode_reasoning_record",
    "negotiate_write_version",
]

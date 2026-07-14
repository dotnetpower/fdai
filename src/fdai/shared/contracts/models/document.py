"""Immutable contracts for document upload, processing, and deletion."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from ._base import SemVer, _Base


class DocumentState(StrEnum):
    CREATED = "created"
    UPLOADING = "uploading"
    RECEIVED = "received"
    QUARANTINED = "quarantined"
    SCANNING = "scanning"
    PROTECTION_CHECK = "protection_check"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    HELD = "held"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class ProtectionState(StrEnum):
    NONE = "none"
    LABELED_UNENCRYPTED = "labeled_unencrypted"
    RIGHTS_MANAGED_ACCESSIBLE = "rights_managed_accessible"
    RIGHTS_MANAGED_ACCESS_DENIED = "rights_managed_access_denied"
    PASSWORD_ENCRYPTED = "password_encrypted"  # noqa: S105 - protection-state token
    UNSUPPORTED_PROTECTION = "unsupported_protection"
    UNKNOWN = "unknown"


class SourceStorageMode(StrEnum):
    MANAGED_COPY = "managed_copy"
    LINKED_SOURCE = "linked_source"
    EPHEMERAL_PROCESSING = "ephemeral_processing"
    METADATA_ONLY = "metadata_only"


class MalwareVerdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"


class DocumentPurpose(StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    MANUAL_DISTILLATION = "manual_distillation"


class AccessDescriptor(_Base):
    reference: Annotated[str, Field(min_length=1, max_length=512)]
    collection_id: Annotated[str, Field(min_length=1, max_length=256)]
    reader_groups: tuple[str, ...] = ()


class RetentionPolicy(_Base):
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    source_expires_at: datetime | None = None
    derived_expires_at: datetime | None = None
    legal_hold: bool = False


class UploadSession(_Base):
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    actor_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_name: Annotated[str, Field(min_length=1, max_length=512)]
    collection_id: Annotated[str, Field(min_length=1, max_length=256)]
    object_key: Annotated[str, Field(min_length=1, max_length=512)]
    media_type_hint: Annotated[str, Field(min_length=1, max_length=256)]
    expected_size: Annotated[int, Field(ge=0)]
    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    state: DocumentState
    storage_mode: SourceStorageMode
    purposes: tuple[DocumentPurpose, ...]
    access: AccessDescriptor
    retention: RetentionPolicy
    created_at: datetime
    expires_at: datetime
    supersedes_version_id: UUID | None = None
    failure_code: str | None = None


class DocumentVersion(_Base):
    document_id: UUID
    version_id: UUID
    upload_id: UUID
    source_name: str
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(ge=0)]
    media_type: str
    observed_format: str | None = None
    state: DocumentState
    protection_state: ProtectionState = ProtectionState.UNKNOWN
    classification: str = "unclassified"
    sensitivity_label: str | None = None
    access: AccessDescriptor
    retention: RetentionPolicy
    purposes: tuple[DocumentPurpose, ...]
    uploader_id: str
    created_at: datetime
    updated_at: datetime
    active: bool = False
    available: bool = False
    supersedes_version_id: UUID | None = None
    failure_code: str | None = None
    warnings: tuple[str, ...] = ()


class StructuralUnit(_Base):
    unit_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["text", "paragraph", "table", "slide", "sheet", "page"]
    locator: Annotated[str, Field(min_length=1, max_length=256)]
    text: str


class DocumentEnvelope(_Base):
    schema_version: SemVer = "1.0.0"
    document_id: UUID
    version_id: UUID
    source_sha256: str
    media_type: str
    observed_format: str
    size_bytes: int
    collection_id: str
    purposes: tuple[DocumentPurpose, ...]
    protection_state: ProtectionState
    access_descriptor_ref: str
    units: tuple[StructuralUnit, ...]
    extractor_name: str
    extractor_version: str
    warnings: tuple[str, ...] = ()


class IngestionCapabilities(_Base):
    supported_formats: tuple[str, ...]
    storage_modes: tuple[SourceStorageMode, ...]
    max_file_size: int
    max_batch_count: int
    archives_enabled: bool
    policy_versions: tuple[str, ...]
    direct_upload: bool = False


__all__ = [
    "AccessDescriptor",
    "DocumentEnvelope",
    "DocumentPurpose",
    "DocumentState",
    "DocumentVersion",
    "IngestionCapabilities",
    "MalwareVerdict",
    "ProtectionState",
    "RetentionPolicy",
    "SourceStorageMode",
    "StructuralUnit",
    "UploadSession",
]

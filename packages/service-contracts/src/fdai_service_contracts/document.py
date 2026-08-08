"""Implementation-free contracts for document upload and processing services."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentContract(BaseModel):
    """Immutable validated base for cross-service document records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


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
    PASSWORD_ENCRYPTED = "password_encrypted"  # noqa: S105 - contract token
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


class ExtractionUnavailableReason(StrEnum):
    INPUT_BUDGET = "extraction_input_budget_exceeded"
    PACKAGE_MEMBER_BUDGET = "extraction_package_member_budget_exceeded"
    PACKAGE_EXPANSION_BUDGET = "extraction_package_expansion_budget_exceeded"
    XML_MEMBER_BUDGET = "extraction_xml_member_budget_exceeded"
    XML_DEPTH_BUDGET = "extraction_xml_depth_budget_exceeded"
    XML_NODE_BUDGET = "extraction_xml_node_budget_exceeded"
    TEXT_BUDGET = "extraction_text_budget_exceeded"
    UNIT_BUDGET = "extraction_unit_budget_exceeded"
    UNSAFE_PACKAGE = "extraction_unsafe_package"
    MALFORMED_PACKAGE = "extraction_malformed_package"
    UNSUPPORTED_FORMAT = "extraction_unsupported_format"


class DocumentPurpose(StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    MANUAL_DISTILLATION = "manual_distillation"
    HANDOVER_BOOTSTRAP = "handover_bootstrap"
    HANDOVER_EVIDENCE = "handover_evidence"


class DocumentWorkerStage(StrEnum):
    RECEIVED_REPLAY = "received_replay"
    INSPECTION = "inspection"
    PROTECTION_REPLAY = "protection_replay"
    SAFETY_DECISION = "safety_decision"
    INDEXING = "indexing"
    DELETION = "deletion"


class DocumentWorkerClaimStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    RELEASED = "released"


class AccessDescriptor(DocumentContract):
    reference: Annotated[str, Field(min_length=1, max_length=512)]
    collection_id: Annotated[str, Field(min_length=1, max_length=256)]
    reader_groups: tuple[str, ...] = ()


class RetentionPolicy(DocumentContract):
    policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    source_expires_at: datetime | None = None
    derived_expires_at: datetime | None = None
    legal_hold: bool = False


class UploadSession(DocumentContract):
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
    revision: Annotated[int, Field(ge=1)] = 1


class DocumentWorkerClaim(DocumentContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    upload_id: UUID
    stage: DocumentWorkerStage
    owner: Annotated[str, Field(min_length=1, max_length=256)]
    attempt_id: UUID
    revision: Annotated[int, Field(ge=1)]
    status: DocumentWorkerClaimStatus
    claimed_at: datetime
    lease_expires_at: datetime
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> DocumentWorkerClaim:
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("document worker claim lease MUST expire after it is claimed")
        if (self.status is DocumentWorkerClaimStatus.ACTIVE) == (self.finished_at is not None):
            raise ValueError("only terminal document worker claims MUST have finished_at")
        return self


class DocumentWorkerAuditEvent(DocumentContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    producer_principal: Literal["Saga"]
    kind: Literal["document_ingestion"]
    audited_topic: Literal["object.verdict", "object.approval"]
    correlation_id: Annotated[str, Field(max_length=512)] = ""
    idempotency_key: Annotated[str, Field(max_length=512)] = ""
    stage: Literal["received", "protection_check"]
    decision: Annotated[str, Field(min_length=1, max_length=64)]
    reason: Annotated[str, Field(max_length=256)] = ""
    document_id: Annotated[str, Field(max_length=128)] = ""
    upload_id: UUID
    initiator_principal: Annotated[str, Field(max_length=256)] = ""
    approvers: tuple[str, ...] = ()


class DocumentWorkerIndexCommand(DocumentContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    producer_principal: Literal["Muninn"]
    kind: Literal["document_ingestion"]
    stage: Literal["indexing"]
    command: Literal["index"]
    correlation_id: Annotated[str, Field(max_length=512)] = ""
    idempotency_key: Annotated[str, Field(max_length=512)] = ""
    resource_id: Annotated[str, Field(max_length=128)] = ""
    document_id: Annotated[str, Field(max_length=128)] = ""
    upload_id: UUID


class DocumentDeletionRequest(DocumentContract):
    """Immutable API request for worker-owned document artifact deletion."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: UUID
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    document_id: UUID
    version_id: UUID
    upload_id: UUID
    requested_by: Annotated[str, Field(min_length=1, max_length=256)]
    expected_upload_revision: Annotated[int, Field(ge=1)]
    expected_version_revision: Annotated[int, Field(ge=1)]
    requested_at: datetime


class DocumentLifecycleEvent(DocumentContract):
    """One durable lifecycle fact published only from a service outbox."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: UUID
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    topic: Annotated[str, Field(min_length=1, max_length=256)]
    key: Annotated[str, Field(min_length=1, max_length=512)]
    payload: dict[str, object]
    created_at: datetime


class DocumentVersion(DocumentContract):
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
    revision: Annotated[int, Field(ge=1)] = 1


class StructuralUnit(DocumentContract):
    unit_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["text", "paragraph", "table", "slide", "sheet", "page"]
    locator: Annotated[str, Field(min_length=1, max_length=256)]
    text: str
    table_cell_role: Literal["header", "body"] | None = None
    heading_level: Annotated[int, Field(ge=1, le=9)] | None = None
    parent_locator: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    section_name: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class DocumentEnvelope(DocumentContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
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
    goal_ref: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    warnings: tuple[str, ...] = ()


class IngestionCapabilities(DocumentContract):
    supported_formats: tuple[str, ...]
    storage_modes: tuple[SourceStorageMode, ...]
    max_file_size: int
    max_batch_count: int
    archives_enabled: bool
    policy_versions: tuple[str, ...]
    direct_upload: bool = False


class EventEnvelope(DocumentContract):
    """Transport-neutral event record consumed by the ingestion worker."""

    topic: str
    key: str
    payload: dict[str, object]
    headers: dict[str, str] = {}
    offset: int | None = None

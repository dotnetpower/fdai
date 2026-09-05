"""Implementation-free contracts for document upload and processing services."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class DocumentDisposition(StrEnum):
    """Governance purpose assigned to a document version."""

    SESSION_EPHEMERAL = "session_ephemeral"
    WORKSPACE_DRAFT = "workspace_draft"
    GOVERNED_KNOWLEDGE = "governed_knowledge"
    REGULATED_RECORD = "regulated_record"


class DocumentScopeKind(StrEnum):
    """Authorization scope that owns a document version."""

    CONVERSATION = "conversation"
    WORKSPACE = "workspace"
    COLLECTION = "collection"
    REGULATED = "regulated"


class DocumentIndexState(StrEnum):
    """Independent lifecycle state of a document's search index."""

    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    BUILDING = "building"
    ACTIVE = "active"
    TOMBSTONED = "tombstoned"
    PURGED = "purged"
    FAILED = "failed"


class DocumentRetentionState(StrEnum):
    """Independent lifecycle state of retained document material."""

    LIVE = "live"
    EXPIRING = "expiring"
    HELD = "held"
    TOMBSTONED = "tombstoned"
    PURGE_PENDING = "purge_pending"
    PURGED = "purged"


class DocumentArtifactKind(StrEnum):
    """Material kinds tracked in a document artifact graph."""

    SOURCE = "source"
    NATIVE_TEXT = "native_text"
    PAGE_RASTER = "page_raster"
    EMBEDDED_IMAGE = "embedded_image"
    OCR_TEXT = "ocr_text"
    THUMBNAIL = "thumbnail"
    NORMALIZED_ENVELOPE = "normalized_envelope"
    CHUNK = "chunk"
    EMBEDDING = "embedding"


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
    OCR_UNAVAILABLE = "extraction_ocr_unavailable"
    NO_EXTRACTABLE_CONTENT = "extraction_no_extractable_content"


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


class ArtifactManifestEntry(DocumentContract):
    """One immutable, content-addressed node in a document artifact graph."""

    artifact_id: Annotated[str, Field(min_length=1, max_length=256)]
    parent_artifact_id: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    kind: DocumentArtifactKind
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    locator: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    media_type: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    size_bytes: Annotated[int, Field(ge=0)] | None = None
    retained: bool
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("artifact expiry MUST include a timezone")
        return value

    @model_validator(mode="after")
    def _validate_retained_integrity(self) -> ArtifactManifestEntry:
        if self.retained and (self.content_sha256 is None or self.size_bytes is None):
            raise ValueError("retained artifact MUST include content digest and size")
        return self


class DocumentArtifactManifest(DocumentContract):
    """Bind a document version to its source and complete derived-artifact lineage."""

    document_id: UUID
    version_id: UUID
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    access: AccessDescriptor
    retention: RetentionPolicy
    disposition: DocumentDisposition = DocumentDisposition.GOVERNED_KNOWLEDGE
    scope_kind: DocumentScopeKind | None = None
    scope_ref: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    entries: Annotated[tuple[ArtifactManifestEntry, ...], Field(min_length=1)]
    extractor_name: Annotated[str, Field(min_length=1, max_length=256)]
    extractor_version: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_manifest(self) -> DocumentArtifactManifest:
        if self.created_at.utcoffset() is None or self.updated_at.utcoffset() is None:
            raise ValueError("artifact manifest timestamps MUST include a timezone")
        if self.updated_at < self.created_at:
            raise ValueError("artifact manifest updated_at MUST NOT precede created_at")
        scope_kind, scope_ref = _resolve_document_scope(
            disposition=self.disposition,
            scope_kind=self.scope_kind,
            scope_ref=self.scope_ref,
            collection_id=self.access.collection_id,
        )
        object.__setattr__(self, "scope_kind", scope_kind)
        object.__setattr__(self, "scope_ref", scope_ref)

        entries_by_id = {entry.artifact_id: entry for entry in self.entries}
        if len(entries_by_id) != len(self.entries):
            raise ValueError("artifact manifest artifact_id values MUST be unique")

        source_entries = [
            entry for entry in self.entries if entry.kind is DocumentArtifactKind.SOURCE
        ]
        if len(source_entries) != 1:
            raise ValueError("artifact manifest MUST contain exactly one source artifact")
        source = source_entries[0]
        if source.parent_artifact_id is not None:
            raise ValueError("artifact manifest source artifact MUST NOT have a parent")
        if source.content_sha256 != self.source_sha256:
            raise ValueError("artifact manifest source hash MUST match source_sha256")

        for entry in self.entries:
            parent_id = entry.parent_artifact_id
            if entry.kind is not DocumentArtifactKind.SOURCE and parent_id is None:
                raise ValueError("artifact manifest derivative MUST identify its parent")
            if parent_id is not None and parent_id not in entries_by_id:
                raise ValueError("artifact manifest child parent MUST exist")

        for entry in self.entries:
            parent_id = entry.parent_artifact_id
            seen = {entry.artifact_id}
            while parent_id is not None:
                if parent_id in seen:
                    raise ValueError("artifact manifest lineage MUST NOT contain a cycle")
                seen.add(parent_id)
                parent_id = entries_by_id[parent_id].parent_artifact_id

            if (
                entry.kind is DocumentArtifactKind.SOURCE
                and entry.retained
                and self.retention.source_expires_at is not None
            ):
                if entry.expires_at is None:
                    raise ValueError("retained source MUST expire by the governed source expiry")
                if entry.expires_at > self.retention.source_expires_at:
                    raise ValueError(
                        "retained source MUST NOT expire after the governed source expiry"
                    )
            if (
                entry.kind is not DocumentArtifactKind.SOURCE
                and entry.retained
                and self.retention.derived_expires_at is not None
            ):
                if entry.expires_at is None:
                    raise ValueError(
                        "retained derivative MUST expire by the governed derived expiry"
                    )
                if entry.expires_at > self.retention.derived_expires_at:
                    raise ValueError(
                        "retained derivative MUST NOT expire after the governed derived expiry"
                    )
        return self


class DocumentPurgeVerificationReceipt(DocumentContract):
    """Independently report whether every owned document residue is absent."""

    document_id: UUID
    version_id: UUID
    live_index_rows: Annotated[int, Field(ge=0)]
    derivative_objects: Annotated[int, Field(ge=0)]
    source_objects: Annotated[int, Field(ge=0)]
    cache_entries: Annotated[int, Field(ge=0)]
    legal_hold_blocked: bool
    backup_blocked: bool
    producer_blocked: bool = False
    verified_at: datetime
    verified: bool | None = None

    @field_validator("verified_at")
    @classmethod
    def _validate_verified_at(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("purge verification timestamp MUST include a timezone")
        return value

    @model_validator(mode="after")
    def _validate_verified(self) -> DocumentPurgeVerificationReceipt:
        expected = (
            self.live_index_rows == 0
            and self.derivative_objects == 0
            and self.source_objects == 0
            and self.cache_entries == 0
            and not self.legal_hold_blocked
            and not self.backup_blocked
            and not self.producer_blocked
        )
        if self.verified is not None and self.verified is not expected:
            raise ValueError("purge verification result MUST match residue and blocker fields")
        object.__setattr__(self, "verified", expected)
        return self


def _resolve_document_scope(
    *,
    disposition: DocumentDisposition,
    scope_kind: DocumentScopeKind | None,
    scope_ref: str | None,
    collection_id: str,
) -> tuple[DocumentScopeKind | None, str | None]:
    if disposition is DocumentDisposition.GOVERNED_KNOWLEDGE:
        scope_kind = scope_kind or DocumentScopeKind.COLLECTION
        if scope_kind is not DocumentScopeKind.COLLECTION:
            raise ValueError("governed knowledge MUST use collection scope")
        scope_ref = scope_ref or collection_id
        if scope_ref != collection_id:
            raise ValueError("governed knowledge scope MUST match its collection")
    else:
        expected_scope = {
            DocumentDisposition.SESSION_EPHEMERAL: DocumentScopeKind.CONVERSATION,
            DocumentDisposition.WORKSPACE_DRAFT: DocumentScopeKind.WORKSPACE,
            DocumentDisposition.REGULATED_RECORD: DocumentScopeKind.REGULATED,
        }[disposition]
        if scope_kind is not expected_scope or scope_ref is None:
            raise ValueError(
                f"{disposition.value} documents MUST identify a {expected_scope.value} scope"
            )

    if (scope_kind is None) != (scope_ref is None):
        raise ValueError("document scope kind and reference MUST be provided together")
    return scope_kind, scope_ref


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
    disposition: DocumentDisposition = DocumentDisposition.GOVERNED_KNOWLEDGE
    index_state: DocumentIndexState = DocumentIndexState.NOT_REQUESTED
    retention_state: DocumentRetentionState = DocumentRetentionState.LIVE
    scope_kind: DocumentScopeKind | None = None
    scope_ref: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    supersedes_version_id: UUID | None = None
    failure_code: str | None = None
    revision: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def _validate_scope(self) -> UploadSession:
        scope_kind, scope_ref = _resolve_document_scope(
            disposition=self.disposition,
            scope_kind=self.scope_kind,
            scope_ref=self.scope_ref,
            collection_id=self.collection_id,
        )
        object.__setattr__(self, "scope_kind", scope_kind)
        object.__setattr__(self, "scope_ref", scope_ref)
        return self


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
    protection_provider_ref: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    protection_policy_revision: Annotated[int, Field(ge=0)] | None = None
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
    disposition: DocumentDisposition = DocumentDisposition.GOVERNED_KNOWLEDGE
    index_state: DocumentIndexState = DocumentIndexState.NOT_REQUESTED
    retention_state: DocumentRetentionState = DocumentRetentionState.LIVE
    scope_kind: DocumentScopeKind | None = None
    scope_ref: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    supersedes_version_id: UUID | None = None
    promoted_from_version_id: UUID | None = None
    failure_code: str | None = None
    warnings: tuple[str, ...] = ()
    revision: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def _validate_scope(self) -> DocumentVersion:
        scope_kind, scope_ref = _resolve_document_scope(
            disposition=self.disposition,
            scope_kind=self.scope_kind,
            scope_ref=self.scope_ref,
            collection_id=self.access.collection_id,
        )
        object.__setattr__(self, "scope_kind", scope_kind)
        object.__setattr__(self, "scope_ref", scope_ref)
        if self.promoted_from_version_id == self.version_id:
            raise ValueError("promoted document version MUST NOT reference itself")
        return self

    @model_validator(mode="after")
    def _validate_purged_availability(self) -> DocumentVersion:
        if (
            self.index_state is DocumentIndexState.PURGED
            or self.retention_state is DocumentRetentionState.PURGED
        ) and (self.active or self.available):
            raise ValueError("a purged document version MUST be inactive and unavailable")
        return self


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
    artifact_manifest: DocumentArtifactManifest | None = None

    @model_validator(mode="after")
    def _validate_artifact_manifest(self) -> DocumentEnvelope:
        manifest = self.artifact_manifest
        if manifest is None:
            return self
        if (
            manifest.document_id != self.document_id
            or manifest.version_id != self.version_id
            or manifest.source_sha256 != self.source_sha256
        ):
            raise ValueError("artifact manifest MUST bind the envelope document version and source")
        if (
            manifest.access.collection_id != self.collection_id
            or manifest.access.reference != self.access_descriptor_ref
        ):
            raise ValueError("artifact manifest MUST bind the envelope access descriptor")
        if (
            manifest.extractor_name != self.extractor_name
            or manifest.extractor_version != self.extractor_version
        ):
            raise ValueError("artifact manifest MUST bind the envelope extractor")
        return self


class IngestionCapabilities(DocumentContract):
    supported_formats: tuple[str, ...]
    storage_modes: tuple[SourceStorageMode, ...]
    max_file_size: int
    max_batch_count: int
    archives_enabled: bool
    policy_versions: tuple[str, ...]
    direct_upload: bool = False
    ocr_available: bool = False


class EventEnvelope(DocumentContract):
    """Transport-neutral event record consumed by the ingestion worker."""

    topic: str
    key: str
    payload: dict[str, object]
    headers: dict[str, str] = {}
    offset: int | None = None

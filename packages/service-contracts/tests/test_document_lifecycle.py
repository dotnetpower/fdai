from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_service_contracts import (
    AccessDescriptor,
    ArtifactManifestEntry,
    DocumentArtifactKind,
    DocumentArtifactManifest,
    DocumentDisposition,
    DocumentEnvelope,
    DocumentIndexState,
    DocumentPurgeVerificationReceipt,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentScopeKind,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    UploadSession,
)
from pydantic import ValidationError

SOURCE_DIGEST = "a" * 64
DERIVATIVE_DIGEST = "b" * 64
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _access() -> AccessDescriptor:
    return AccessDescriptor(reference="access-policy-v1", collection_id="knowledge")


def _retention() -> RetentionPolicy:
    return RetentionPolicy(
        policy_version="retention-v1",
        source_expires_at=NOW + timedelta(days=30),
        derived_expires_at=NOW + timedelta(days=7),
    )


def _source() -> ArtifactManifestEntry:
    return ArtifactManifestEntry(
        artifact_id="source",
        kind=DocumentArtifactKind.SOURCE,
        content_sha256=SOURCE_DIGEST,
        media_type="application/pdf",
        size_bytes=100,
        retained=True,
        expires_at=NOW + timedelta(days=30),
    )


def _derivative(**updates: object) -> ArtifactManifestEntry:
    values: dict[str, object] = {
        "artifact_id": "native-text",
        "parent_artifact_id": "source",
        "kind": DocumentArtifactKind.NATIVE_TEXT,
        "content_sha256": DERIVATIVE_DIGEST,
        "media_type": "text/plain",
        "size_bytes": 20,
        "retained": True,
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(updates)
    return ArtifactManifestEntry.model_validate(values)


def _manifest(*entries: ArtifactManifestEntry, **updates: object) -> DocumentArtifactManifest:
    values: dict[str, object] = {
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "source_sha256": SOURCE_DIGEST,
        "access": _access(),
        "retention": _retention(),
        "entries": entries or (_source(), _derivative()),
        "extractor_name": "bounded-pdf",
        "extractor_version": "1.0.0",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return DocumentArtifactManifest.model_validate(values)


def _version(**updates: object) -> DocumentVersion:
    values: dict[str, object] = {
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "upload_id": UUID(int=3),
        "source_name": "guide.pdf",
        "source_sha256": SOURCE_DIGEST,
        "size_bytes": 100,
        "media_type": "application/pdf",
        "state": DocumentState.READY,
        "access": _access(),
        "retention": _retention(),
        "purposes": (DocumentPurpose.KNOWLEDGE_BASE,),
        "uploader_id": "operator",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return DocumentVersion.model_validate(values)


def _upload(**updates: object) -> UploadSession:
    values: dict[str, object] = {
        "upload_id": UUID(int=3),
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "actor_id": "operator",
        "source_name": "guide.pdf",
        "collection_id": "knowledge",
        "object_key": "uploads/guide.pdf",
        "media_type_hint": "application/pdf",
        "expected_size": 100,
        "expected_sha256": SOURCE_DIGEST,
        "state": DocumentState.CREATED,
        "storage_mode": SourceStorageMode.MANAGED_COPY,
        "purposes": (DocumentPurpose.KNOWLEDGE_BASE,),
        "access": _access(),
        "retention": _retention(),
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(updates)
    return UploadSession.model_validate(values)


def test_document_lifecycle_axes_are_stable_contract_values() -> None:
    assert tuple(DocumentDisposition) == (
        "session_ephemeral",
        "workspace_draft",
        "governed_knowledge",
        "regulated_record",
    )
    assert tuple(DocumentIndexState) == (
        "not_requested",
        "queued",
        "building",
        "active",
        "tombstoned",
        "purged",
        "failed",
    )
    assert tuple(DocumentRetentionState) == (
        "live",
        "expiring",
        "held",
        "tombstoned",
        "purge_pending",
        "purged",
    )
    assert tuple(DocumentScopeKind) == (
        "conversation",
        "workspace",
        "collection",
        "regulated",
    )


def test_existing_document_models_receive_backward_compatible_defaults() -> None:
    version = _version()
    upload = _upload()

    assert version.disposition is DocumentDisposition.GOVERNED_KNOWLEDGE
    assert upload.disposition is DocumentDisposition.GOVERNED_KNOWLEDGE
    assert version.index_state is upload.index_state is DocumentIndexState.NOT_REQUESTED
    assert version.retention_state is upload.retention_state is DocumentRetentionState.LIVE
    assert version.scope_kind is upload.scope_kind is DocumentScopeKind.COLLECTION
    assert version.scope_ref == upload.scope_ref == "knowledge"


def test_session_ephemeral_documents_require_conversation_scope() -> None:
    with pytest.raises(ValidationError, match="conversation scope"):
        _upload(disposition=DocumentDisposition.SESSION_EPHEMERAL)
    with pytest.raises(ValidationError, match="conversation scope"):
        _version(disposition=DocumentDisposition.SESSION_EPHEMERAL)

    upload = _upload(
        disposition=DocumentDisposition.SESSION_EPHEMERAL,
        scope_kind=DocumentScopeKind.CONVERSATION,
        scope_ref="conversation-1",
    )
    version = _version(
        disposition=DocumentDisposition.SESSION_EPHEMERAL,
        scope_kind=DocumentScopeKind.CONVERSATION,
        scope_ref="conversation-1",
    )
    assert upload.scope_ref == version.scope_ref == "conversation-1"


@pytest.mark.parametrize(
    ("disposition", "scope_kind"),
    [
        (DocumentDisposition.WORKSPACE_DRAFT, DocumentScopeKind.WORKSPACE),
        (DocumentDisposition.REGULATED_RECORD, DocumentScopeKind.REGULATED),
    ],
)
def test_non_governed_dispositions_require_their_scope(
    disposition: DocumentDisposition,
    scope_kind: DocumentScopeKind,
) -> None:
    with pytest.raises(ValidationError, match="MUST identify"):
        _version(disposition=disposition)
    version = _version(
        disposition=disposition,
        scope_kind=scope_kind,
        scope_ref="scope-1",
    )
    assert version.scope_kind is scope_kind


def test_governed_knowledge_rejects_non_collection_scope() -> None:
    with pytest.raises(ValidationError, match="MUST use collection scope"):
        _version(scope_kind=DocumentScopeKind.WORKSPACE, scope_ref="workspace-1")
    with pytest.raises(ValidationError, match="MUST match its collection"):
        _upload(scope_kind=DocumentScopeKind.COLLECTION, scope_ref="other-collection")


def test_document_version_records_promotion_lineage_without_self_reference() -> None:
    promoted = _version(promoted_from_version_id=UUID(int=4))
    assert promoted.promoted_from_version_id == UUID(int=4)

    with pytest.raises(ValidationError, match="MUST NOT reference itself"):
        _version(promoted_from_version_id=UUID(int=2))


def test_manifest_binds_source_hash_and_parent_lineage() -> None:
    manifest = _manifest()
    assert manifest.entries[1].parent_artifact_id == manifest.entries[0].artifact_id

    with pytest.raises(ValidationError, match="source hash MUST match"):
        _manifest(source_sha256="c" * 64)

    with pytest.raises(ValidationError, match="child parent MUST exist"):
        _manifest(_source(), _derivative(parent_artifact_id="missing"))

    with pytest.raises(ValidationError, match="digest and size"):
        _manifest(_source(), _derivative(content_sha256=None))


def test_temporary_manifest_requires_and_preserves_conversation_scope() -> None:
    manifest = _manifest(
        disposition=DocumentDisposition.SESSION_EPHEMERAL,
        scope_kind=DocumentScopeKind.CONVERSATION,
        scope_ref="conversation-1",
    )
    assert manifest.scope_ref == "conversation-1"

    with pytest.raises(ValidationError, match="conversation scope"):
        _manifest(disposition=DocumentDisposition.SESSION_EPHEMERAL)


def test_retained_derivative_cannot_outlive_governed_expiry() -> None:
    with pytest.raises(ValidationError, match="MUST NOT expire after"):
        _manifest(_source(), _derivative(expires_at=NOW + timedelta(days=8)))

    with pytest.raises(ValidationError, match="MUST expire by"):
        _manifest(_source(), _derivative(expires_at=None))


def test_retained_source_cannot_outlive_governed_expiry() -> None:
    with pytest.raises(ValidationError, match="source MUST NOT expire after"):
        _manifest(
            _source().model_copy(update={"expires_at": NOW + timedelta(days=31)}),
            _derivative(),
        )
    with pytest.raises(ValidationError, match="source MUST expire by"):
        _manifest(_source().model_copy(update={"expires_at": None}), _derivative())


@pytest.mark.parametrize(
    "updates",
    [
        {"index_state": DocumentIndexState.PURGED, "active": True},
        {"index_state": DocumentIndexState.PURGED, "available": True},
        {"retention_state": DocumentRetentionState.PURGED, "active": True},
        {"retention_state": DocumentRetentionState.PURGED, "available": True},
    ],
)
def test_purged_document_version_is_inactive_and_unavailable(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="inactive and unavailable"):
        _version(**updates)


def test_document_envelope_optionally_binds_the_artifact_manifest() -> None:
    values: dict[str, object] = {
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "source_sha256": SOURCE_DIGEST,
        "media_type": "application/pdf",
        "observed_format": "pdf",
        "size_bytes": 100,
        "collection_id": "knowledge",
        "purposes": (DocumentPurpose.KNOWLEDGE_BASE,),
        "protection_state": ProtectionState.NONE,
        "access_descriptor_ref": "access-policy-v1",
        "units": (),
        "extractor_name": "bounded-pdf",
        "extractor_version": "1.0.0",
    }
    assert DocumentEnvelope.model_validate(values).artifact_manifest is None
    assert (
        DocumentEnvelope.model_validate(
            {**values, "artifact_manifest": _manifest()}
        ).artifact_manifest
        is not None
    )

    with pytest.raises(ValidationError, match="bind the envelope document version and source"):
        DocumentEnvelope.model_validate(
            {
                **values,
                "artifact_manifest": _manifest(document_id=UUID(int=4)),
            }
        )
    with pytest.raises(ValidationError, match="access descriptor"):
        DocumentEnvelope.model_validate(
            {
                **values,
                "collection_id": "other",
                "artifact_manifest": _manifest(),
            }
        )


@pytest.mark.parametrize(
    ("updates", "verified"),
    [
        ({}, True),
        ({"live_index_rows": 1}, False),
        ({"derivative_objects": 1}, False),
        ({"source_objects": 1}, False),
        ({"cache_entries": 1}, False),
        ({"legal_hold_blocked": True}, False),
        ({"backup_blocked": True}, False),
        ({"producer_blocked": True}, False),
    ],
)
def test_purge_receipt_requires_zero_residue_and_no_blockers(
    updates: dict[str, object],
    verified: bool,
) -> None:
    values: dict[str, object] = {
        "document_id": UUID(int=1),
        "version_id": UUID(int=2),
        "live_index_rows": 0,
        "derivative_objects": 0,
        "source_objects": 0,
        "cache_entries": 0,
        "legal_hold_blocked": False,
        "backup_blocked": False,
        "verified_at": NOW,
    }
    values.update(updates)

    receipt = DocumentPurgeVerificationReceipt.model_validate(values)
    assert receipt.verified is verified
    assert receipt.model_dump()["verified"] is verified
    assert (
        DocumentPurgeVerificationReceipt.model_validate(receipt.model_dump(mode="json")).verified
        is verified
    )

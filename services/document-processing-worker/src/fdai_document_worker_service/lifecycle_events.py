"""Serialize content-free, revision-bound worker facts for the existing Huginn event boundary."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from fdai_service_contracts import DocumentLifecycleEvent, DocumentVersion, UploadSession


def document_lifecycle_payload(
    session: UploadSession,
    version: DocumentVersion,
    action: str,
    actor_id: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Project stable content-free identity for existing agent gates."""
    record: dict[str, object] = {
        "action": action,
        "actor_id": actor_id,
        "collection_id": session.collection_id,
        "document_id": str(version.document_id),
        "version_id": str(version.version_id),
        "upload_id": str(session.upload_id),
        "source_sha256": version.source_sha256,
        "state": version.state.value,
        "index_state": version.index_state.value,
        "retention_state": version.retention_state.value,
        "protection_state": version.protection_state.value,
        "sensitivity_label": version.sensitivity_label or "",
        "purposes": [purpose.value for purpose in version.purposes],
        "uploader_id": version.uploader_id,
        "failure_code": version.failure_code or "",
        "policy_version": version.retention.policy_version,
        "access_descriptor_ref": version.access.reference,
        "upload_revision": session.revision,
        "version_revision": version.revision,
    }
    if extra:
        record.update(extra)
    return record


def document_lifecycle_event(
    session: UploadSession,
    version: DocumentVersion,
    action: str,
    *,
    actor_id: str,
    observed_at: datetime,
    extra: dict[str, object] | None = None,
) -> DocumentLifecycleEvent:
    """Create a deterministic outbox fact without publishing or granting authority."""
    record = document_lifecycle_payload(session, version, action, actor_id, extra)
    identity = f"{action}:{version.version_id}:{version.revision}"
    return DocumentLifecycleEvent(
        event_id=UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16]),
        idempotency_key=identity,
        topic="object.event",
        key=str(version.document_id),
        payload={
            "producer_principal": "Huginn",
            "kind": "document_ingestion",
            "action": action,
            "event_type": action,
            "correlation_id": str(session.upload_id),
            "idempotency_key": identity,
            "resource_id": str(version.document_id),
            "resource_type": "document",
            "document_id": str(version.document_id),
            "record": record,
        },
        created_at=observed_at,
    )

"""Finish an approved cloud index only after readback; failures never expose its body."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentIndexState,
    DocumentLifecycleConflictError,
    DocumentLifecycleEvent,
    DocumentState,
    DocumentVersion,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    UploadSession,
)

from fdai_document_worker_service.effects import WorkerMetadataStore

EventFactory = Callable[
    [UploadSession, DocumentVersion, str, dict[str, object]], DocumentLifecycleEvent
]


class CloudIndexVerifier(Protocol):
    """Observe persisted candidate identity and exact approved passages without writes."""

    async def verify(self, version: DocumentVersion, envelope: DocumentEnvelope) -> str:
        """Return the observed index digest or raise; no approval or activation is granted."""
        ...


async def record_cloud_activation(
    *,
    metadata: WorkerMetadataStore,
    session: UploadSession,
    version: DocumentVersion,
    claim: DocumentWorkerClaim,
    observed_at: datetime,
    index_digest: str | None,
    event_factory: EventFactory,
) -> DocumentVersion:
    """CAS a pending, unavailable cloud generation to verified readiness or containment."""
    if (
        version.cloud_knowledge is None
        or version.state not in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
        or version.available
        or not version.active
    ):
        raise DocumentLifecycleConflictError("knowledge verification requires a pending generation")
    success = index_digest is not None
    updates: dict[str, object] = {
        "state": version.state if success else DocumentState.FAILED,
        "index_state": DocumentIndexState.ACTIVE if success else DocumentIndexState.FAILED,
        "failure_code": None if success else "cloud_activation_unverified",
    }
    next_session = session.model_copy(update={**updates, "revision": session.revision + 1})
    next_version = version.model_copy(
        update={
            **updates,
            "revision": version.revision + 1,
            "updated_at": observed_at,
            "active": success,
            "available": success,
        }
    )
    event = event_factory(
        next_session,
        next_version,
        "document.ready" if success else "document.failed",
        {
            "cloud_index_digest": index_digest,
            "cloud_verification": "verified" if success else "failed",
        },
    )
    await metadata.transition_worker_stage(
        next_session,
        next_version,
        claim=claim,
        expected_upload_state=session.state.value,
        expected_upload_revision=session.revision,
        expected_version_state=version.state.value,
        expected_version_revision=version.revision,
        event=event,
    )
    return next_version


async def verify_cloud_activation(
    *,
    metadata: WorkerMetadataStore,
    session: UploadSession,
    version: DocumentVersion,
    claim: Callable[[], DocumentWorkerClaim],
    observe: Callable[[], Awaitable[str]],
    clock: Callable[[], datetime],
    event_factory: EventFactory,
) -> DocumentVersion:
    """Record exact independent evidence or audited unavailability;
    never restore another version.
    """
    # The async observation includes current trust, scanner, source, and database checks.
    digest = None
    try:
        digest = await observe()
    except DocumentWorkerClaimConflictError:
        raise
    except Exception:  # noqa: BLE001 - private evidence errors yield a safe terminal outcome
        digest = None
    return await record_cloud_activation(
        metadata=metadata,
        session=session,
        version=version,
        claim=claim(),
        observed_at=clock(),
        index_digest=digest,
        event_factory=event_factory,
    )

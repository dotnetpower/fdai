"""Admit and commit channel attachments through the canonical document lifecycle."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentOutcome,
    ChannelAttachmentTerminalReceipt,
    DocumentAccessProvider,
    DocumentDisposition,
    DocumentIndexState,
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentScopeKind,
    DocumentState,
    DocumentUploadMetadataStore,
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    SourceStorageMode,
)
from fdai_service_contracts.compatibility import canonical_digest

from fdai_ingestion_api_service.ingestion import CreateUploadRequest, DocumentIngestionService

_IDENTITY_NAMESPACE = UUID(int=0)
_CONTRIBUTOR_ROLES = frozenset({"Contributor", "Approver", "Owner"})
_OPERATOR_ROLES = frozenset({"Reader", "Contributor", "Approver", "Owner", "BreakGlass"})
_TERMINAL_REJECTIONS = frozenset(
    {
        DocumentState.HELD,
        DocumentState.FAILED,
        DocumentState.DELETING,
        DocumentState.DELETED,
    }
)
_COMMITTED_UPLOAD_STATES = frozenset(
    {
        DocumentState.RECEIVED,
        DocumentState.QUARANTINED,
        DocumentState.SCANNING,
        DocumentState.PROTECTION_CHECK,
        DocumentState.EXTRACTING,
        DocumentState.INDEXING,
        DocumentState.READY,
        DocumentState.READY_WITH_WARNINGS,
    }
)


class ChannelAttachmentAdmissionDeniedError(PermissionError):
    """The independently resolved principal or policy does not admit the upload."""


class ChannelAttachmentConflictError(ValueError):
    """A handoff identity was replayed with different immutable content."""


@dataclass(frozen=True, slots=True)
class ChannelAttachmentReservation:
    """Durably bind one request to its original admission and optional commit receipt."""

    request: ChannelAttachmentAdmissionRequest
    admission: ChannelAttachmentAdmissionReceipt
    commit: ChannelAttachmentCommitReceipt | None = None


class ChannelAttachmentReservationStore(Protocol):
    """Persist one request-owned handoff record without document-table ownership."""

    async def reserve(
        self,
        reservation: ChannelAttachmentReservation,
    ) -> ChannelAttachmentReservation: ...

    async def get(self, handoff_id: str) -> ChannelAttachmentReservation: ...

    async def record_commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        commit: ChannelAttachmentCommitReceipt,
    ) -> ChannelAttachmentReservation: ...


class HandoverDraftReader(Protocol):
    """Read the existing worker-produced handover projection by upload id."""

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact: ...


class HandoverGovernanceReceiptReader(Protocol):
    """Verify durable governance delivery for one exact handover draft."""

    async def governance_delivered(self, artifact: HandoverDraftArtifact) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChannelAttachmentPrincipalManifest:
    """Resolve current server-owned roles from one exact deployment manifest."""

    roles_by_principal: Mapping[str, frozenset[str]]
    digest: str

    def roles_for(self, principal_id: str) -> frozenset[str]:
        """Return the current roles or deny an unknown principal uniformly."""

        roles = self.roles_by_principal.get(principal_id)
        if roles is None:
            raise ChannelAttachmentAdmissionDeniedError(
                "channel attachment principal is not admitted"
            )
        return roles

    @classmethod
    def parse(cls, value: str) -> ChannelAttachmentPrincipalManifest:
        """Parse the edge-compatible manifest and retain its canonical digest."""

        try:
            raw = json.loads(value, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("channel attachment principal manifest is invalid JSON") from exc
        if not isinstance(raw, dict) or not raw:
            raise ValueError("channel attachment principal manifest MUST be a non-empty object")
        roles_by_principal: dict[str, frozenset[str]] = {}
        normalized: dict[str, dict[str, object]] = {}
        for principal_id, item in raw.items():
            if (
                not isinstance(principal_id, str)
                or not principal_id.strip()
                or len(principal_id) > 256
                or not isinstance(item, dict)
                or set(item) - {"scope_ref", "roles", "locale"}
            ):
                raise ValueError("channel attachment principal manifest entry is invalid")
            scope_ref = item.get("scope_ref")
            locale = item.get("locale", "en")
            roles = item.get("roles")
            if (
                not isinstance(scope_ref, str)
                or not scope_ref.strip()
                or len(scope_ref) > 512
                or not isinstance(locale, str)
                or not locale.strip()
                or len(locale) > 32
                or not isinstance(roles, list)
                or not roles
                or any(not isinstance(role, str) or role not in _OPERATOR_ROLES for role in roles)
                or len(roles) != len(set(roles))
            ):
                raise ValueError("channel attachment principal manifest values are invalid")
            roles_by_principal[principal_id] = frozenset(roles)
            normalized[principal_id] = {
                "scope_ref": scope_ref,
                "roles": roles,
                "locale": locale,
            }
        return cls(
            roles_by_principal=MappingProxyType(roles_by_principal),
            digest=canonical_digest(normalized),
        )


@dataclass(frozen=True, slots=True)
class ChannelAttachmentPolicy:
    """Hold deployment-owned document policy that request data cannot override."""

    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    max_content_bytes: int
    admission_ttl: timedelta = timedelta(minutes=15)
    require_handover_governance: bool = False

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("collection_id", self.collection_id, 256),
            ("access_descriptor_ref", self.access_descriptor_ref, 512),
            ("retention_policy_version", self.retention_policy_version, 128),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"channel attachment {label} MUST be bounded and non-empty")
        if (
            not self.reader_groups
            or len(self.reader_groups) != len(set(self.reader_groups))
            or any(not value.strip() or len(value) > 256 for value in self.reader_groups)
        ):
            raise ValueError("channel attachment reader groups MUST be unique and bounded")
        if self.max_content_bytes < 1:
            raise ValueError("channel attachment max content bytes MUST be positive")
        if self.admission_ttl <= timedelta(0) or self.admission_ttl > timedelta(hours=1):
            raise ValueError("channel attachment admission TTL MUST be in (0, 1 hour]")

    @property
    def digest(self) -> str:
        """Return the content identity of every server-owned policy value."""

        return canonical_digest(
            {
                "schema_version": "1.0.0",
                "collection_id": self.collection_id,
                "access_descriptor_ref": self.access_descriptor_ref,
                "reader_groups": list(self.reader_groups),
                "retention_policy_version": self.retention_policy_version,
                "max_content_bytes": self.max_content_bytes,
                "admission_ttl_seconds": int(self.admission_ttl.total_seconds()),
                "require_handover_governance": self.require_handover_governance,
            }
        )


class ChannelAttachmentIntakeService:
    """Join internal handoff records to the existing API-owned upload transitions."""

    def __init__(
        self,
        *,
        ingestion: DocumentIngestionService,
        metadata: DocumentUploadMetadataStore,
        access: DocumentAccessProvider,
        reservations: ChannelAttachmentReservationStore,
        principals: ChannelAttachmentPrincipalManifest,
        policy: ChannelAttachmentPolicy,
        handover_drafts: HandoverDraftReader | None = None,
        handover_governance: HandoverGovernanceReceiptReader | None = None,
        clock: Callable[[], datetime] | None = None,
        request_future_skew: timedelta = timedelta(minutes=1),
    ) -> None:
        if request_future_skew < timedelta(0) or request_future_skew > timedelta(minutes=5):
            raise ValueError("channel attachment future skew MUST be in [0, 5 minutes]")
        if policy.require_handover_governance and (
            handover_drafts is None or handover_governance is None
        ):
            raise ValueError("required handover governance readers MUST be configured")
        self._ingestion = ingestion
        self._metadata = metadata
        self._access = access
        self._reservations = reservations
        self._principals = principals
        self._policy = policy
        self._handover_drafts = handover_drafts
        self._handover_governance = handover_governance
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._request_future_skew = request_future_skew

    async def admit(
        self,
        request: ChannelAttachmentAdmissionRequest,
    ) -> ChannelAttachmentAdmissionReceipt:
        """Authorize and durably reserve one handoff before provider download."""

        now = _aware(self._clock())
        self._authorize(request)
        if request.requested_at > now + self._request_future_skew:
            raise ChannelAttachmentAdmissionDeniedError(
                "channel attachment request time is outside the admission window"
            )
        expires_at = request.requested_at + self._policy.admission_ttl
        if expires_at <= now:
            raise ChannelAttachmentAdmissionDeniedError("channel attachment admission has expired")
        max_content_bytes = min(
            self._policy.max_content_bytes,
            self._ingestion.capabilities.max_file_size,
        )
        if request.declared_size > max_content_bytes:
            raise ChannelAttachmentAdmissionDeniedError(
                "channel attachment exceeds the admitted content limit"
            )
        material: dict[str, object] = {
            "schema_version": "1.0.0",
            "receipt_kind": "admission",
            "handoff_id": request.handoff_id,
            "request_digest": request.request_digest,
            "policy_digest": self._policy.digest,
            "max_content_bytes": max_content_bytes,
            "accepted_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "execution_authority": False,
        }
        admission = ChannelAttachmentAdmissionReceipt.model_validate(
            {**material, "receipt_digest": canonical_digest(material)}
        )
        stored = await self._reservations.reserve(
            ChannelAttachmentReservation(request=request, admission=admission)
        )
        if stored.request != request:
            raise ChannelAttachmentConflictError(
                "channel attachment handoff conflicts with its durable request"
            )
        return stored.admission

    async def commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        observed_size: int,
        observed_sha256: str,
        chunks: AsyncIterator[bytes],
    ) -> ChannelAttachmentCommitReceipt:
        """Stream one admitted source and return its durable received-state receipt."""

        reservation = await self._reservation(handoff_id, request_digest)
        if reservation.commit is not None:
            if (
                isinstance(observed_size, bool)
                or observed_size != reservation.commit.observed_size
                or observed_sha256 != reservation.commit.observed_sha256
            ):
                raise ChannelAttachmentConflictError(
                    "channel attachment replay content does not match its commit"
                )
            return reservation.commit
        request = reservation.request
        self._authorize(request)
        if _aware(self._clock()) >= reservation.admission.expires_at:
            raise ChannelAttachmentAdmissionDeniedError("channel attachment admission has expired")
        if (
            isinstance(observed_size, bool)
            or observed_size != request.declared_size
            or observed_size > reservation.admission.max_content_bytes
        ):
            raise ChannelAttachmentConflictError(
                "channel attachment content size does not match admission"
            )
        if len(observed_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in observed_sha256
        ):
            raise ChannelAttachmentConflictError("channel attachment SHA-256 is invalid")

        upload_id, document_id, version_id = channel_attachment_ids(handoff_id)
        actor_groups = _actor_groups(self._principals.roles_for(request.attributed_principal_id))
        expected = CreateUploadRequest(
            source_name=request.source_name,
            collection_id=self._policy.collection_id,
            media_type_hint=request.media_type_hint,
            expected_size=observed_size,
            expected_sha256=observed_sha256,
            storage_mode=SourceStorageMode.MANAGED_COPY,
            purposes=(request.requested_purpose,),
            access_descriptor_ref=self._policy.access_descriptor_ref,
            reader_groups=self._policy.reader_groups,
            retention_policy_version=self._policy.retention_policy_version,
            document_id=document_id,
            upload_id=upload_id,
            version_id=version_id,
            connector_idempotency_key=handoff_id,
            disposition=DocumentDisposition.SESSION_EPHEMERAL,
            scope_kind=DocumentScopeKind.CONVERSATION,
            scope_ref=request.conversation_ref,
        )
        try:
            session, _grant = await self._ingestion.create_upload(
                actor_id=request.attributed_principal_id,
                actor_groups=actor_groups,
                request=expected,
            )
        except ValueError as exc:
            if str(exc) != "document upload or version already exists":
                raise
            session = await self._metadata.get_upload(upload_id)
            _validate_session(session, request=request, expected=expected, verify_content=True)

        if session.state is DocumentState.CREATED:
            await self._ingestion.resume_upload(
                actor_id=request.attributed_principal_id,
                actor_groups=actor_groups,
                upload_id=upload_id,
            )
            session = await self._metadata.get_upload(upload_id)
        if session.state is DocumentState.UPLOADING:
            await self._ingestion.put_streaming_content(
                actor_id=request.attributed_principal_id,
                actor_groups=actor_groups,
                upload_id=upload_id,
                chunks=chunks,
            )
            session = await self._ingestion.complete_upload(
                actor_id=request.attributed_principal_id,
                actor_groups=actor_groups,
                upload_id=upload_id,
            )
        if session.state not in _COMMITTED_UPLOAD_STATES:
            raise ChannelAttachmentConflictError(
                "channel attachment upload cannot produce a commit receipt"
            )
        return await self._record_commit(
            handoff_id=handoff_id,
            request_digest=request_digest,
            upload_id=upload_id,
            document_id=document_id,
            version_id=version_id,
            observed_size=observed_size,
            observed_sha256=observed_sha256,
        )

    async def status(
        self,
        *,
        handoff_id: str,
        request_digest: str,
    ) -> (
        ChannelAttachmentAdmissionReceipt
        | ChannelAttachmentCommitReceipt
        | ChannelAttachmentTerminalReceipt
    ):
        """Reauthorize and observe one handoff without reading document content."""

        reservation = await self._reservation(handoff_id, request_digest)
        request = reservation.request
        self._authorize(request)
        upload_id, document_id, version_id = channel_attachment_ids(handoff_id)
        now = _aware(self._clock())
        commit = reservation.commit
        if commit is None:
            try:
                session = await self._metadata.get_upload(upload_id)
            except DocumentNotFoundError:
                return reservation.admission
            if session.state not in _COMMITTED_UPLOAD_STATES:
                return reservation.admission
            _validate_session(
                session,
                request=request,
                expected=_expected_request(
                    self._policy,
                    request,
                    upload_id,
                    document_id,
                    version_id,
                    expected_sha256=session.expected_sha256,
                ),
                verify_content=True,
            )
            commit = await self._record_commit(
                handoff_id=handoff_id,
                request_digest=request_digest,
                upload_id=upload_id,
                document_id=document_id,
                version_id=version_id,
                observed_size=session.expected_size,
                observed_sha256=session.expected_sha256,
            )
        try:
            session = await self._metadata.get_upload(upload_id)
            version = await self._metadata.get_version(document_id, version_id)
        except DocumentNotFoundError:
            return commit
        _validate_session(
            session,
            request=request,
            expected=_expected_request(
                self._policy,
                request,
                upload_id,
                document_id,
                version_id,
                expected_sha256=commit.observed_sha256,
            ),
            verify_content=True,
        )
        actor_groups = _actor_groups(self._principals.roles_for(request.attributed_principal_id))
        await self._access.authorize_read(
            actor_id=request.attributed_principal_id,
            actor_groups=actor_groups,
            version=version,
        )
        expired = (
            version.retention.derived_expires_at is not None
            and version.retention.derived_expires_at <= now
        )
        handover_ready = False
        handover_rejected = False
        if (
            request.requested_purpose is DocumentPurpose.HANDOVER_BOOTSTRAP
            and self._handover_drafts is not None
        ):
            try:
                draft = await self._handover_drafts.get(upload_id)
            except DocumentNotFoundError:
                pass
            else:
                if (
                    draft.upload_id != upload_id
                    or draft.document_id != document_id
                    or draft.version_id != version_id
                ):
                    raise ChannelAttachmentConflictError(
                        "handover draft identity does not match attachment"
                    )
                if (
                    draft.draft.outcome is not HandoverDraftOutcome.DRAFTED
                    or not draft.draft.mappings
                ):
                    handover_rejected = True
                elif self._policy.require_handover_governance:
                    if self._handover_governance is None:
                        raise RuntimeError("handover governance reader is unavailable")
                    handover_ready = await self._handover_governance.governance_delivered(draft)
                else:
                    handover_ready = True
        query_visible = (
            version.state in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
            and version.index_state is DocumentIndexState.ACTIVE
            and version.retention_state is DocumentRetentionState.LIVE
            and version.active
            and version.available
            and not expired
        )
        purpose_ready = (
            request.requested_purpose is not DocumentPurpose.HANDOVER_BOOTSTRAP or handover_ready
        )
        if query_visible and purpose_ready:
            outcome = ChannelAttachmentOutcome.READY
            reason_code = None
        elif expired:
            outcome = ChannelAttachmentOutcome.REJECTED
            reason_code = "document_expired"
        elif handover_rejected:
            outcome = ChannelAttachmentOutcome.REJECTED
            reason_code = "handover_draft_unavailable"
        elif version.state in _TERMINAL_REJECTIONS or version.index_state in {
            DocumentIndexState.FAILED,
            DocumentIndexState.TOMBSTONED,
            DocumentIndexState.PURGED,
        }:
            outcome = ChannelAttachmentOutcome.REJECTED
            reason_code = "document_unavailable"
        else:
            outcome = ChannelAttachmentOutcome.PENDING
            reason_code = None
        return _terminal_receipt(
            reservation=reservation,
            commit=commit,
            upload_id=upload_id,
            document_id=document_id,
            version_id=version_id,
            outcome=outcome,
            document_state=version.state,
            index_state=version.index_state,
            retention_state=version.retention_state,
            active=version.active,
            available=version.available,
            handover_draft_ready=handover_ready,
            reason_code=reason_code,
            observed_at=now,
        )

    async def _record_commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        upload_id: UUID,
        document_id: UUID,
        version_id: UUID,
        observed_size: int,
        observed_sha256: str,
    ) -> ChannelAttachmentCommitReceipt:
        material = {
            "schema_version": "1.0.0",
            "receipt_kind": "commit",
            "handoff_id": handoff_id,
            "request_digest": request_digest,
            "upload_id": str(upload_id),
            "document_id": str(document_id),
            "version_id": str(version_id),
            "observed_size": observed_size,
            "observed_sha256": observed_sha256,
            "state": "received",
            "committed_at": _aware(self._clock()).isoformat().replace("+00:00", "Z"),
            "execution_authority": False,
        }
        commit = ChannelAttachmentCommitReceipt.model_validate(
            {**material, "receipt_digest": canonical_digest(material)}
        )
        stored = await self._reservations.record_commit(
            handoff_id=handoff_id,
            request_digest=request_digest,
            commit=commit,
        )
        if stored.commit is None or (
            stored.commit.handoff_id != handoff_id
            or stored.commit.request_digest != request_digest
            or stored.commit.upload_id != upload_id
            or stored.commit.document_id != document_id
            or stored.commit.version_id != version_id
            or stored.commit.observed_size != observed_size
            or stored.commit.observed_sha256 != observed_sha256
        ):
            raise ChannelAttachmentConflictError(
                "channel attachment commit conflicts with its durable receipt"
            )
        return stored.commit

    def _authorize(self, request: ChannelAttachmentAdmissionRequest) -> None:
        if request.principal_manifest_digest != self._principals.digest:
            raise ChannelAttachmentAdmissionDeniedError(
                "channel attachment principal manifest is not current"
            )
        roles = self._principals.roles_for(request.attributed_principal_id)
        if roles.isdisjoint(_CONTRIBUTOR_ROLES):
            raise ChannelAttachmentAdmissionDeniedError(
                "channel attachment requires Contributor access"
            )

    async def _reservation(
        self,
        handoff_id: str,
        request_digest: str,
    ) -> ChannelAttachmentReservation:
        reservation = await self._reservations.get(handoff_id)
        if reservation.request.request_digest != request_digest:
            raise ChannelAttachmentConflictError(
                "channel attachment request digest does not match reservation"
            )
        return reservation


def channel_attachment_ids(handoff_id: str) -> tuple[UUID, UUID, UUID]:
    """Derive stable canonical upload identities from one validated handoff id."""

    return (
        uuid5(_IDENTITY_NAMESPACE, f"channel-attachment:upload:{handoff_id}"),
        uuid5(_IDENTITY_NAMESPACE, f"channel-attachment:document:{handoff_id}"),
        uuid5(_IDENTITY_NAMESPACE, f"channel-attachment:version:{handoff_id}"),
    )


def _expected_request(
    policy: ChannelAttachmentPolicy,
    request: ChannelAttachmentAdmissionRequest,
    upload_id: UUID,
    document_id: UUID,
    version_id: UUID,
    *,
    expected_sha256: str = "0" * 64,
) -> CreateUploadRequest:
    return CreateUploadRequest(
        source_name=request.source_name,
        collection_id=policy.collection_id,
        media_type_hint=request.media_type_hint,
        expected_size=request.declared_size,
        expected_sha256=expected_sha256,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(request.requested_purpose,),
        access_descriptor_ref=policy.access_descriptor_ref,
        reader_groups=policy.reader_groups,
        retention_policy_version=policy.retention_policy_version,
        document_id=document_id,
        upload_id=upload_id,
        version_id=version_id,
        connector_idempotency_key=request.handoff_id,
        disposition=DocumentDisposition.SESSION_EPHEMERAL,
        scope_kind=DocumentScopeKind.CONVERSATION,
        scope_ref=request.conversation_ref,
    )


def _validate_session(
    session: object,
    *,
    request: ChannelAttachmentAdmissionRequest,
    expected: CreateUploadRequest,
    verify_content: bool,
) -> None:
    from fdai_service_contracts import UploadSession

    if not isinstance(session, UploadSession) or (
        session.upload_id != expected.upload_id
        or session.document_id != expected.document_id
        or session.version_id != expected.version_id
        or session.actor_id != request.attributed_principal_id
        or session.source_name != expected.source_name
        or session.collection_id != expected.collection_id
        or session.media_type_hint != expected.media_type_hint
        or session.expected_size != expected.expected_size
        or (verify_content and session.expected_sha256 != expected.expected_sha256)
        or session.storage_mode is not expected.storage_mode
        or session.purposes != expected.purposes
        or session.access.reference != expected.access_descriptor_ref
        or session.access.reader_groups != expected.reader_groups
        or session.retention.policy_version != expected.retention_policy_version
        or session.disposition is not expected.disposition
        or session.scope_kind is not expected.scope_kind
        or session.scope_ref != expected.scope_ref
    ):
        raise ChannelAttachmentConflictError(
            "channel attachment upload identity does not match its reservation"
        )


def _actor_groups(roles: frozenset[str]) -> frozenset[str]:
    return frozenset(f"role:{role}" for role in roles)


def _terminal_receipt(
    *,
    reservation: ChannelAttachmentReservation,
    commit: ChannelAttachmentCommitReceipt,
    upload_id: UUID,
    document_id: UUID,
    version_id: UUID,
    outcome: ChannelAttachmentOutcome,
    document_state: DocumentState,
    index_state: DocumentIndexState,
    retention_state: DocumentRetentionState,
    active: bool,
    available: bool,
    handover_draft_ready: bool,
    reason_code: str | None,
    observed_at: datetime,
) -> ChannelAttachmentTerminalReceipt:
    citation = (
        f"doc:{document_id}:{version_id}" if outcome is ChannelAttachmentOutcome.READY else None
    )
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "receipt_kind": "terminal",
        "handoff_id": reservation.request.handoff_id,
        "request_digest": reservation.request.request_digest,
        "upload_id": str(upload_id),
        "document_id": str(document_id),
        "version_id": str(version_id),
        "commit_receipt_digest": commit.receipt_digest,
        "observed_size": commit.observed_size,
        "observed_sha256": commit.observed_sha256,
        "requested_purpose": reservation.request.requested_purpose.value,
        "outcome": outcome.value,
        "document_state": document_state.value,
        "index_state": index_state.value,
        "retention_state": retention_state.value,
        "active": active,
        "available": available,
        "handover_draft_ready": handover_draft_ready,
        "citation": citation,
        "reason_code": reason_code,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    return ChannelAttachmentTerminalReceipt.model_validate(
        {**material, "receipt_digest": canonical_digest(material)}
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("channel attachment clock MUST be timezone-aware")
    return value.astimezone(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


__all__ = [
    "ChannelAttachmentAdmissionDeniedError",
    "ChannelAttachmentConflictError",
    "ChannelAttachmentIntakeService",
    "ChannelAttachmentPolicy",
    "ChannelAttachmentPrincipalManifest",
    "ChannelAttachmentReservation",
    "ChannelAttachmentReservationStore",
    "channel_attachment_ids",
]

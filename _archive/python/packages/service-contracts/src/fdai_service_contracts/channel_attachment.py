"""Authority-free contracts for the Operator-to-ingestion attachment handoff."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from unicodedata import category
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.document import (
    DocumentIndexState,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
)

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
HandoffId = Annotated[str, Field(pattern=r"^channel-attachment-[a-f0-9]{64}$")]
ConversationRef = Annotated[str, Field(min_length=1, max_length=256)]
_CITATION_PATTERN = (
    r"^doc:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ALLOWED_PURPOSES = frozenset({DocumentPurpose.KNOWLEDGE_BASE, DocumentPurpose.HANDOVER_BOOTSTRAP})


class ChannelAttachmentContract(BaseModel):
    """Reject unknown fields and control characters at the service boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(ord(character) < 32 for character in value):
            raise ValueError("channel attachment text MUST NOT contain control characters")
        return value


class ChannelAttachmentOutcome(StrEnum):
    """Classify one current handoff observation without inventing success."""

    PENDING = "pending"
    READY = "ready"
    REJECTED = "rejected"


class ChannelAttachmentAdmissionRequest(ChannelAttachmentContract):
    """Request bounded admission before any provider file download begins."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    handoff_id: HandoffId
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    origin_digest: Digest
    ordinal: Annotated[int, Field(ge=0, le=7)]
    attributed_principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_manifest_digest: Digest
    conversation_ref: ConversationRef
    requested_purpose: DocumentPurpose
    source_name: Annotated[str, Field(min_length=1, max_length=512)]
    media_type_hint: Annotated[str, Field(min_length=1, max_length=256)]
    declared_size: Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
    requested_at: datetime
    request_digest: Digest
    execution_authority: Literal[False] = False

    @field_validator("source_name")
    @classmethod
    def _source_name_is_safe_leaf(cls, value: str) -> str:
        if value in {".", ".."} or any(
            character in {"/", "\\"} or category(character).startswith("C") for character in value
        ):
            raise ValueError("channel attachment source_name MUST be a safe leaf name")
        return value

    @model_validator(mode="after")
    def _request_is_exact(self) -> ChannelAttachmentAdmissionRequest:
        _aware("requested_at", self.requested_at)
        if self.requested_purpose not in _ALLOWED_PURPOSES:
            raise ValueError("channel attachment purpose is not supported")
        if self.request_digest != channel_attachment_request_digest(self):
            raise ValueError("channel attachment request digest does not match its content")
        return self


class ChannelAttachmentAdmissionReceipt(ChannelAttachmentContract):
    """Return server-owned admission limits without a URL or storage credential."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_kind: Literal["admission"] = "admission"
    handoff_id: HandoffId
    request_digest: Digest
    policy_digest: Digest
    max_content_bytes: Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
    accepted_at: datetime
    expires_at: datetime
    execution_authority: Literal[False] = False
    receipt_digest: Digest

    @model_validator(mode="after")
    def _receipt_is_exact(self) -> ChannelAttachmentAdmissionReceipt:
        _aware("accepted_at", self.accepted_at)
        _aware("expires_at", self.expires_at)
        if self.expires_at <= self.accepted_at:
            raise ValueError("channel attachment admission MUST expire after acceptance")
        if self.receipt_digest != channel_attachment_receipt_digest(self):
            raise ValueError("channel attachment admission digest does not match its content")
        return self


class ChannelAttachmentCommitReceipt(ChannelAttachmentContract):
    """Bind independently verified content to one canonical received document version."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_kind: Literal["commit"] = "commit"
    handoff_id: HandoffId
    request_digest: Digest
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    observed_size: Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
    observed_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    state: Literal[DocumentState.RECEIVED] = DocumentState.RECEIVED
    committed_at: datetime
    execution_authority: Literal[False] = False
    receipt_digest: Digest

    @model_validator(mode="after")
    def _receipt_is_exact(self) -> ChannelAttachmentCommitReceipt:
        _aware("committed_at", self.committed_at)
        if self.receipt_digest != channel_attachment_receipt_digest(self):
            raise ValueError("channel attachment commit digest does not match its content")
        return self


class ChannelAttachmentTerminalReceipt(ChannelAttachmentContract):
    """Report one authorized lifecycle observation and cite only query-visible content."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_kind: Literal["terminal"] = "terminal"
    handoff_id: HandoffId
    request_digest: Digest
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    commit_receipt_digest: Digest
    observed_size: Annotated[int, Field(ge=1, le=9_223_372_036_854_775_807)]
    observed_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    requested_purpose: DocumentPurpose
    outcome: ChannelAttachmentOutcome
    document_state: DocumentState
    index_state: DocumentIndexState
    retention_state: DocumentRetentionState
    active: bool
    available: bool
    handover_draft_ready: bool = False
    citation: Annotated[str, Field(pattern=_CITATION_PATTERN)] | None = None
    reason_code: (
        Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")] | None
    ) = None
    observed_at: datetime
    execution_authority: Literal[False] = False
    receipt_digest: Digest

    @model_validator(mode="after")
    def _outcome_matches_state(self) -> ChannelAttachmentTerminalReceipt:
        _aware("observed_at", self.observed_at)
        if self.requested_purpose not in _ALLOWED_PURPOSES:
            raise ValueError("channel attachment purpose is not supported")
        if self.handover_draft_ready and (
            self.requested_purpose is not DocumentPurpose.HANDOVER_BOOTSTRAP
        ):
            raise ValueError("only handover attachments can carry a ready draft")

        query_visible = (
            self.document_state in {DocumentState.READY, DocumentState.READY_WITH_WARNINGS}
            and self.index_state is DocumentIndexState.ACTIVE
            and self.retention_state is DocumentRetentionState.LIVE
            and self.active
            and self.available
        )
        handover_ready = (
            self.requested_purpose is not DocumentPurpose.HANDOVER_BOOTSTRAP
            or self.handover_draft_ready
        )
        expected_citation = f"doc:{self.document_id}:{self.version_id}"
        if self.outcome is ChannelAttachmentOutcome.READY:
            if (
                not query_visible
                or not handover_ready
                or self.citation != expected_citation
                or self.reason_code is not None
            ):
                raise ValueError("ready channel attachment receipt is not query-visible")
        elif self.outcome is ChannelAttachmentOutcome.PENDING:
            if self.citation is not None or self.reason_code is not None:
                raise ValueError("pending channel attachment receipt cannot carry a result")
            if query_visible and handover_ready:
                raise ValueError("query-visible channel attachment receipt cannot remain pending")
        elif self.citation is not None or self.reason_code is None:
            raise ValueError("rejected channel attachment receipt requires only a reason")

        if self.receipt_digest != channel_attachment_receipt_digest(self):
            raise ValueError("channel attachment terminal digest does not match its content")
        return self


def channel_attachment_request_digest(request: ChannelAttachmentAdmissionRequest) -> str:
    """Return the canonical request digest without the digest field itself."""

    return canonical_digest(request.model_dump(mode="json", exclude={"request_digest"}))


def channel_attachment_receipt_digest(
    receipt: (
        ChannelAttachmentAdmissionReceipt
        | ChannelAttachmentCommitReceipt
        | ChannelAttachmentTerminalReceipt
    ),
) -> str:
    """Return the canonical receipt digest without the digest field itself."""

    return canonical_digest(receipt.model_dump(mode="json", exclude={"receipt_digest"}))


def _aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"channel attachment {label} MUST be timezone-aware")


__all__ = [
    "ChannelAttachmentAdmissionReceipt",
    "ChannelAttachmentAdmissionRequest",
    "ChannelAttachmentCommitReceipt",
    "ChannelAttachmentOutcome",
    "ChannelAttachmentTerminalReceipt",
    "channel_attachment_receipt_digest",
    "channel_attachment_request_digest",
]

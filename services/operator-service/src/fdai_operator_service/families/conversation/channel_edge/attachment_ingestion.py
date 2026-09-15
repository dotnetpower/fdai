"""Orchestrate stable, receipt-bound channel attachment ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.attachment_handoff import (
    ChannelAttachmentFetcher,
    ChannelAttachmentHandoffError,
    ChannelAttachmentIntakeClient,
    SpooledAttachment,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelAttachment,
)
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentOutcome,
    ChannelAttachmentTerminalReceipt,
    DocumentPurpose,
    SemanticDocumentContext,
    SemanticDocumentContextSource,
    canonical_digest,
    semantic_document_context_digest,
)


@dataclass(frozen=True, slots=True)
class ChannelAttachmentIngestionResult:
    """Return ordered terminal receipts and their exact semantic context."""

    purpose: DocumentPurpose
    receipts: tuple[ChannelAttachmentTerminalReceipt, ...]
    document_context: SemanticDocumentContext

    def __post_init__(self) -> None:
        if (
            not self.receipts
            or self.document_context.source is not SemanticDocumentContextSource.CHANNEL_ATTACHMENT
            or tuple(receipt.citation for receipt in self.receipts)
            != self.document_context.citations
            or tuple(receipt.receipt_digest for receipt in self.receipts)
            != self.document_context.receipt_digests
            or any(
                receipt.outcome is not ChannelAttachmentOutcome.READY
                or receipt.requested_purpose is not self.purpose
                or (
                    self.purpose is DocumentPurpose.HANDOVER_BOOTSTRAP
                    and not receipt.handover_draft_ready
                )
                for receipt in self.receipts
            )
        ):
            raise ValueError("channel attachment ingestion result requires matching ready receipts")


class ChannelAttachmentIngestor:
    """Admit, fetch, commit, and observe all attachments in stable ordinal order."""

    def __init__(
        self,
        *,
        intake: ChannelAttachmentIntakeClient,
        fetchers: Mapping[ChannelKind, ChannelAttachmentFetcher],
        principal_manifest_digest: str,
        max_content_bytes: int = 25 * 1024 * 1024,
        terminal_timeout: timedelta = timedelta(minutes=2),
        poll_interval: float = 0.5,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if not principal_manifest_digest.startswith("sha256:"):
            raise ValueError("channel principal manifest digest is invalid")
        if terminal_timeout <= timedelta(0) or poll_interval <= 0:
            raise ValueError("channel attachment polling bounds MUST be positive")
        if not 1 <= max_content_bytes <= 1024 * 1024 * 1024:
            raise ValueError("channel attachment byte ceiling is invalid")
        self._intake = intake
        self._fetchers = dict(fetchers)
        self._manifest_digest = principal_manifest_digest
        self._max_content_bytes = max_content_bytes
        self._terminal_timeout = terminal_timeout
        self._poll_interval = poll_interval
        self._clock = clock

    async def ingest(
        self,
        authenticated: AuthenticatedInboundTurn,
        *,
        conversation_ref: str,
        purpose: DocumentPurpose,
    ) -> ChannelAttachmentIngestionResult:
        origin_digest = canonical_digest(
            {
                "channel_kind": authenticated.turn.channel_kind.value,
                "channel_id": authenticated.turn.channel_id,
                "message_id": authenticated.turn.message_id,
                "sender_id": authenticated.turn.sender_id,
                "principal_id": authenticated.principal_id,
                "verification_ref": authenticated.verification_ref,
            }
        )
        receipts: list[ChannelAttachmentTerminalReceipt] = []
        for ordinal, attachment in enumerate(authenticated.turn.attachments):
            request = _admission_request(
                attachment=attachment,
                ordinal=ordinal,
                origin_digest=origin_digest,
                principal_id=authenticated.principal_id,
                principal_manifest_digest=self._manifest_digest,
                conversation_ref=conversation_ref,
                purpose=purpose,
                requested_at=_aware_utc(self._clock()),
            )
            admission = await self._intake.admit(request)
            replay_state = await self._intake.status(request)
            if isinstance(replay_state, ChannelAttachmentTerminalReceipt):
                if replay_state.outcome is ChannelAttachmentOutcome.PENDING:
                    replay_state = await self._terminal(request, baseline=replay_state)
                if replay_state.outcome is not ChannelAttachmentOutcome.READY:
                    raise ChannelAttachmentHandoffError(
                        "replayed channel attachment is not query-visible",
                        code=replay_state.reason_code or "terminal_rejected",
                    )
                receipts.append(replay_state)
                continue
            if isinstance(replay_state, ChannelAttachmentCommitReceipt):
                terminal = await self._terminal(request, baseline=replay_state)
                _match_terminal_commit(terminal, replay_state)
                if terminal.outcome is not ChannelAttachmentOutcome.READY:
                    raise ChannelAttachmentHandoffError(
                        "channel attachment did not become query-visible",
                        code=terminal.reason_code or "terminal_rejected",
                    )
                receipts.append(terminal)
                continue
            fetcher = self._fetchers.get(authenticated.turn.channel_kind)
            if fetcher is None:
                raise ChannelAttachmentHandoffError(
                    "channel attachment fetcher is unavailable", code="fetcher_unavailable"
                )
            content = await fetcher.fetch(
                attachment,
                conversation_ref=conversation_ref,
                max_content_bytes=min(
                    self._max_content_bytes,
                    admission.max_content_bytes,
                ),
            )
            async with content:
                if _aware_utc(self._clock()) >= admission.expires_at:
                    raise ChannelAttachmentHandoffError(
                        "channel attachment admission expired before commit",
                        code="admission_expired",
                    )
                committed = await self._commit_with_recovery(request, content)
                observed_size = content.size_bytes
                observed_sha256 = content.sha256
            terminal = (
                committed
                if isinstance(committed, ChannelAttachmentTerminalReceipt)
                and committed.outcome is not ChannelAttachmentOutcome.PENDING
                else await self._terminal(request, baseline=committed)
            )
            _match_terminal_content(
                terminal,
                observed_size=observed_size,
                observed_sha256=observed_sha256,
            )
            if isinstance(committed, ChannelAttachmentCommitReceipt):
                _match_terminal_commit(terminal, committed)
            if terminal.outcome is not ChannelAttachmentOutcome.READY:
                raise ChannelAttachmentHandoffError(
                    "channel attachment did not become query-visible",
                    code=terminal.reason_code or "terminal_rejected",
                )
            receipts.append(terminal)
        context = _semantic_context(
            principal_ref=authenticated.principal_id,
            conversation_ref=conversation_ref,
            receipts=tuple(receipts),
        )
        return ChannelAttachmentIngestionResult(
            purpose=purpose,
            receipts=tuple(receipts),
            document_context=context,
        )

    async def _commit_with_recovery(
        self,
        request: ChannelAttachmentAdmissionRequest,
        content: SpooledAttachment,
    ) -> ChannelAttachmentCommitReceipt | ChannelAttachmentTerminalReceipt:
        try:
            committed = await self._intake.commit(request, content)
            _match_committed_content(committed, content)
            return committed
        except ChannelAttachmentHandoffError as exc:
            if exc.code not in {"intake_transport", "intake_unavailable"}:
                raise
        observed = await self._intake.status(request)
        if isinstance(observed, ChannelAttachmentCommitReceipt):
            _match_committed_content(observed, content)
            return observed
        if isinstance(observed, ChannelAttachmentTerminalReceipt):
            if observed.outcome is ChannelAttachmentOutcome.REJECTED:
                raise ChannelAttachmentHandoffError(
                    "attachment intake rejected ambiguous commit",
                    code=observed.reason_code or "terminal_rejected",
                )
            return observed
        if not isinstance(observed, ChannelAttachmentAdmissionReceipt):
            raise ChannelAttachmentHandoffError(
                "attachment intake returned an invalid recovery state", code="invalid_receipt"
            )
        committed = await self._intake.commit(request, content)
        _match_committed_content(committed, content)
        return committed

    async def _terminal(
        self,
        request: ChannelAttachmentAdmissionRequest,
        *,
        baseline: ChannelAttachmentCommitReceipt | ChannelAttachmentTerminalReceipt,
    ) -> ChannelAttachmentTerminalReceipt:
        deadline = asyncio.get_running_loop().time() + self._terminal_timeout.total_seconds()
        while True:
            observed = await self._intake.status(request)
            if isinstance(observed, ChannelAttachmentTerminalReceipt):
                if isinstance(baseline, ChannelAttachmentCommitReceipt):
                    _match_terminal_commit(observed, baseline)
                else:
                    _match_terminal_progression(observed, baseline)
                if observed.outcome is not ChannelAttachmentOutcome.PENDING:
                    return observed
            if asyncio.get_running_loop().time() >= deadline:
                raise ChannelAttachmentHandoffError(
                    "channel attachment terminal observation timed out",
                    code="terminal_timeout",
                )
            await asyncio.sleep(self._poll_interval)


def attachment_purpose(text: str) -> DocumentPurpose:
    """Select handover only from an exact leading directive."""

    normalized = text.strip().casefold()
    if (
        normalized == "/handover"
        or normalized.startswith("/handover ")
        or normalized == "/attach handover"
        or normalized.startswith("/attach handover ")
        or normalized.startswith("인수인계 문서:")
    ):
        return DocumentPurpose.HANDOVER_BOOTSTRAP
    return DocumentPurpose.KNOWLEDGE_BASE


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("channel attachment clock MUST be timezone-aware")
    return value.astimezone(UTC)


def _admission_request(
    *,
    attachment: ChannelAttachment,
    ordinal: int,
    origin_digest: str,
    principal_id: str,
    principal_manifest_digest: str,
    conversation_ref: str,
    purpose: DocumentPurpose,
    requested_at: datetime,
) -> ChannelAttachmentAdmissionRequest:
    identity = canonical_digest({"origin_digest": origin_digest, "ordinal": ordinal}).removeprefix(
        "sha256:"
    )
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "handoff_id": "channel-attachment-" + identity,
        "idempotency_key": "channel-attachment-" + identity,
        "origin_digest": origin_digest,
        "ordinal": ordinal,
        "attributed_principal_id": principal_id,
        "principal_manifest_digest": principal_manifest_digest,
        "conversation_ref": conversation_ref,
        "requested_purpose": purpose,
        "source_name": attachment.name,
        "media_type_hint": attachment.media_type_hint,
        "declared_size": attachment.size_bytes,
        "requested_at": requested_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    payload["request_digest"] = canonical_digest(payload)
    return ChannelAttachmentAdmissionRequest.model_validate(payload)


def _semantic_context(
    *,
    principal_ref: str,
    conversation_ref: str,
    receipts: tuple[ChannelAttachmentTerminalReceipt, ...],
) -> SemanticDocumentContext:
    citations = tuple(receipt.citation for receipt in receipts)
    if any(citation is None for citation in citations):
        raise ChannelAttachmentHandoffError(
            "ready attachment omitted its citation", code="invalid_receipt"
        )
    exact_citations = cast(tuple[str, ...], citations)
    receipt_digests = tuple(receipt.receipt_digest for receipt in receipts)
    authorization_digest = canonical_digest(
        {
            "principal_ref": principal_ref,
            "conversation_ref": conversation_ref,
            "receipt_digests": list(receipt_digests),
        }
    )
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "source": SemanticDocumentContextSource.CHANNEL_ATTACHMENT,
        "principal_ref": principal_ref,
        "conversation_ref": conversation_ref,
        "citations": exact_citations,
        "authorization_digest": authorization_digest,
        "receipt_digests": receipt_digests,
        "execution_authority": False,
    }
    draft = SemanticDocumentContext.model_construct(
        schema_version="1.0.0",
        source=SemanticDocumentContextSource.CHANNEL_ATTACHMENT,
        principal_ref=principal_ref,
        conversation_ref=conversation_ref,
        citations=exact_citations,
        authorization_digest=authorization_digest,
        receipt_digests=receipt_digests,
        context_digest="sha256:" + "0" * 64,
        execution_authority=False,
    )
    payload["context_digest"] = semantic_document_context_digest(draft)
    return SemanticDocumentContext.model_validate(payload)


def _match_committed_content(
    receipt: ChannelAttachmentCommitReceipt, content: SpooledAttachment
) -> None:
    if receipt.observed_size != content.size_bytes or receipt.observed_sha256 != content.sha256:
        raise ChannelAttachmentHandoffError(
            "attachment commit receipt does not match captured content",
            code="commit_mismatch",
        )


def _match_terminal_content(
    receipt: ChannelAttachmentTerminalReceipt,
    *,
    observed_size: int,
    observed_sha256: str,
) -> None:
    if receipt.observed_size != observed_size or receipt.observed_sha256 != observed_sha256:
        raise ChannelAttachmentHandoffError(
            "attachment terminal receipt does not match captured content",
            code="terminal_mismatch",
        )


def _match_terminal_commit(
    terminal: ChannelAttachmentTerminalReceipt,
    commit: ChannelAttachmentCommitReceipt,
) -> None:
    if (
        terminal.commit_receipt_digest != commit.receipt_digest
        or terminal.upload_id != commit.upload_id
        or terminal.document_id != commit.document_id
        or terminal.version_id != commit.version_id
        or terminal.observed_size != commit.observed_size
        or terminal.observed_sha256 != commit.observed_sha256
    ):
        raise ChannelAttachmentHandoffError(
            "attachment terminal receipt does not match its commit",
            code="terminal_mismatch",
        )


def _match_terminal_progression(
    observed: ChannelAttachmentTerminalReceipt,
    baseline: ChannelAttachmentTerminalReceipt,
) -> None:
    if (
        observed.commit_receipt_digest != baseline.commit_receipt_digest
        or observed.upload_id != baseline.upload_id
        or observed.document_id != baseline.document_id
        or observed.version_id != baseline.version_id
        or observed.observed_size != baseline.observed_size
        or observed.observed_sha256 != baseline.observed_sha256
        or observed.requested_purpose is not baseline.requested_purpose
    ):
        raise ChannelAttachmentHandoffError(
            "attachment terminal progression changed its commit evidence",
            code="terminal_mismatch",
        )


__all__ = [
    "ChannelAttachmentIngestionResult",
    "ChannelAttachmentIngestor",
    "attachment_purpose",
]

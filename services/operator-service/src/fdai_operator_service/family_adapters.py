"""PostgreSQL and unavailable adapters for non-IAM Operator route families."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from typing import cast

from fdai_service_contracts import RuleSearchProjection, rule_search_query_digest
from starlette.exceptions import HTTPException

from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    ConversationUnavailableError,
    JsonObject,
    OutboxReceipt,
    StreamEvent,
)
from fdai_operator_service.families.operations.contracts import (
    EventProposal,
    ProjectionQuery,
    ProjectionUnavailableError,
    ProposalConflictError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
)
from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowOperation,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)
from fdai_operator_service.postgres_semantic_turn_store import rule_search_projection_key


class _ConversationEventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _ConversationEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite authoritative replay iterator."""


@dataclass(frozen=True, slots=True)
class PostgresConversationAdapters:
    """Read conversation projections and append typed proposals through PostgreSQL."""

    store: PostgresFamilyStore

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Read an explicitly materialized conversation projection."""
        try:
            payload = await self.store.read_projection(
                family="conversation",
                operation=query.operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ConversationResponse(body=cast(JsonObject, payload))

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Persist one proposal-only conversation intent with duplicate suppression."""
        try:
            stored = await self.store.append_proposal(
                family="conversation",
                operation=proposal.operation,
                principal_id=proposal.scope.subject_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return OutboxReceipt(
            proposal_id=stored.proposal_id,
            duplicate=stored.duplicate,
            response=ConversationResponse(
                body={
                    "accepted": True,
                    "proposal_id": stored.proposal_id,
                    "operation": proposal.operation,
                    "mode": "shadow",
                    "duplicate": stored.duplicate,
                },
                status_code=202,
            ),
        )

    async def open(self, request: ConversationStreamRequest) -> _ConversationEventIterator:
        """Open a finite replay over durable audit events for the requested operation."""
        try:
            after = int(request.after_event_id) if request.after_event_id is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID MUST be numeric") from exc
        try:
            records = await self.store.replay(
                stream=request.operation,
                principal_id=request.scope.subject_id,
                after_sequence=after,
                limit=500,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _ConversationEventIterator(
            tuple(
                StreamEvent(
                    event=record.event,
                    event_id=str(record.sequence),
                    data=cast(JsonObject, dict(record.data)),
                )
                for record in records
            )
        )


class UnavailableConversationAdapters:
    """Authenticate conversation routes before failing unavailable dependencies closed."""

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        del query
        raise ConversationUnavailableError("authoritative conversation projection is unavailable")

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        del proposal
        raise ConversationUnavailableError("conversation proposal outbox is unavailable")

    async def open(self, request: ConversationStreamRequest) -> _ConversationEventIterator:
        del request
        raise ConversationUnavailableError("conversation event stream is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresWorkflowAdapters:
    """Read workflow projections and durably queue shadow-only workflow proposals."""

    store: PostgresFamilyStore

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        """Read a revisioned authoritative workflow projection."""
        try:
            if request.operation is WorkflowOperation.RULE_SEARCH:
                query_digest = rule_search_query_digest(request.body)
                stored = await self.store.read_rule_search_projection(
                    principal_id=request.principal_id,
                    query_digest=query_digest,
                )
                projection_key = rule_search_projection_key(
                    request.principal_id,
                    query_digest,
                )
                payload_value = stored.get("data")
                if not isinstance(payload_value, dict):
                    raise HTTPException(
                        status_code=503,
                        detail="authoritative Rule search projection is malformed",
                    )
                payload = RuleSearchProjection.model_validate(payload_value).model_dump(mode="json")
            else:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=request.operation.value,
                )
                projection_key = f"operator-projection:workflow:{request.operation.value}"
                payload = dict(stored)
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        revision = stored.get("_revision", stored.get("revision"))
        if not isinstance(revision, str) or not revision:
            raise HTTPException(
                status_code=503,
                detail="authoritative workflow projection has no revision",
            )
        return WorkflowReadResult(
            payload=cast(JsonObject, payload),
            provenance=ProjectionProvenance(
                source_ref=f"state_kv:{projection_key}",
                revision=revision,
            ),
        )

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        """Append a typed workflow proposal without promoting or executing it."""
        try:
            stored = await self.store.append_proposal(
                family="workflow",
                operation=proposal.operation.value,
                principal_id=proposal.principal_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return WorkflowProposalReceipt(
            proposal_id=stored.proposal_id,
            revision=stored.accepted_at,
            duplicate=stored.duplicate,
        )


class UnavailableWorkflowAdapters:
    """Fail every workflow route closed while preserving route registration."""

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        del request
        raise HTTPException(status_code=503, detail="authoritative workflow store is unavailable")

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="workflow proposal outbox is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresOperationsAdapters:
    """Serve operations projections, proposals, replay, and signed webhook intake."""

    store: PostgresFamilyStore
    webhook_secret: str | None = None

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Read one explicitly materialized operations projection."""
        try:
            return await self.store.read_projection(
                family="operations",
                operation=query.operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        """Persist one event proposal without publishing or executing it."""
        try:
            stored = await self.store.append_proposal(
                family="operations",
                operation=proposal.operation,
                principal_id=proposal.principal_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise ProposalConflictError from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ProposalReceipt(
            request_id=stored.proposal_id,
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at=stored.accepted_at,
        )

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Replay authoritative audit events using the durable sequence watermark."""
        try:
            stored = await self.store.replay(
                stream=query.stream,
                principal_id=query.principal_id,
                after_sequence=query.after_sequence,
                limit=query.limit,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc
        events = tuple(ReplayEvent(record.sequence, record.event, record.data) for record in stored)
        watermark = events[-1].sequence if events else query.after_sequence or 0
        return ReplayBatch(events=events, watermark=watermark)

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Verify an HMAC signature before accepting webhook proposals."""
        del operation
        if self.webhook_secret is None:
            raise HTTPException(status_code=503, detail="webhook signing input is unavailable")
        supplied = headers.get("x-fdai-signature", "")
        if not supplied.startswith("sha256="):
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied[len("sha256=") :])


class UnavailableOperationsAdapters:
    """Fail all operations dependencies closed while keeping their routes visible."""

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        del query
        raise ProjectionUnavailableError

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="event proposal outbox is unavailable")

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        del query
        raise ProjectionUnavailableError

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        del operation, headers, body
        raise HTTPException(status_code=503, detail="webhook signing input is unavailable")


def _mapping(value: object) -> Mapping[str, object]:
    normalized = json.loads(json.dumps(value, default=str))
    if not isinstance(normalized, dict):
        raise ValueError("proposal payload MUST serialize to a JSON object")
    return cast(Mapping[str, object], normalized)


__all__ = [
    "PostgresConversationAdapters",
    "PostgresOperationsAdapters",
    "PostgresWorkflowAdapters",
    "UnavailableConversationAdapters",
    "UnavailableOperationsAdapters",
    "UnavailableWorkflowAdapters",
]

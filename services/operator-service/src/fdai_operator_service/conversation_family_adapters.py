"""Conversation PostgreSQL and unavailable family adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import cast

from fdai_service_contracts.test_context import TestContextApplication
from starlette.exceptions import HTTPException

from fdai_operator_service.families.conversation.background_tasks import (
    materialize_background_task,
    open_background_task_stream,
)
from fdai_operator_service.families.conversation.contracts import (
    ActionConfirmationBody,
    ConversationEventStream,
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    ConversationUnavailableError,
    JsonObject,
    OutboxReceipt,
    StreamEvent,
)
from fdai_operator_service.families.conversation.conversation_history import (
    materialize_conversation_history,
)
from fdai_operator_service.families.conversation.conversation_search import (
    materialize_conversation_search,
)
from fdai_operator_service.families.conversation.user_context import materialize_user_context
from fdai_operator_service.family_adapter_values import mapping as _mapping
from fdai_operator_service.incident_creation_confirmation import (
    IncidentCreationConfirmationService,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
)
from fdai_operator_service.postgres_test_context import PostgresTestContextOutbox


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
        if query.operation == "test-context.command-status":
            proposal_id = query.path_params.get("proposal_id")
            if not isinstance(proposal_id, str) or not 1 <= len(proposal_id) <= 256:
                raise HTTPException(status_code=400, detail="invalid context proposal identity")
            try:
                status = await PostgresTestContextOutbox(self.store).read_test_context_command(
                    proposal_id=proposal_id,
                    principal_id=query.scope.subject_id,
                )
            except PostgresFamilyStoreUnavailable as exc:
                raise HTTPException(
                    status_code=503, detail="context command status unavailable"
                ) from exc
            if status is None:
                raise HTTPException(status_code=404, detail="context command not found")
            if status.get("dispatch_status") not in {"pending", "claimed", "published", "rejected"}:
                raise HTTPException(status_code=503, detail="context command status is invalid")
            application = status.get("context_application")
            if application is not None:
                try:
                    applied = TestContextApplication.model_validate(application)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=503, detail="context application is invalid"
                    ) from exc
                if applied.actor_id != query.scope.subject_id:
                    raise HTTPException(
                        status_code=503, detail="context application principal mismatch"
                    )
                status = {
                    **status,
                    "context_application": applied.model_dump(
                        mode="json",
                        exclude={"actor_id", "target_ref", "access_scope_digest", "request_key"},
                    ),
                }
            return ConversationResponse(
                body=cast(
                    JsonObject,
                    {
                        **status,
                        "policy_application": "recorded" if application is not None else "unknown",
                        "current_authorization": "not_evaluated",
                        "execution_authority": False,
                    },
                )
            )
        try:
            background_response = await materialize_background_task(query, store=self.store)
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationUnavailableError(
                "authoritative background task projection is unavailable"
            ) from exc
        if background_response is not None:
            return background_response
        try:
            history_response = await materialize_conversation_history(query, store=self.store)
            if history_response is not None:
                return history_response
            search_response = await materialize_conversation_search(query, store=self.store)
            if search_response is not None:
                return search_response
            context_response = await materialize_user_context(query, store=self.store)
            if context_response is not None:
                return context_response
            payload = await self.store.read_projection(
                family="conversation",
                operation=query.operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ConversationResponse(body=cast(JsonObject, payload))

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Persist one proposal-only conversation intent with duplicate suppression."""
        if proposal.operation == "chat.action.confirm":
            return await IncidentCreationConfirmationService(self.store).confirm(
                scope=proposal.scope,
                body=ActionConfirmationBody.model_validate(proposal.body),
            )
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

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Open a finite replay over durable audit events for the requested operation."""
        try:
            background_stream = await open_background_task_stream(request, store=self.store)
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationUnavailableError(
                "authoritative background task stream is unavailable"
            ) from exc
        if background_stream is not None:
            return background_stream
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


__all__ = ["PostgresConversationAdapters", "UnavailableConversationAdapters"]

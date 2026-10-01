"""Resolve opaque result-handle references for semantic request continuity."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol, cast

from fdai_operator_service.families.conversation.contracts import ConversationProposal
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_service_contracts import ResultHandleRef, SemanticInvestigationContinuation
from fdai_service_contracts.adaptive_relationship import (
    AdaptiveRelationshipProof,
    AdaptiveRelationshipUnknownReason,
)

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


class ResultHandleRefReader(Protocol):
    async def latest_result_handle_refs(
        self,
        *,
        principal_id: str,
        session_id: str,
        limit: int = 4,
    ) -> tuple[ResultHandleRef, ...]: ...


class SemanticSessionLike(Protocol):
    session_id: str


class SemanticContinuationReader(Protocol):
    async def latest_semantic_investigation_continuation(
        self,
        *,
        principal_id: str,
        session_id: str,
    ) -> SemanticInvestigationContinuation | None: ...


class RelationshipResolutionLike(Protocol):
    proof: AdaptiveRelationshipProof | None
    reason: AdaptiveRelationshipUnknownReason | None


async def latest_result_handle_refs(
    store: object,
    *,
    principal_id: str,
    session_id: str,
    limit: int = 4,
) -> tuple[ResultHandleRef, ...]:
    """Return newest opaque result-handle refs from a semantic store when available."""

    if hasattr(store, "latest_result_handle_refs"):
        reader = cast(ResultHandleRefReader, store)
        return await reader.latest_result_handle_refs(
            principal_id=principal_id, session_id=session_id, limit=limit
        )
    repository = getattr(store, "_semantic_turn_store", None)
    fetch_all = getattr(repository, "_fetch_all", None)
    outbox_prefix = getattr(repository, "_outbox_prefix", None)
    outbox_namespace = getattr(repository, "_outbox_namespace", None)
    if not callable(fetch_all) or not isinstance(outbox_prefix, str):
        return ()
    return await _latest_postgres_refs(
        cast(FetchAll, fetch_all),
        result_prefix="operator-semantic-result:",
        request_prefix=outbox_prefix,
        outbox_namespace=str(outbox_namespace or ""),
        principal_id=principal_id,
        session_id=session_id,
        limit=limit,
    )


async def build_envelope_with_result_handles(
    *,
    builder: SemanticTurnEnvelopeBuilder,
    store: SemanticContinuationReader,
    proposal: ConversationProposal,
    semantic: SemanticSessionLike,
    relationship: RelationshipResolutionLike,
) -> tuple[ConversationProposal, dict[str, object]]:
    """Rebuild the semantic envelope with continuation and recent handle references."""

    session_id = str(semantic.session_id)
    continuation = await store.latest_semantic_investigation_continuation(
        principal_id=proposal.scope.subject_id,
        session_id=session_id,
    )
    recent_handles = await latest_result_handle_refs(
        store, principal_id=proposal.scope.subject_id, session_id=session_id, limit=4
    )
    if continuation is not None:
        proposal = replace(
            proposal,
            body={**proposal.body, "turn_sequence": continuation.source_turn_sequence + 1},
        )
    return proposal, builder.build(
        proposal,
        investigation_continuation=continuation,
        recent_result_handles=recent_handles,
        relationship_proof=relationship.proof,
        relationship_unknown_reason=relationship.reason,
    )


async def _latest_postgres_refs(
    fetch_all: FetchAll,
    *,
    result_prefix: str,
    request_prefix: str,
    outbox_namespace: str,
    principal_id: str,
    session_id: str,
    limit: int,
) -> tuple[ResultHandleRef, ...]:
    if not 1 <= limit <= 4:
        raise ValueError("result handle ref limit MUST be in [1, 4]")
    rows = await fetch_all(
        """
        WITH result_candidates AS MATERIALIZED (
            SELECT result.key,
                   result.updated_at,
                   result.value ->> 'request_id' AS request_id,
                   result.value -> 'data' -> 'semantic_result' -> 'result_handle_ref'
                       AS result_handle_ref
              FROM state_kv AS result
             WHERE result.key LIKE %(result_prefix)s
               AND result.value ->> 'kind' = 'operator.semantic_result'
               AND result.value -> 'data' -> 'semantic_result' ->> 'session_id'
                   = %(session_id)s
               AND result.value -> 'data' -> 'semantic_result' ? 'result_handle_ref'
        ),
        principal_requests AS MATERIALIZED (
            SELECT request.value ->> 'request_id' AS request_id
              FROM state_kv AS request
             WHERE request.key LIKE %(request_prefix)s
               AND request.value ->> 'kind' = 'operator.semantic_turn'
               AND COALESCE(request.value ->> 'outbox_namespace', '') = %(outbox_namespace)s
               AND request.value ->> 'principal_id' = %(principal_id)s
        )
        SELECT result.result_handle_ref AS result_handle_ref
          FROM result_candidates AS result
          JOIN principal_requests AS request USING (request_id)
         ORDER BY result.updated_at DESC, result.key DESC
         LIMIT %(limit)s
        """,
        {
            "result_prefix": f"{result_prefix}%",
            "request_prefix": f"{request_prefix}%",
            "outbox_namespace": outbox_namespace,
            "principal_id": principal_id,
            "session_id": session_id,
            "limit": limit,
        },
    )
    return tuple(
        ResultHandleRef.model_validate(dict(cast(Mapping[str, object], row["result_handle_ref"])))
        for row in rows
        if isinstance(row.get("result_handle_ref"), Mapping)
    )


__all__ = ["build_envelope_with_result_handles", "latest_result_handle_refs"]

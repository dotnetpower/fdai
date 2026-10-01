"""Core-only successive relation-plan continuations for shadow reasoning."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind, canonical_json
from fdai_service_contracts.reasoning_handles import (
    KeysetCursor,
    NextBatchDescriptor,
    OrderingTerm,
    QueryContinuation,
    SortDirection,
)

from fdai.core.ontology_platform.query_execution import QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryTable

from .semantic_reasoning_compiler import CompiledBatch, GoalCompilation, GoalStatus

_EXPIRY_SECONDS = 15 * 60
_ORDERING = (OrderingTerm(field_name="batch_index", direction=SortDirection.ASC),)


class SuccessiveRelationContinuationInvalidError(Exception):
    """The opaque relation continuation cannot authorize another batch."""


class SuccessiveRelationGenerationChangedError(Exception):
    """The inventory generation changed before the successive plan completed."""


@dataclass(frozen=True, slots=True)
class SuccessiveRelationBinding:
    deployment_scope_digest: str
    principal_digest: str
    conversation_id: str
    purpose: str
    admitted_goal_digest: str
    plan_digest: str
    manifest_digest: str
    query_version_digest: str


@dataclass(frozen=True, slots=True)
class RelationEndpoint:
    endpoint_id: str
    endpoint_name: str
    link_type: str


@dataclass(frozen=True, slots=True)
class SuccessiveRelationPage:
    endpoints: tuple[RelationEndpoint, ...]
    remaining_batches: int
    continuation_ref: str | None
    complete: bool
    incomplete_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StoredSuccessiveRelationContinuation:
    continuation_ref: str
    continuation: QueryContinuation
    source_generation: str
    pending_batches: tuple[CompiledBatch, ...]
    listed_endpoints: tuple[RelationEndpoint, ...]


class SuccessiveRelationContinuationStore(Protocol):
    async def put(self, record: StoredSuccessiveRelationContinuation) -> None: ...

    async def get(self, continuation_ref: str) -> StoredSuccessiveRelationContinuation | None: ...

    async def delete(self, continuation_ref: str) -> None: ...


class InMemorySuccessiveRelationContinuationStore:
    def __init__(self) -> None:
        self._records: dict[str, StoredSuccessiveRelationContinuation] = {}

    async def put(self, record: StoredSuccessiveRelationContinuation) -> None:
        self._records[record.continuation_ref] = record

    async def get(self, continuation_ref: str) -> StoredSuccessiveRelationContinuation | None:
        return self._records.get(continuation_ref)

    async def delete(self, continuation_ref: str) -> None:
        self._records.pop(continuation_ref, None)


class SuccessiveRelationContinuationIssuer:
    """Store verified relation batches and hand clients only opaque references."""

    def __init__(
        self,
        *,
        store: SuccessiveRelationContinuationStore,
        binding: SuccessiveRelationBinding,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._binding = binding
        self._clock = clock or (lambda: datetime.now(UTC))

    async def start(
        self,
        *,
        goal: GoalCompilation,
        first_execution: QueryPlanExecution,
    ) -> SuccessiveRelationPage:
        if goal.status is not GoalStatus.COMPILED or not goal.batches:
            raise ValueError("successive relation continuation requires a compiled goal")
        first = goal.batches[0]
        source_generation = _execution_generation(first, first_execution)
        first_endpoints = relation_endpoints(first, first_execution)
        pending = goal.batches[1:]
        if not pending:
            return SuccessiveRelationPage(first_endpoints, 0, None, True)
        continuation_ref = _opaque_ref()
        await self._store.put(
            StoredSuccessiveRelationContinuation(
                continuation_ref=continuation_ref,
                continuation=self._continuation(
                    first=first,
                    next_batch=pending[0],
                    source_generation=source_generation,
                    listed_endpoints=first_endpoints,
                    remaining_batches=len(pending),
                ),
                source_generation=source_generation,
                pending_batches=pending,
                listed_endpoints=first_endpoints,
            )
        )
        return SuccessiveRelationPage(first_endpoints, len(pending), continuation_ref, False)

    async def next_batch(self, continuation_ref: str) -> CompiledBatch:
        record = await self._valid_record(continuation_ref)
        return record.pending_batches[0]

    async def complete_batch(
        self,
        *,
        continuation_ref: str,
        execution: QueryPlanExecution,
    ) -> SuccessiveRelationPage:
        record = await self._valid_record(continuation_ref)
        batch = record.pending_batches[0]
        # Only the pending batch's own verified plan may advance this continuation.
        if execution.plan_digest != batch.plan.plan_digest:
            raise SuccessiveRelationContinuationInvalidError
        source_generation = _execution_generation(batch, execution)
        if source_generation != record.source_generation:
            await self._store.delete(continuation_ref)
            raise SuccessiveRelationGenerationChangedError
        endpoints = relation_endpoints(batch, execution)
        listed = (*record.listed_endpoints, *endpoints)
        pending = record.pending_batches[1:]
        await self._store.delete(continuation_ref)
        if not pending:
            return SuccessiveRelationPage(endpoints, 0, None, True)
        next_ref = _opaque_ref()
        next_record = StoredSuccessiveRelationContinuation(
            continuation_ref=next_ref,
            continuation=record.continuation.model_copy(
                update={
                    "remaining_batches": len(pending),
                    "next_batch": _descriptor(pending[0]),
                    "listed_endpoint_digest": _endpoint_digest(listed),
                    "keyset_cursor": _batch_cursor(batch.index),
                }
            ),
            source_generation=record.source_generation,
            pending_batches=pending,
            listed_endpoints=listed,
        )
        await self._store.put(next_record)
        return SuccessiveRelationPage(endpoints, len(pending), next_ref, False)

    async def _valid_record(self, continuation_ref: str) -> StoredSuccessiveRelationContinuation:
        record = await self._store.get(continuation_ref)
        if record is None or _aware_utc(self._clock()) >= record.continuation.expires_at:
            raise SuccessiveRelationContinuationInvalidError
        continuation = record.continuation
        if (
            continuation.deployment_scope_digest != self._binding.deployment_scope_digest
            or continuation.principal_digest != self._binding.principal_digest
            or continuation.conversation_id != self._binding.conversation_id
            or continuation.purpose != self._binding.purpose
            or continuation.admitted_goal_digest != self._binding.admitted_goal_digest
            or continuation.plan_digest != self._binding.plan_digest
            or continuation.manifest_digest != self._binding.manifest_digest
            or continuation.query_version_digest != self._binding.query_version_digest
        ):
            raise SuccessiveRelationContinuationInvalidError
        return record

    def _continuation(
        self,
        *,
        first: CompiledBatch,
        next_batch: CompiledBatch,
        source_generation: str,
        listed_endpoints: tuple[RelationEndpoint, ...],
        remaining_batches: int,
    ) -> QueryContinuation:
        now = _aware_utc(self._clock())
        return QueryContinuation(
            deployment_scope_digest=self._binding.deployment_scope_digest,
            principal_digest=self._binding.principal_digest,
            conversation_id=self._binding.conversation_id,
            purpose=self._binding.purpose,
            admitted_goal_digest=self._binding.admitted_goal_digest,
            plan_digest=self._binding.plan_digest,
            manifest_digest=self._binding.manifest_digest,
            query_version_digest=self._binding.query_version_digest,
            window_start=now,
            window_end=now + timedelta(seconds=1),
            cutoff=now,
            ordering=_ORDERING,
            keyset_cursor=_batch_cursor(first.index),
            page_size=1,
            expires_at=now + timedelta(seconds=_EXPIRY_SECONDS),
            remaining_batches=remaining_batches,
            next_batch=_descriptor(next_batch),
            listed_endpoint_digest=_endpoint_digest(listed_endpoints),
        )


def relation_endpoints(
    batch: CompiledBatch, execution: QueryPlanExecution
) -> tuple[RelationEndpoint, ...]:
    endpoints: list[RelationEndpoint] = []
    link_types = _output_link_types(batch.plan)
    for node_id in batch.plan.output_node_ids:
        value = execution.results[node_id].value
        if not isinstance(value, QueryTable):
            raise ValueError("successive relation output MUST be a query table")
        link_type = link_types[node_id]
        for row in value.rows:
            properties = row.values.get("properties")
            name = properties.get("name") if isinstance(properties, dict) else None
            endpoints.append(
                RelationEndpoint(
                    endpoint_id=row.row_id,
                    endpoint_name=str(name or row.row_id),
                    link_type=link_type,
                )
            )
    return tuple(endpoints)


def _execution_generation(batch: CompiledBatch, execution: QueryPlanExecution) -> str:
    generations: set[str] = set()
    for node_id in batch.plan.output_node_ids:
        value = execution.results[node_id].value
        if not isinstance(value, QueryTable) or value.source_generation is None:
            raise ValueError("successive relation output generation is unavailable")
        generations.add(value.source_generation)
    if len(generations) != 1:
        raise ValueError("successive relation output generation is ambiguous")
    return next(iter(generations))


def _output_link_types(plan: OntologyQueryPlan) -> dict[str, str]:
    link_types: dict[str, str] = {}
    by_id = {node.node_id: node for node in plan.nodes}
    for node_id in plan.output_node_ids:
        node = by_id[node_id]
        if node.kind is not QueryNodeKind.RELATIONSHIP_TRAVERSAL:
            raise ValueError("successive relation output MUST be a traversal")
        arguments = json.loads(node.arguments_json)
        raw = arguments.get("link_types")
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], str):
            raise ValueError("successive relation traversal MUST name one LinkType")
        link_types[node_id] = raw[0]
    return link_types


def _descriptor(batch: CompiledBatch) -> NextBatchDescriptor:
    return NextBatchDescriptor(
        batch_id=f"batch-{batch.index + 1}",
        plan_digest=batch.plan.plan_digest,
        link_types=tuple(sorted(set(_output_link_types(batch.plan).values()))),
        depth_bound=_max_depth(batch.plan),
    )


def _max_depth(plan: OntologyQueryPlan) -> int:
    depths: list[int] = []
    for node in plan.nodes:
        if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
            value = json.loads(node.arguments_json).get("max_depth")
            if isinstance(value, int):
                depths.append(value)
    return max(depths or [1])


def _batch_cursor(index: int) -> KeysetCursor:
    return KeysetCursor(cursor_digest=_digest({"batch_index": index}))


def _endpoint_digest(endpoints: tuple[RelationEndpoint, ...]) -> str:
    return _digest(
        [
            {
                "endpoint_id": endpoint.endpoint_id,
                "link_type": endpoint.link_type,
            }
            for endpoint in endpoints
        ]
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _opaque_ref() -> str:
    return secrets.token_urlsafe(32)


def _aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("successive relation continuation time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "InMemorySuccessiveRelationContinuationStore",
    "RelationEndpoint",
    "StoredSuccessiveRelationContinuation",
    "SuccessiveRelationBinding",
    "SuccessiveRelationContinuationInvalidError",
    "SuccessiveRelationContinuationIssuer",
    "SuccessiveRelationContinuationStore",
    "SuccessiveRelationGenerationChangedError",
    "SuccessiveRelationPage",
    "relation_endpoints",
]

"""Bounded dependency-wave execution for verified ontology query plans."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    TaskStatus,
)

from .models import ObjectSetDefinition
from .object_sets import ObjectSetService

_MAX_CONCURRENCY = 8
_MAX_NODE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class QueryNodeResult:
    """One immutable result projection returned by a query-node handler."""

    value: object
    evidence_refs: tuple[str, ...] = ()


class QueryNodeHandler(Protocol):
    """Execute one already-verified query node without changing authority."""

    def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> Awaitable[QueryNodeResult]: ...


@dataclass(frozen=True, slots=True)
class QueryPlanExecution:
    """Terminal results and receipts for one exact verified query plan."""

    plan_digest: str
    status: str
    results: Mapping[str, QueryNodeResult]
    receipts: tuple[GoalTaskReceipt, ...]
    output_node_ids: tuple[str, ...]
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("query plan execution MUST NOT carry execution authority")


class OntologyQueryPlanExecutor:
    """Execute a closed query DAG in bounded dependency waves.

    Unknown handlers, failed dependencies, timeout, and cancellation are terminal
    typed outcomes. They never trigger another capability or a mutation fallback.
    """

    def __init__(
        self,
        *,
        handlers: Mapping[QueryNodeKind, QueryNodeHandler],
        max_concurrency: int = _MAX_CONCURRENCY,
        node_timeout_seconds: float = _MAX_NODE_TIMEOUT_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= max_concurrency <= _MAX_CONCURRENCY:
            raise ValueError(f"query concurrency MUST be in [1, {_MAX_CONCURRENCY}]")
        if not 0 < node_timeout_seconds <= _MAX_NODE_TIMEOUT_SECONDS:
            raise ValueError(f"query node timeout MUST be in (0, {_MAX_NODE_TIMEOUT_SECONDS}]")
        self._handlers = MappingProxyType(dict(handlers))
        self._max_concurrency = max_concurrency
        self._node_timeout_seconds = node_timeout_seconds
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        plan: OntologyQueryPlan,
        *,
        expected_release_digest: str,
        expected_role: str,
        expected_purpose: str,
        cancelled: asyncio.Event | None = None,
    ) -> QueryPlanExecution:
        """Execute a plan only when its release, role, and purpose still match."""

        if plan.ontology_release_digest != expected_release_digest:
            raise ValueError("ontology query plan targets a stale release")
        if plan.caller_role != expected_role:
            raise PermissionError("ontology query plan caller role changed")
        if plan.purpose != expected_purpose:
            raise PermissionError("ontology query plan purpose changed")

        pending = {node.node_id: node for node in plan.nodes}
        results: dict[str, QueryNodeResult] = {}
        terminal_statuses: dict[str, TaskStatus] = {}
        receipts: dict[str, GoalTaskReceipt] = {}
        semaphore = asyncio.Semaphore(self._max_concurrency)

        while pending:
            ready = tuple(
                node
                for node in pending.values()
                if all(dependency in terminal_statuses for dependency in node.depends_on)
            )
            if not ready:
                raise RuntimeError(
                    "verified ontology query plan has an unresolved dependency cycle"
                )

            runnable: list[OntologyQueryNode] = []
            for node in ready:
                blocked_by = tuple(
                    dependency
                    for dependency in node.depends_on
                    if terminal_statuses[dependency] is not TaskStatus.COMPLETED
                )
                if blocked_by:
                    receipt = self._terminal_receipt(
                        node,
                        status=TaskStatus.SKIPPED,
                        reason="dependency_not_completed",
                        blocked_by=blocked_by,
                    )
                    receipts[node.node_id] = receipt
                    terminal_statuses[node.node_id] = receipt.status
                    pending.pop(node.node_id)
                else:
                    runnable.append(node)

            if runnable:
                completed = await asyncio.gather(
                    *(
                        self._run_node(
                            node,
                            dependencies={key: results[key] for key in node.depends_on},
                            semaphore=semaphore,
                            cancelled=cancelled,
                        )
                        for node in runnable
                    )
                )
                for node, result, receipt in completed:
                    if result is not None:
                        results[node.node_id] = result
                    receipts[node.node_id] = receipt
                    terminal_statuses[node.node_id] = receipt.status
                    pending.pop(node.node_id)

        ordered_receipts = tuple(receipts[node.node_id] for node in plan.nodes)
        statuses = tuple(item.status for item in ordered_receipts)
        if all(status is TaskStatus.COMPLETED for status in statuses):
            status = "completed"
        elif any(status in {TaskStatus.FAILED, TaskStatus.TIMED_OUT} for status in statuses):
            status = "failed"
        elif any(status is TaskStatus.CANCELLED for status in statuses):
            status = "cancelled"
        else:
            status = "partial"
        return QueryPlanExecution(
            plan_digest=plan.plan_digest,
            status=status,
            results=MappingProxyType(results),
            receipts=ordered_receipts,
            output_node_ids=plan.output_node_ids,
        )

    async def _run_node(
        self,
        node: OntologyQueryNode,
        *,
        dependencies: Mapping[str, QueryNodeResult],
        semaphore: asyncio.Semaphore,
        cancelled: asyncio.Event | None,
    ) -> tuple[OntologyQueryNode, QueryNodeResult | None, GoalTaskReceipt]:
        started_at = self._aware_now()
        started = time.monotonic()
        if cancelled is not None and cancelled.is_set():
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.CANCELLED,
                    reason="request_cancelled",
                    started_at=started_at,
                    started_monotonic=started,
                ),
            )
        handler = self._handlers.get(node.kind)
        if handler is None:
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.UNAVAILABLE,
                    reason="capability_unavailable",
                    started_at=started_at,
                    started_monotonic=started,
                ),
            )
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    handler(node, MappingProxyType(dict(dependencies))),
                    timeout=self._node_timeout_seconds,
                )
        except TimeoutError:
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.TIMED_OUT,
                    reason="capability_timed_out",
                    started_at=started_at,
                    started_monotonic=started,
                ),
            )
        except (TypeError, ValueError, RuntimeError):
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.FAILED,
                    reason="capability_failed",
                    started_at=started_at,
                    started_monotonic=started,
                ),
            )
        if not isinstance(result, QueryNodeResult):
            raise TypeError("query node handler MUST return QueryNodeResult")
        return (
            node,
            result,
            self._receipt(
                node,
                status=TaskStatus.COMPLETED,
                reason=None,
                evidence_refs=result.evidence_refs,
                started_at=started_at,
                started_monotonic=started,
            ),
        )

    def _terminal_receipt(
        self,
        node: OntologyQueryNode,
        *,
        status: TaskStatus,
        reason: str,
        blocked_by: tuple[str, ...],
    ) -> GoalTaskReceipt:
        now = self._aware_now()
        return GoalTaskReceipt(
            task_id=f"query:{node.node_id}",
            goal_id=node.node_id,
            intent=node.kind.value,
            capability=f"query.{node.kind.value}",
            evidence_mode=GoalEvidenceMode.OPERATIONAL,
            status=status,
            duration_ms=0,
            depends_on=node.depends_on,
            reason=reason,
            blocked_by=blocked_by,
            started_at=now,
            completed_at=now,
        )

    def _receipt(
        self,
        node: OntologyQueryNode,
        *,
        status: TaskStatus,
        reason: str | None,
        started_at: datetime,
        started_monotonic: float,
        evidence_refs: tuple[str, ...] = (),
    ) -> GoalTaskReceipt:
        completed_at = self._aware_now()
        duration_ms = max(0, min(86_400_000, round((time.monotonic() - started_monotonic) * 1000)))
        return GoalTaskReceipt(
            task_id=f"query:{node.node_id}",
            goal_id=node.node_id,
            intent=node.kind.value,
            capability=f"query.{node.kind.value}",
            evidence_mode=GoalEvidenceMode.OPERATIONAL,
            status=status,
            duration_ms=duration_ms,
            depends_on=node.depends_on,
            reason=reason,
            evidence_refs=evidence_refs,
            started_at=started_at,
            completed_at=max(started_at, completed_at),
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("query executor clock MUST be timezone-aware")
        return value.astimezone(UTC)


class ObjectSetNodeHandler:
    """Materialize one ObjectSet node through the existing bounded service."""

    def __init__(self, service: ObjectSetService) -> None:
        self._service = service

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if dependencies:
            raise ValueError("object_set node MUST NOT consume dependency results")
        definition = ObjectSetDefinition.model_validate(node.arguments.get("definition"))
        materialization = await self._service.materialize(definition)
        evidence_refs = (
            f"ontology-object-set:{node.node_id}:{len(materialization.graph.objects)}",
        )
        return QueryNodeResult(value=materialization, evidence_refs=evidence_refs)


__all__ = [
    "ObjectSetNodeHandler",
    "OntologyQueryPlanExecutor",
    "QueryNodeHandler",
    "QueryNodeResult",
    "QueryPlanExecution",
]

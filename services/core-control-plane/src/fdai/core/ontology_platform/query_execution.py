"""Bounded dependency-wave execution for verified ontology query plans."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Protocol

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
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
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueryNodeResult:
    """One immutable result projection returned by a query-node handler."""

    value: object
    evidence_refs: tuple[str, ...] = ()
    authority: EvidenceAuthority | None = None
    authority_inputs: tuple[EvidenceAuthority, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryNodeProgress:
    """One observed query-node lifecycle transition."""

    node: OntologyQueryNode
    status: Literal["running"] | TaskStatus
    started_at: datetime
    step_index: int
    step_total: int
    receipt: GoalTaskReceipt | None = None
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("query node progress MUST NOT carry execution authority")
        if not 1 <= self.step_index <= self.step_total <= 32:
            raise ValueError("query node progress position is invalid")
        if (self.status == "running") != (self.receipt is None):
            raise ValueError("query node progress lifecycle is inconsistent")
        if self.receipt is not None and self.status is not self.receipt.status:
            raise ValueError("query node progress status MUST match its receipt")


class QueryProgressObserver(Protocol):
    """Observe best-effort query progress without controlling execution."""

    def __call__(self, progress: QueryNodeProgress) -> Awaitable[None]: ...


class QueryNodeHandler(Protocol):
    """Execute one already-verified query node without changing authority."""

    def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> Awaitable[QueryNodeResult]: ...


class QueryNodeHeldError(RuntimeError):
    """Stop one dependency branch with a stable no-authority hold reason."""

    def __init__(self, reason: str) -> None:
        if not reason or len(reason) > 128:
            raise ValueError("query node hold reason MUST be bounded and non-empty")
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class QueryPlanExecution:
    """Terminal results and receipts for one exact verified query plan."""

    plan_digest: str
    status: str
    results: Mapping[str, QueryNodeResult]
    receipts: tuple[GoalTaskReceipt, ...]
    output_node_ids: tuple[str, ...]
    execution_authority: Literal[False] = False

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
        expected_manifest_digest: str,
        expected_role: str,
        expected_purpose: str,
        cancelled: asyncio.Event | None = None,
        progress_observer: QueryProgressObserver | None = None,
    ) -> QueryPlanExecution:
        """Execute a plan only when its release, role, and purpose still match."""

        if plan.ontology_release_digest != expected_release_digest:
            raise ValueError("ontology query plan targets a stale release")
        if plan.semantic_catalog_digest != expected_manifest_digest:
            raise ValueError("ontology query plan targets a stale query manifest")
        if plan.caller_role != expected_role:
            raise PermissionError("ontology query plan caller role changed")
        if plan.purpose != expected_purpose:
            raise PermissionError("ontology query plan purpose changed")

        pending = {node.node_id: node for node in plan.nodes}
        results: dict[str, QueryNodeResult] = {}
        terminal_statuses: dict[str, TaskStatus] = {}
        receipts: dict[str, GoalTaskReceipt] = {}
        semaphore = asyncio.Semaphore(self._max_concurrency)
        step_positions = {
            node.node_id: (index, len(plan.nodes)) for index, node in enumerate(plan.nodes, start=1)
        }

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
                    await self._notify_progress(
                        QueryNodeProgress(
                            node=node,
                            status=receipt.status,
                            started_at=receipt.started_at,
                            step_index=step_positions[node.node_id][0],
                            step_total=step_positions[node.node_id][1],
                            receipt=receipt,
                        ),
                        progress_observer,
                    )
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
                            progress_observer=progress_observer,
                            step_index=step_positions[node.node_id][0],
                            step_total=step_positions[node.node_id][1],
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
        progress_observer: QueryProgressObserver | None,
        step_index: int,
        step_total: int,
    ) -> tuple[OntologyQueryNode, QueryNodeResult | None, GoalTaskReceipt]:
        started_at = self._aware_now()
        started = time.monotonic()
        await self._notify_progress(
            QueryNodeProgress(
                node=node,
                status="running",
                started_at=started_at,
                step_index=step_index,
                step_total=step_total,
            ),
            progress_observer,
        )
        node, result, receipt = await self._execute_node(
            node,
            dependencies=dependencies,
            semaphore=semaphore,
            cancelled=cancelled,
            started_at=started_at,
            started_monotonic=started,
        )
        await self._notify_progress(
            QueryNodeProgress(
                node=node,
                status=receipt.status,
                started_at=started_at,
                step_index=step_index,
                step_total=step_total,
                receipt=receipt,
            ),
            progress_observer,
        )
        return node, result, receipt

    async def _execute_node(
        self,
        node: OntologyQueryNode,
        *,
        dependencies: Mapping[str, QueryNodeResult],
        semaphore: asyncio.Semaphore,
        cancelled: asyncio.Event | None,
        started_at: datetime,
        started_monotonic: float,
    ) -> tuple[OntologyQueryNode, QueryNodeResult | None, GoalTaskReceipt]:
        if cancelled is not None and cancelled.is_set():
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.CANCELLED,
                    reason="request_cancelled",
                    started_at=started_at,
                    started_monotonic=started_monotonic,
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
                    started_monotonic=started_monotonic,
                ),
            )
        try:
            result = await self._invoke_with_deadline(
                handler,
                node=node,
                dependencies=dependencies,
                semaphore=semaphore,
                cancelled=cancelled,
            )
            if not isinstance(result, QueryNodeResult):
                raise TypeError("query node handler MUST return QueryNodeResult")
            result = _bind_result_authority(result, dependencies)
        except QueryNodeHeldError as error:
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.UNAVAILABLE,
                    reason=error.reason,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
            )
        except _QueryCancelledError:
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.CANCELLED,
                    reason="request_cancelled",
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
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
                    started_monotonic=started_monotonic,
                ),
            )
        except PermissionError:
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.UNAVAILABLE,
                    reason="authorization_denied",
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
            )
        except (TypeError, ValueError, RuntimeError) as error:
            _LOGGER.warning(
                "ontology_query_node_failed",
                extra={
                    "node_kind": node.kind.value,
                    "failure_type": type(error).__name__,
                },
            )
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.FAILED,
                    reason="capability_failed",
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
            )
        except Exception:  # noqa: BLE001 - provider failures become stable typed receipts
            _LOGGER.exception(
                "ontology_query_node_failed",
                extra={"node_id": node.node_id, "node_kind": node.kind.value},
            )
            return (
                node,
                None,
                self._receipt(
                    node,
                    status=TaskStatus.FAILED,
                    reason="capability_failed",
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                ),
            )
        return (
            node,
            result,
            self._receipt(
                node,
                status=TaskStatus.COMPLETED,
                reason=None,
                evidence_refs=result.evidence_refs,
                authority=result.authority,
                authority_inputs=result.authority_inputs,
                started_at=started_at,
                started_monotonic=started_monotonic,
            ),
        )

    async def _notify_progress(
        self,
        progress: QueryNodeProgress,
        observer: QueryProgressObserver | None,
    ) -> None:
        if observer is None:
            return
        _LOGGER.info(
            "ontology_query_progress_observed",
            extra={
                "node_kind": progress.node.kind.value,
                "status": str(progress.status),
            },
        )
        try:
            await observer(progress)
        except Exception:  # noqa: BLE001 - presentation progress cannot control query truth
            _LOGGER.warning(
                "ontology_query_progress_observer_failed",
                extra={
                    "node_id": progress.node.node_id,
                    "status": str(progress.status),
                },
            )

    async def _invoke_with_deadline(
        self,
        handler: QueryNodeHandler,
        *,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
        semaphore: asyncio.Semaphore,
        cancelled: asyncio.Event | None,
    ) -> QueryNodeResult:
        async def invoke() -> QueryNodeResult:
            async with semaphore:
                if cancelled is not None and cancelled.is_set():
                    raise _QueryCancelledError
                return await handler(node, MappingProxyType(dict(dependencies)))

        execution = asyncio.create_task(invoke())
        cancellation = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        waiters: set[asyncio.Task[object]] = {execution}
        if cancellation is not None:
            waiters.add(cancellation)
        done, pending = await asyncio.wait(
            waiters,
            timeout=self._node_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation is not None and cancellation in done:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            raise _QueryCancelledError
        if execution not in done:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            raise TimeoutError
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return execution.result()

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
        authority: EvidenceAuthority | None = None,
        authority_inputs: tuple[EvidenceAuthority, ...] = (),
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
            authority=authority,
            authority_inputs=authority_inputs,
            started_at=started_at,
            completed_at=max(started_at, completed_at),
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("query executor clock MUST be timezone-aware")
        return value.astimezone(UTC)


def _bind_result_authority(
    result: QueryNodeResult,
    dependencies: Mapping[str, QueryNodeResult],
) -> QueryNodeResult:
    dependency_authorities = {
        dependency.authority
        for dependency in dependencies.values()
        if dependency.authority is not None
    }
    scoped_inputs = {
        EvidenceAuthority.SERVER_ONTOLOGY_INSTANCE_PATH: (
            (
                EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
            ),
            {EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST},
        ),
        EvidenceAuthority.SERVER_RESOURCE_HEALTH: (
            (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
            {EvidenceAuthority.SERVER_INVENTORY_GRAPH},
        ),
        EvidenceAuthority.SERVER_OPERATIONAL_STATE_HISTORY: (
            (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
            {EvidenceAuthority.SERVER_INVENTORY_GRAPH},
        ),
    }
    scoped_contract = scoped_inputs.get(result.authority) if result.authority is not None else None
    if scoped_contract is not None:
        expected_inputs, expected_dependencies = scoped_contract
        if (
            result.authority_inputs != expected_inputs
            or dependency_authorities != expected_dependencies
        ):
            raise QueryNodeHeldError("evidence_authority_derivation_invalid")
        return result
    if result.authority_inputs:
        raise QueryNodeHeldError("evidence_authority_derivation_invalid")
    if len(dependency_authorities) > 1:
        raise QueryNodeHeldError("evidence_authority_conflict")
    dependency_authority = next(iter(dependency_authorities), None)
    if result.authority is None:
        return (
            replace(result, authority=dependency_authority)
            if dependency_authority is not None
            else result
        )
    if result.authority is EvidenceAuthority.SERVER_ONTOLOGY_QUERY:
        return (
            replace(result, authority=dependency_authority)
            if dependency_authority is not None
            else result
        )
    if dependency_authority is not None and dependency_authority is not result.authority:
        raise QueryNodeHeldError("evidence_authority_conflict")
    return result


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
        return QueryNodeResult(
            value=materialization,
            evidence_refs=evidence_refs,
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )


class _QueryCancelledError(Exception):
    """Internal control signal for one cancelled query node."""


__all__ = [
    "ObjectSetNodeHandler",
    "OntologyQueryPlanExecutor",
    "QueryNodeHeldError",
    "QueryNodeHandler",
    "QueryNodeResult",
    "QueryPlanExecution",
]

"""Async server producer for verified semantic read turns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from fdai_service_contracts.ontology_query import (
    IntentGraphEvidence,
    QueryNodeKind,
    project_intent_graph,
    project_intent_graph_evidence,
)

from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryPlanExecution
from fdai.core.ontology_platform.query_execution import QueryProgressObserver
from fdai.core.ontology_platform.query_values import QueryTable

from .intent_graph import build_intent_graph_evidence
from .semantic_planning import SemanticPlanningService
from .semantic_planning_cascade import SemanticPlanningEscalationPolicy
from .semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from .session import Principal, Turn

_PROGRESS_OBSERVER: ContextVar[QueryProgressObserver | None] = ContextVar(
    "semantic_query_progress_observer",
    default=None,
)


@contextmanager
def bind_semantic_query_progress_observer(
    observer: QueryProgressObserver,
) -> Iterator[None]:
    """Bind one invocation-scoped presentation observer without changing authority."""
    token = _PROGRESS_OBSERVER.set(observer)
    try:
        yield
    finally:
        _PROGRESS_OBSERVER.reset(token)


def _resolve_progress_observer(
    explicit: QueryProgressObserver | None,
) -> QueryProgressObserver | None:
    return explicit or _PROGRESS_OBSERVER.get()


@dataclass(frozen=True, slots=True)
class SemanticTurnResult:
    """One total semantic turn disposition and optional execution projections."""

    disposition: Literal[
        "answered",
        "direct_response",
        "clarification",
        "held",
        "unsupported",
        "action_draft",
        "cancelled",
    ]
    reason: str
    planning: SemanticPlanningOutcome
    execution: QueryPlanExecution | None = None
    intent_graph: dict[str, Any] | None = None
    intent_graph_evidence: dict[str, Any] | None = None
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("semantic turn result MUST NOT carry execution authority")
        has_execution = self.execution is not None
        has_projections = self.intent_graph is not None and self.intent_graph_evidence is not None
        if has_execution != has_projections:
            raise ValueError("semantic turn execution and projections MUST be present together")


class SemanticConversationRuntime:
    """Plan and execute an ordinary-language read through one verified DAG."""

    def __init__(
        self,
        *,
        planner: SemanticPlanningService,
        executor: OntologyQueryPlanExecutor | None = None,
        executor_factory: Callable[[Principal], OntologyQueryPlanExecutor] | None = None,
        purpose: str = "operations-review",
    ) -> None:
        if (executor is None) == (executor_factory is None):
            raise ValueError("semantic runtime requires exactly one executor binding")
        self._planner = planner
        if executor_factory is not None:
            self._executor_factory = executor_factory
        else:
            if executor is None:  # pragma: no cover - constructor invariant
                raise RuntimeError("semantic executor binding is unavailable")
            bound_executor = executor
            self._executor_factory = lambda _principal: bound_executor
        self._purpose = purpose

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
        progress_observer: QueryProgressObserver | None = None,
    ) -> SemanticTurnResult:
        """Terminate every accepted turn without invoking a compatibility parser."""

        planning = await asyncio.to_thread(
            self._planner.plan,
            utterance=utterance,
            prior_turns=prior_turns,
            principal=principal,
            purpose=self._purpose,
            bound_incident=bound_incident,
            bound_resource_context=bound_resource_context,
            bound_investigation_continuation=bound_investigation_continuation,
            escalation_policy=escalation_policy,
        )
        if planning.disposition is SemanticPlanningDisposition.DIRECT_RESPONSE:
            return _terminal("direct_response", planning.reason, planning)
        if planning.disposition is SemanticPlanningDisposition.CLARIFICATION:
            return _terminal("clarification", planning.reason, planning)
        if planning.disposition is SemanticPlanningDisposition.ACTION_DRAFT:
            return _terminal("action_draft", planning.reason, planning)
        if planning.disposition is SemanticPlanningDisposition.UNSUPPORTED:
            return _terminal("unsupported", planning.reason, planning)
        if planning.disposition is SemanticPlanningDisposition.UNAVAILABLE:
            return _terminal("held", planning.reason, planning)
        if planning.plan is None or planning.intent_graph is None:
            raise RuntimeError("verified semantic planning result is incomplete")
        executor = self._executor_factory(principal)
        if executor is None:  # pragma: no cover - constructor invariant
            raise RuntimeError("semantic executor binding is unavailable")
        execution = await executor.execute(
            planning.plan,
            expected_release_digest=planning.plan.ontology_release_digest,
            expected_manifest_digest=planning.plan.semantic_catalog_digest,
            expected_role=principal.role.value,
            expected_purpose=self._purpose,
            cancelled=cancelled,
            progress_observer=_resolve_progress_observer(progress_observer),
        )
        evidence: IntentGraphEvidence = build_intent_graph_evidence(
            graph=planning.intent_graph,
            plan=planning.plan,
            execution=execution,
        )
        disposition: Literal["answered", "held", "cancelled"]
        reason = f"semantic_execution_{execution.status}"
        if execution.status == "completed":
            if _query_output_incomplete(planning, execution):
                disposition = "held"
                reason = "semantic_evidence_incomplete"
            elif _current_relationship_mapping_unavailable(planning, execution):
                disposition = "held"
                reason = "semantic_current_relationship_mapping_unavailable"
            else:
                disposition = "answered"
        elif execution.status == "cancelled":
            disposition = "cancelled"
        else:
            disposition = "held"
        return SemanticTurnResult(
            disposition=disposition,
            reason=reason,
            planning=planning,
            execution=execution,
            intent_graph=project_intent_graph(planning.intent_graph),
            intent_graph_evidence=project_intent_graph_evidence(evidence),
        )


def _current_relationship_mapping_unavailable(
    planning: SemanticPlanningOutcome,
    execution: QueryPlanExecution,
) -> bool:
    """Hold current mapping coverage when any endpoint ObjectSet is empty."""

    frame = planning.frame
    plan = planning.plan
    if (
        frame is None
        or plan is None
        or frame.output_shape != "ontology_relationships"
        or frame.temporal_scope != {"kind": "current"}
    ):
        return False
    output_node_ids = set(plan.output_node_ids)
    endpoint_node_ids = {
        node.node_id
        for node in plan.nodes
        if node.kind is QueryNodeKind.OBJECT_SET and node.node_id in output_node_ids
    }
    return bool(endpoint_node_ids) and any(
        isinstance(node_result.value, QueryTable) and not node_result.value.rows
        for node_id in endpoint_node_ids
        if (node_result := execution.results.get(node_id)) is not None
    )


def _query_output_incomplete(
    planning: SemanticPlanningOutcome,
    execution: QueryPlanExecution,
) -> bool:
    """Hold a completed DAG when its authoritative output is explicitly incomplete."""
    plan = planning.plan
    if plan is None:
        return False
    return any(
        isinstance(result.value, QueryTable) and not result.value.complete
        for node_id in plan.output_node_ids
        if (result := execution.results.get(node_id)) is not None
    )


def _terminal(
    disposition: Literal[
        "direct_response",
        "clarification",
        "held",
        "unsupported",
        "action_draft",
    ],
    reason: str,
    planning: SemanticPlanningOutcome,
) -> SemanticTurnResult:
    return SemanticTurnResult(
        disposition=disposition,
        reason=reason,
        planning=planning,
    )


__all__ = [
    "bind_semantic_query_progress_observer",
    "SemanticConversationRuntime",
    "SemanticTurnResult",
]

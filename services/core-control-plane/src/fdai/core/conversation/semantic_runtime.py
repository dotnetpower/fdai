"""Async server producer for verified semantic read turns."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from fdai_service_contracts.ontology_query import (
    IntentGraphEvidence,
    project_intent_graph,
    project_intent_graph_evidence,
)

from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryPlanExecution

from .intent_graph import build_intent_graph_evidence
from .semantic_planning import SemanticPlanningService
from .semantic_planning_models import SemanticPlanningDisposition, SemanticPlanningOutcome
from .session import Principal, Turn


@dataclass(frozen=True, slots=True)
class SemanticTurnResult:
    """One total semantic turn disposition and optional execution projections."""

    disposition: Literal[
        "answered",
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
    ) -> SemanticTurnResult:
        """Terminate every accepted turn without invoking a compatibility parser."""

        planning = await asyncio.to_thread(
            self._planner.plan,
            utterance=utterance,
            prior_turns=prior_turns,
            principal=principal,
            purpose=self._purpose,
        )
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
        )
        evidence: IntentGraphEvidence = build_intent_graph_evidence(
            graph=planning.intent_graph,
            plan=planning.plan,
            execution=execution,
        )
        disposition: Literal["answered", "held", "cancelled"]
        if execution.status == "completed":
            disposition = "answered"
        elif execution.status == "cancelled":
            disposition = "cancelled"
        else:
            disposition = "held"
        return SemanticTurnResult(
            disposition=disposition,
            reason=f"semantic_execution_{execution.status}",
            planning=planning,
            execution=execution,
            intent_graph=project_intent_graph(planning.intent_graph),
            intent_graph_evidence=project_intent_graph_evidence(evidence),
        )


def _terminal(
    disposition: Literal["clarification", "held", "unsupported", "action_draft"],
    reason: str,
    planning: SemanticPlanningOutcome,
) -> SemanticTurnResult:
    return SemanticTurnResult(
        disposition=disposition,
        reason=reason,
        planning=planning,
    )


__all__ = [
    "SemanticConversationRuntime",
    "SemanticTurnResult",
]

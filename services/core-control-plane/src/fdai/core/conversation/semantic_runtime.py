"""Async server producer for verified semantic read turns."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Literal

from fdai_service_contracts.adaptive_answer import AdaptiveAnswer
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    IntentGraphEvidence,
    QueryNodeKind,
    project_intent_graph,
    project_intent_graph_evidence,
)

from fdai.core.ontology_platform import OntologyQueryPlanExecutor, QueryPlanExecution
from fdai.core.ontology_platform.query_execution import QueryProgressObserver
from fdai.core.ontology_platform.query_values import QueryTable

from .adaptive_call_scope import AdaptiveBudgetExceededError, bind_adaptive_model_budget
from .adaptive_models import AdaptiveEvidence
from .adaptive_service import AdaptiveConversationService, AdaptiveDeferred, AdaptiveUnavailable
from .adaptive_wait import await_adaptive_call
from .intent_graph import build_intent_graph_evidence, resolve_execution_authority
from .semantic_planning import SemanticPlanningService
from .semantic_planning_cascade import NO_T2_ESCALATION_POLICY, SemanticPlanningEscalationPolicy
from .semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
    SemanticOutputShape,
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
        "advisory_response",
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
    adaptive_answer: AdaptiveAnswer | None = None

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("semantic turn result MUST NOT carry execution authority")
        has_execution = self.execution is not None
        has_projections = self.intent_graph is not None and self.intent_graph_evidence is not None
        if has_execution != has_projections:
            raise ValueError("semantic turn execution and projections MUST be present together")
        if self.disposition == "advisory_response" and self.adaptive_answer is None:
            raise ValueError("advisory terminal requires exactly one adaptive answer")
        if self.adaptive_answer is not None and self.disposition not in {
            "advisory_response",
            "action_draft",
        }:
            raise ValueError("adaptive content requires an advisory or governed draft terminal")


class SemanticConversationRuntime:
    """Plan and execute an ordinary-language read through one verified DAG."""

    def __init__(
        self,
        *,
        planner: SemanticPlanningService | None = None,
        executor: OntologyQueryPlanExecutor | None = None,
        executor_factory: Callable[[Principal], OntologyQueryPlanExecutor] | None = None,
        purpose: str = "operations-review",
        function_bindings: Mapping[str, EvidenceAuthority] | None = None,
        adaptive_service: AdaptiveConversationService | None = None,
        verified_unavailable_reason: str | None = None,
    ) -> None:
        if (
            verified_unavailable_reason is not None
            and not 1 <= len(verified_unavailable_reason) <= 128
        ):
            raise ValueError("verified runtime unavailability must have a bounded reason")
        advisory_only = (
            planner is None
            and adaptive_service is not None
            and verified_unavailable_reason is not None
        )
        if not advisory_only and (executor is None) == (executor_factory is None):
            raise ValueError("semantic runtime requires exactly one executor binding")
        if planner is None and not advisory_only:
            raise ValueError(
                "semantic runtime requires a planner or explicit advisory-only binding"
            )
        if advisory_only and (executor is not None or executor_factory is not None):
            raise ValueError("advisory-only runtime cannot carry an executor")
        self._planner = planner
        self._verified_unavailable_reason = verified_unavailable_reason
        self._executor_factory: Callable[[Principal], OntologyQueryPlanExecutor] | None
        if advisory_only:
            self._executor_factory = None
        elif executor_factory is not None:
            self._executor_factory = executor_factory
        else:
            if executor is None:  # pragma: no cover - constructor invariant
                raise RuntimeError("semantic executor binding is unavailable")
            bound_executor = executor
            self._executor_factory = lambda _principal: bound_executor
        self._purpose = purpose
        self._function_bindings = MappingProxyType(dict(function_bindings or {}))
        self._adaptive = adaptive_service

    @property
    def function_bindings(self) -> Mapping[str, EvidenceAuthority]:
        """Return the immutable function-authority bindings for this runtime."""

        return self._function_bindings

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        locale: str = "en",
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
        progress_observer: QueryProgressObserver | None = None,
        target_agent: str = "Bragi",
        relationship: Mapping[str, object] | None = None,
    ) -> SemanticTurnResult:
        """Answer knowledge facets without bypassing the principal-scoped verified read path."""
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError

        async def verified(question: str) -> SemanticTurnResult:
            return await self._handle_verified(
                utterance=question,
                prior_turns=prior_turns,
                principal=principal,
                locale=locale,
                cancelled=cancelled,
                bound_incident=bound_incident,
                bound_resource_context=bound_resource_context,
                bound_investigation_continuation=bound_investigation_continuation,
                escalation_policy=escalation_policy,
                progress_observer=progress_observer,
                conversation_profile=(
                    self._adaptive.social_profile(target_agent, locale, relationship)
                    if self._adaptive is not None
                    else None
                ),
            )

        async def evidence(question: str) -> AdaptiveEvidence:
            result = await verified(question)
            if result.disposition != "answered" or result.execution is None:
                return AdaptiveEvidence(status="held", limitation=result.reason)
            values: list[object] = []
            refs: list[str] = []
            authorities: list[EvidenceAuthority] = []
            for node_id in result.execution.output_node_ids:
                node = result.execution.results.get(node_id)
                if node is None:
                    return AdaptiveEvidence(status="unavailable", limitation="missing_query_output")
                value = node.value
                values.append(
                    json.loads(value.canonical_json()) if isinstance(value, QueryTable) else value
                )
                refs.extend(node.evidence_refs)
                if node.authority is not None:
                    authorities.append(node.authority)
                authorities.extend(node.authority_inputs)
            try:
                content = json.dumps(values, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                return AdaptiveEvidence(
                    status="unavailable", limitation="unsupported_evidence_shape"
                )
            references = tuple(dict.fromkeys(refs))
            if (
                len(content) > 12000
                or len(references) > 12
                or not references
                or any(len(ref) > 256 for ref in references)
            ):
                return AdaptiveEvidence(
                    status="unavailable", limitation="adaptive_evidence_budget_or_refs"
                )
            return AdaptiveEvidence(
                status="answered",
                content=content,
                evidence_refs=references,
                authorities=tuple(dict.fromkeys(authorities)),
            )

        if (
            self._adaptive is not None
            and bound_incident is None
            and bound_investigation_continuation is None
            and escalation_policy != NO_T2_ESCALATION_POLICY
        ):
            outcome = await self._adaptive.respond(
                utterance=utterance,
                history=tuple(
                    {"direction": turn.direction, "content": turn.content} for turn in prior_turns
                ),
                locale=locale,
                target_agent=target_agent,
                relationship=relationship,
                read_evidence=evidence,
                cancelled=cancelled,
                allow_refinement=escalation_policy != NO_T2_ESCALATION_POLICY,
            )
            if isinstance(outcome, AdaptiveUnavailable):
                return SemanticTurnResult(
                    disposition="held",
                    reason=outcome.reason,
                    planning=SemanticPlanningOutcome(
                        disposition=SemanticPlanningDisposition.UNAVAILABLE,
                        reason=outcome.reason,
                        model_observations=outcome.observations,
                    ),
                )
            if isinstance(outcome, AdaptiveDeferred):
                needs_explanation = outcome.plan.action_requested and any(
                    goal.kind == "knowledge" for goal in outcome.plan.goals
                )
                try:
                    async with bind_adaptive_model_budget(
                        outcome.budget,
                        reserved_calls=2 if needs_explanation else 0,
                    ):
                        governed = await await_adaptive_call(
                            verified(utterance),
                            timeout=outcome.budget.remaining,
                            cancelled=cancelled,
                        )
                except (TimeoutError, AdaptiveBudgetExceededError):
                    return SemanticTurnResult(
                        disposition="held",
                        reason="adaptive_governed_budget_exhausted",
                        planning=SemanticPlanningOutcome(
                            disposition=SemanticPlanningDisposition.UNAVAILABLE,
                            reason="adaptive_governed_budget_exhausted",
                            model_observations=tuple(outcome.budget.observations),
                        ),
                    )
                recorded = {id(item) for item in outcome.budget.observations}
                outcome.budget.observations.extend(
                    item
                    for item in governed.planning.model_observations
                    if id(item) not in recorded
                )
                governed = replace(
                    governed,
                    planning=replace(
                        governed.planning,
                        model_observations=tuple(outcome.budget.observations),
                    ),
                )
                if governed.disposition != "action_draft" or not needs_explanation:
                    return governed
                explanation = await self._adaptive.resume_after_governed_draft(
                    outcome,
                    read_evidence=evidence,
                    cancelled=cancelled,
                    allow_refinement=escalation_policy != NO_T2_ESCALATION_POLICY,
                )
                return replace(
                    governed,
                    adaptive_answer=explanation.answer,
                    planning=replace(
                        governed.planning,
                        model_observations=explanation.observations,
                    ),
                )
            if outcome is not None:
                return SemanticTurnResult(
                    disposition="advisory_response",
                    reason="semantic_advisory_response",
                    planning=SemanticPlanningOutcome(
                        disposition=SemanticPlanningDisposition.ADVISORY_RESPONSE,
                        reason="semantic_advisory_response",
                        model_observations=outcome.observations,
                    ),
                    adaptive_answer=outcome.answer,
                )
        return await verified(utterance)

    async def _handle_verified(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        locale: str = "en",
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
        progress_observer: QueryProgressObserver | None = None,
        conversation_profile: Mapping[str, str] | None = None,
    ) -> SemanticTurnResult:
        """Terminate every accepted turn without invoking a compatibility parser."""
        if self._planner is None:
            reason = self._verified_unavailable_reason or "semantic_query_runtime_unavailable"
            return SemanticTurnResult(
                disposition="held",
                reason=reason,
                planning=SemanticPlanningOutcome(
                    disposition=SemanticPlanningDisposition.UNAVAILABLE,
                    reason=reason,
                ),
            )
        planning = await asyncio.to_thread(
            self._planner.plan,
            utterance=utterance,
            prior_turns=prior_turns,
            principal=principal,
            purpose=self._purpose,
            locale=locale,
            bound_incident=bound_incident,
            bound_resource_context=bound_resource_context,
            bound_investigation_continuation=bound_investigation_continuation,
            escalation_policy=escalation_policy,
            **(
                {"conversation_profile": conversation_profile}
                if conversation_profile is not None
                else {}
            ),
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
        executor = self._executor_factory(principal) if self._executor_factory is not None else None
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
            frame=planning.frame,
        )
        disposition: Literal["answered", "held", "cancelled"]
        reason = f"semantic_execution_{execution.status}"
        if execution.status == "completed":
            if _current_relationship_mapping_unavailable(planning, execution):
                disposition = "held"
                reason = "semantic_current_relationship_mapping_unavailable"
            else:
                _authority, authority_status = resolve_execution_authority(
                    execution,
                    frame=planning.frame,
                    plan=planning.plan,
                )
                if authority_status == "missing":
                    disposition = "held"
                    reason = "semantic_evidence_authority_missing"
                elif authority_status == "conflict":
                    disposition = "held"
                    reason = "semantic_evidence_authority_conflict"
                elif _query_output_incomplete(planning, execution):
                    disposition = "held"
                    reason = "semantic_evidence_incomplete"
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
    frame = planning.frame
    plan = planning.plan
    if (
        frame is None
        or plan is None
        or frame.output_shape != SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST
    ):
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

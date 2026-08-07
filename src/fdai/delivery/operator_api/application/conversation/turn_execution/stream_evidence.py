"""Resolve and project streamed conversation evidence before generation.

Responsibility:
Apply conversation policies, resolve parallel read-only evidence branches,
derive answer context, and emit ordered semantic progress events.

Boundary:
Accept prepared application values and mutate request-local evidence state.
SSE framing, heartbeat bytes, provider construction, and HTTP stay outside.

Authority and state:
This module has no approval, execution, or promotion authority and performs no
durable writes.

Dependencies:
Injected provider-neutral evidence resolvers plus application and projection
helpers for bounded request-local context.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.conversation.answer_plan import AnswerPlan
from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    render_system_health_answer,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
    resolve_parallel_chat_evidence,
)
from fdai.delivery.operator_api.application.conversation.evidence.enrichment import (
    _delegation_summary,
    _retrieval_source_previews,
    _with_behavior_evidence,
    _with_screen_scope,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    freshness_evidence_refs,
    render_evidence_freshness_answer,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import IntentGraph
from fdai.delivery.operator_api.application.conversation.planning import (
    AnswerPlanningDelegate,
    start_shadow_answer_planning,
)
from fdai.delivery.operator_api.application.conversation.policy import (
    with_assurance_policy,
    with_compiled_user_policy,
)
from fdai.delivery.operator_api.application.conversation.post_generation import (
    evidence_timing_status,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _concept_answer,
    _ontology_browse_answer,
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.operator_api.application.conversation.prompt_ontology import (
    _with_ontology_storage_contract,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    PreparedChatStreamRequest,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    uses_evidence_fast_path,
)
from fdai.delivery.operator_api.application.conversation.verification import AnswerVerification
from fdai.delivery.operator_api.application.conversation.vision_evidence import (
    vision_source_previews,
)
from fdai.delivery.operator_api.projections.conversation.document_evidence import (
    with_document_evidence,
)
from fdai.delivery.operator_api.projections.conversation.resource_context import (
    resource_followup_verification,
)
from fdai.delivery.operator_api.projections.conversation.screen_data import (
    render_screen_data_answer,
)
from fdai.delivery.operator_api.projections.conversation.stream_metrics import (
    record_enqueued_progress_metrics,
)
from fdai.delivery.operator_api.projections.conversation.terminal import TurnTimingRecorder
from fdai.delivery.operator_api.projections.conversation.trajectory import (
    TrajectoryDetailCollector,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.telemetry import ConversationProgressMetrics

from .models import StreamTurnEvent


@dataclass(frozen=True, slots=True)
class StreamEvidenceContext:
    request: PreparedChatStreamRequest
    semantic_plan: Any | None
    deterministic_followup: bool
    behavior_resolver: ChatBehaviorEvidenceResolver | None
    evidence_resolver: OperationalEvidenceResolverProtocol | None
    tool_resolver: ChatToolResolver | None
    planned_tool_resolver: PlannedChatToolResolver | None
    web_search_resolver: ChatWebSearchEvidenceResolver | None
    agent_delegate: AgentChatDelegate | None
    answer_planning_delegate: AnswerPlanningDelegate | None
    conversation_policy_store: ConversationPolicyStore | None
    conversation_assurance_runtime: ConversationPolicyRuntime | None
    progress_metrics: ConversationProgressMetrics | None
    turn_timing: TurnTimingRecorder
    trajectory_detail: TrajectoryDetailCollector
    started: float


@dataclass(slots=True)
class StreamEvidenceState:
    answer_plan: AnswerPlan
    enriched_context: dict[str, Any] | None = None
    planning_task: asyncio.Task[AnswerPlanningResult] | None = None
    delegation: Mapping[str, Any] | None = None
    evidence_fast_path: bool = False
    response_locale: str | None = None
    freshness_answer: str | None = None
    health_answer: str | None = None
    screen_answer: str | None = None
    concept_answer: str | None = None
    ontology_answer: str | None = None
    contextual_verification: AnswerVerification | None = None
    contextual_answer: str | None = None
    freshness_verification: AnswerVerification | None = None


async def resolve_stream_evidence(
    context: StreamEvidenceContext,
    state: StreamEvidenceState,
) -> AsyncIterator[StreamTurnEvent]:
    """Yield evidence progress and populate the request-local generation state."""

    request = context.request
    yield StreamTurnEvent(
        "status",
        {
            "phase": "evidence_resolving",
            "label": "Checking read-only evidence",
            "sources": _retrieval_source_previews(
                request.view_context,
                server_owned=False,
            ),
        },
    )
    vision_previews = vision_source_previews(request.view_context.get("_attachments"))
    if vision_previews:
        yield StreamTurnEvent(
            "status",
            {
                "phase": "vision_analyzing",
                "label": f"Analyzing {len(vision_previews)} attached image(s)",
                "sources": vision_previews,
            },
        )
    enriched_context = await with_compiled_user_policy(
        request.view_context,
        user_id=request.user_id,
        store=context.conversation_policy_store,
    )
    enriched_context = await with_assurance_policy(
        enriched_context,
        user_id=request.user_id,
        request_id=request.request_id,
        runtime=context.conversation_assurance_runtime,
    )
    enriched_context = with_document_evidence(
        enriched_context,
        request.document_evidence_refs,
    )
    enriched_context = _with_screen_scope(
        request.evidence_prompt,
        enriched_context,
        context.agent_delegate,
        conversation_context=request.conversation_context,
        target_agent=request.target_agent,
    )
    enriched_context = await _with_behavior_evidence(
        request.evidence_prompt,
        enriched_context,
        context.behavior_resolver,
    )
    progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
    evidence_outcomes: list[str] = []
    first_progress_recorded = False

    async def observe_progress(event: Mapping[str, Any]) -> None:
        nonlocal first_progress_recorded
        progress_event = dict(event)
        if progress_event.get("event") == "milestone":
            progress_event.setdefault("recorded_at", datetime.now(tz=UTC).isoformat())
        context.trajectory_detail.observe(progress_event)
        if progress_event.get("event") == "branch" and isinstance(
            progress_event.get("status"),
            str,
        ):
            evidence_outcomes.append(str(progress_event["status"]))
        if context.progress_metrics is not None and progress_queue.full():
            context.progress_metrics.increment("queue_saturation")
        await progress_queue.put(progress_event)
        if context.progress_metrics is not None:
            first_progress_recorded = record_enqueued_progress_metrics(
                context.progress_metrics,
                progress_event,
                elapsed_ms=max(0, int((time.monotonic() - context.started) * 1000)),
                first_progress_recorded=first_progress_recorded,
            )

    evidence_timing = context.turn_timing.begin("evidence")
    evidence_task = asyncio.create_task(
        resolve_parallel_chat_evidence(
            request_id=request.request_id,
            prompt=request.evidence_prompt,
            view_context=enriched_context,
            user_id=request.user_id,
            session_id=request.session_id,
            conversation_context=request.conversation_context,
            target_agent=request.target_agent,
            tool_resolver=context.tool_resolver,
            planned_tool_resolver=context.planned_tool_resolver,
            evidence_resolver=context.evidence_resolver,
            agent_delegate=context.agent_delegate,
            web_search_resolver=context.web_search_resolver,
            progress_observer=observe_progress,
            intent_graph=(
                context.semantic_plan if isinstance(context.semantic_plan, IntentGraph) else None
            ),
        )
    )
    try:
        while not evidence_task.done() or not progress_queue.empty():
            try:
                progress_event = await asyncio.wait_for(
                    progress_queue.get(),
                    timeout=0.25,
                )
            except TimeoutError:
                continue
            event_name = progress_event.pop("event", None)
            if event_name in {"activity", "milestone", "status", "branch"}:
                yield StreamTurnEvent(event_name, progress_event)
        enriched_context = await evidence_task
        context.turn_timing.complete(
            evidence_timing,
            status=evidence_timing_status(evidence_outcomes),
        )
    finally:
        if not evidence_task.done():
            evidence_task.cancel()
            with suppress(asyncio.CancelledError):
                await evidence_task

    enriched_context = _with_concept_evidence(request.evidence_prompt, enriched_context)
    enriched_context = _with_ontology_storage_contract(
        request.evidence_prompt,
        enriched_context,
    )
    state.answer_plan, state.planning_task = start_shadow_answer_planning(
        prompt=request.evidence_prompt,
        plan=state.answer_plan,
        delegate=(
            None
            if "_screen_scope" in enriched_context
            or "_ontology_storage_contract" in enriched_context
            or context.deterministic_followup
            or uses_evidence_fast_path(enriched_context)
            else context.answer_planning_delegate
        ),
    )
    enriched_context["_answer_plan"] = state.answer_plan.to_dict()
    state.enriched_context = enriched_context
    state.delegation = _delegation_summary(enriched_context)
    state.evidence_fast_path = uses_evidence_fast_path(enriched_context)
    state.response_locale = _response_locale(request.clean_prompt, enriched_context)
    state.freshness_answer = render_evidence_freshness_answer(
        request.clean_prompt,
        request.freshness_context,
        locale=state.response_locale,
    )
    state.health_answer = render_system_health_answer(
        enriched_context,
        locale=state.response_locale,
    )
    state.screen_answer = render_screen_data_answer(
        request.clean_prompt,
        enriched_context,
        locale=state.response_locale,
    )
    state.concept_answer = (
        _concept_answer(enriched_context, state.answer_plan)
        if state.response_locale is None
        else None
    )
    state.ontology_answer = _ontology_browse_answer(
        request.clean_prompt,
        enriched_context,
        locale=state.response_locale,
    )
    state.contextual_verification = (
        resource_followup_verification(enriched_context, request.resource_context)
        if request.resource_followup
        else None
    )
    state.contextual_answer = (
        state.contextual_verification.answer if state.contextual_verification is not None else None
    )
    state.freshness_verification = (
        AnswerVerification(
            status="verified",
            answer=state.freshness_answer,
            authority="server_evidence_freshness",
            checks_completed=1,
            checks_total=1,
            evidence_refs=freshness_evidence_refs(request.freshness_context),
            reason_code="evidence_freshness_grounded",
        )
        if state.freshness_answer is not None and request.freshness_context is not None
        else None
    )
    if vision_previews:
        yield StreamTurnEvent(
            "status",
            {
                "phase": "vision_grounded",
                "label": f"Grounded on {len(vision_previews)} attached image(s)",
                "completed": len(vision_previews),
                "total": len(vision_previews),
                "sources": vision_previews,
            },
        )
    has_operational_evidence = "_operational_evidence" in enriched_context
    yield StreamTurnEvent(
        "status",
        {
            "phase": "generating",
            "label": (
                "Evidence ready; composing bounded answer"
                if state.evidence_fast_path
                or state.ontology_answer is not None
                or state.health_answer is not None
                or state.screen_answer is not None
                else "Evidence ready; drafting answer"
            ),
            "authority": (
                "server_intent_graph"
                if isinstance(enriched_context.get("_intent_graph_evidence"), Mapping)
                and enriched_context["_intent_graph_evidence"].get("status") != "completed"
                else "server_read_model"
                if has_operational_evidence or state.health_answer is not None
                else "client_snapshot"
            ),
            "sources": _retrieval_source_previews(enriched_context, server_owned=True),
        },
    )


__all__ = [
    "StreamEvidenceContext",
    "StreamEvidenceState",
    "resolve_stream_evidence",
]

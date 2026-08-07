"""Coordinate one-shot JSON conversation turns outside HTTP transport.

Responsibility:
Coordinate the typed request, lifecycle, generation, and completion owners for
one authenticated JSON conversation turn.

Boundary:
Accept an authenticated principal and parsed JSON object, then return a typed
application result. HTTP requests, responses, exceptions, and status codes stay
in the route adapter.

Authority and state:
This service has no approval, execution, promotion, or provider-scope authority.
It coordinates request-local state and writes only through injected conversation
stores that already own those records.

Dependencies:
Provider-neutral conversation contracts plus focused lifecycle and generation
owners supplied with application, projection, persistence, and metering seams.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import ConversationImageStore
from fdai.delivery.handover_events import HandoverAvailabilityPublisher
from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnInput,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackend,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)
from fdai.delivery.operator_api.application.conversation.busy_input import (
    ChatTurnInterruptedError,
)
from fdai.delivery.operator_api.application.conversation.capabilities.action_context import (
    needs_action_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.conversation_context import (
    load_verified_prior_context,
    needs_conversation_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.current_time import (
    needs_current_time,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.compiler import (
    compile_inventory_query,
    inventory_query_requires_semantic_completion,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.followup import (
    contextualize_inventory_scope_followup,
    contextualize_inventory_screen_scope,
)
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    is_llm_usage_followup,
    needs_llm_usage,
)
from fdai.delivery.operator_api.application.conversation.capabilities.log_query import (
    needs_log_query,
    needs_log_query_context,
)
from fdai.delivery.operator_api.application.conversation.capabilities.subscription_health import (
    needs_subscription_health,
    needs_subscription_health_context,
)
from fdai.delivery.operator_api.application.conversation.evidence import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
    has_bound_incident_analysis_context,
    has_screen_incident_analysis_context,
    needs_operational_evidence,
    resolve_parallel_chat_evidence,
)
from fdai.delivery.operator_api.application.conversation.evidence.enrichment import (
    _with_behavior_evidence,
    _with_screen_scope,
)
from fdai.delivery.operator_api.application.conversation.freshness_context import (
    missing_evidence_freshness_context_evidence,
    needs_evidence_freshness_context,
    parse_evidence_freshness_context,
    render_evidence_freshness_answer,
)
from fdai.delivery.operator_api.application.conversation.intent_graph import (
    IntentGraph,
    IntentGraphPlanner,
    apply_intent_graph_to_answer_plan,
)
from fdai.delivery.operator_api.application.conversation.intents import is_topology_question
from fdai.delivery.operator_api.application.conversation.planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    start_shadow_answer_planning,
)
from fdai.delivery.operator_api.application.conversation.policy import (
    with_assurance_policy,
    with_compiled_user_policy,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _response_locale,
    _with_concept_evidence,
)
from fdai.delivery.operator_api.application.conversation.prompt_ontology import (
    _with_ontology_storage_contract,
)
from fdai.delivery.operator_api.application.conversation.request_preparation import (
    DEFAULT_CHAT_HISTORY_POLICY,
    AnswerPreferenceResolver,
    BackendChatHistoryCompressor,
    ChatDocumentEvidenceResolver,
    ChatHistoryPolicy,
    ModelPreferenceResolver,
    contextualize_resource_followup,
    missing_read_investigation_context_evidence,
    parse_conversation_context,
    parse_resource_context,
    resolve_chat_history_result,
    resolve_request_id,
    resolve_session_id,
    resolve_target_agent,
)
from fdai.delivery.operator_api.application.conversation.response_completion import (
    ResponseCompletionContext,
    complete_chat_response,
    metering_correlation_id,
    uses_evidence_fast_path,
)
from fdai.delivery.operator_api.application.conversation.review_submission import (
    PostTurnReviewSubmitter,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import (
    TurnPlanner,
    TurnTool,
    apply_turn_plan_to_answer_plan,
)
from fdai.delivery.operator_api.application.conversation.vision_evidence import (
    parse_vision_attachments,
)
from fdai.delivery.operator_api.projections.conversation.document_evidence import (
    with_document_evidence,
)
from fdai.delivery.operator_api.projections.conversation.terminal import (
    completed_replay_payload,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore
from fdai.shared.telemetry.correlation import with_correlation

from .json_turn import JsonTurnGenerator, response_completion_dependencies
from .lifecycle import JsonTurnLifecycle
from .models import JsonTurnExecutionError, JsonTurnExecutionResult, JsonTurnOutcome


class JsonTurnExecutionService:
    """Run one authenticated, parsed JSON conversation turn."""

    def __init__(
        self,
        *,
        backend: ChatBackend,
        behavior_resolver: ChatBehaviorEvidenceResolver | None = None,
        evidence_resolver: OperationalEvidenceResolverProtocol | None = None,
        tool_resolver: ChatToolResolver | None = None,
        planned_tool_resolver: PlannedChatToolResolver | None = None,
        web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
        agent_delegate: AgentChatDelegate | None = None,
        answer_planning_delegate: AnswerPlanningDelegate | None = None,
        conversation_policy_store: ConversationPolicyStore | None = None,
        conversation_assurance_runtime: ConversationPolicyRuntime | None = None,
        conversation_history_store: ConversationHistoryStore | None = None,
        conversation_image_store: ConversationImageStore | None = None,
        user_context_ontology_projector: UserContextOntologyProjector | None = None,
        model_preference_resolver: ModelPreferenceResolver | None = None,
        answer_preference_resolver: AnswerPreferenceResolver | None = None,
        post_turn_review_submitter: PostTurnReviewSubmitter | None = None,
        busy_input_coordinator: BusyInputCoordinator | None = None,
        document_evidence_resolver: ChatDocumentEvidenceResolver | None = None,
        turn_planner: TurnPlanner | IntentGraphPlanner | None = None,
        turn_tools: tuple[TurnTool, ...] | Callable[[], tuple[TurnTool, ...]] = (),
        handover_availability_publisher: HandoverAvailabilityPublisher | None = None,
        history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
        turn_service: ConversationTurnApplicationService | None = None,
    ) -> None:
        self._behavior_resolver = behavior_resolver
        self._evidence_resolver = evidence_resolver
        self._tool_resolver = tool_resolver
        self._planned_tool_resolver = planned_tool_resolver
        self._web_search_resolver = web_search_resolver
        self._agent_delegate = agent_delegate
        self._answer_planning_delegate = answer_planning_delegate
        self._conversation_policy_store = conversation_policy_store
        self._conversation_assurance_runtime = conversation_assurance_runtime
        self._conversation_history_store = conversation_history_store
        self._user_context_ontology_projector = user_context_ontology_projector
        self._model_preference_resolver = model_preference_resolver
        self._answer_preference_resolver = answer_preference_resolver
        self._post_turn_review_submitter = post_turn_review_submitter
        self._turn_service = (
            turn_service if turn_service is not None else ConversationTurnApplicationService()
        )
        history_compressor = BackendChatHistoryCompressor(
            backend=backend,
            max_summary_chars=history_policy.max_summary_chars,
        )
        self._lifecycle = JsonTurnLifecycle(
            turn_service=self._turn_service,
            conversation_history_store=conversation_history_store,
            conversation_image_store=conversation_image_store,
            user_context_ontology_projector=user_context_ontology_projector,
            busy_input_coordinator=busy_input_coordinator,
            document_evidence_resolver=document_evidence_resolver,
            turn_planner=turn_planner,
            turn_tools=turn_tools,
            handover_availability_publisher=handover_availability_publisher,
        )
        self._generator = JsonTurnGenerator(
            backend=backend,
            busy_input_coordinator=busy_input_coordinator,
            history_compressor=history_compressor,
            history_policy=history_policy,
        )
        self._history_compressor = history_compressor
        self._history_policy = history_policy

    async def execute(
        self,
        *,
        principal_id: str,
        body: dict[str, Any],
    ) -> JsonTurnExecutionResult:
        """Execute one parsed JSON turn without HTTP transport knowledge."""

        document_evidence_refs = await self._lifecycle.resolve_document_refs(body, principal_id)
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise _error("invalid_request", "prompt MUST be a non-empty string")
        try:
            session_id = resolve_session_id(body)
            request_id = resolve_request_id(body)
        except ValueError as exc:
            raise _error("invalid_request", str(exc)) from exc
        view_context = body.get("view_context")
        if view_context is None:
            view_context = {}
        if not isinstance(view_context, dict):
            raise _error("invalid_request", "view_context MUST be an object")
        for server_key in (
            "_answer_plan",
            "_turn_plan",
            "_inventory_screen_scope",
            "_resource_followup",
            "_verified_prior_context",
            "_attachments",
        ):
            view_context.pop(server_key, None)
        try:
            vision_attachments = parse_vision_attachments(body, request_id=request_id)
        except ValueError as exc:
            raise _error("invalid_request", str(exc)) from exc
        if vision_attachments:
            view_context["_attachments"] = [
                attachment.to_view_dict() for attachment in vision_attachments
            ]
        try:
            conversation_context = parse_conversation_context(body)
            target_agent = resolve_target_agent(body, conversation_context)
        except ValueError as exc:
            raise _error("invalid_request", str(exc)) from exc
        history_raw = body.get("history", [])
        if not isinstance(history_raw, list):
            raise _error("invalid_request", "history MUST be a list")
        history = _bounded_history(history_raw)

        clean_prompt = prompt.strip()
        turn_input = ConversationTurnInput(
            principal_id=principal_id,
            conversation_id=session_id,
            request_id=request_id,
            correlation_id=metering_correlation_id(principal_id, session_id),
            prompt=clean_prompt,
            response_locale=_response_locale(clean_prompt, view_context),
            target_agent=target_agent,
            evidence_refs=document_evidence_refs,
            history_turn_count=len(history),
            streaming=False,
        )
        await self._lifecycle.enforce_input_policy(
            principal_id=principal_id,
            session_id=session_id,
            request_id=request_id,
            clean_prompt=clean_prompt,
        )
        preferred_model = (
            await self._model_preference_resolver(principal_id)
            if self._model_preference_resolver is not None
            else None
        )
        answer_preferences = (
            await self._answer_preference_resolver(principal_id)
            if self._answer_preference_resolver is not None
            else None
        )
        with (
            with_correlation(metering_correlation_id(principal_id, session_id)),
            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
        ):
            history_result = await resolve_chat_history_result(
                store=self._conversation_history_store,
                principal_id=principal_id,
                conversation_id=session_id,
                client_history=history,
                compressor=self._history_compressor,
                policy=self._history_policy,
            )
            history = list(history_result.messages)
            history_metadata = history_result.metadata()
        prior_context = None
        if (
            needs_conversation_context(clean_prompt)
            or is_llm_usage_followup(clean_prompt)
            or needs_subscription_health_context(clean_prompt)
            or needs_log_query_context(clean_prompt)
            or needs_evidence_freshness_context(clean_prompt)
        ):
            prior_context = await load_verified_prior_context(
                store=self._conversation_history_store,
                principal_id=principal_id,
                conversation_id=session_id,
            )
            if prior_context is not None:
                view_context["_verified_prior_context"] = prior_context.to_dict()
        try:
            resource_context = parse_resource_context(body.get("resource_context"))
            freshness_context = parse_evidence_freshness_context(
                prior_context.evidence_freshness_context if prior_context is not None else None
            )
        except ValueError as exc:
            raise _error("invalid_request", str(exc)) from exc
        selector_hold = (
            None
            if needs_action_context(clean_prompt)
            or needs_conversation_context(clean_prompt)
            or needs_subscription_health_context(clean_prompt)
            else missing_read_investigation_context_evidence(clean_prompt, resource_context)
        )
        if selector_hold is None:
            selector_hold = missing_evidence_freshness_context_evidence(
                clean_prompt,
                freshness_context,
            )
        if selector_hold is not None:
            view_context["_read_investigation_context_hold"] = selector_hold
        freshness_answer = render_evidence_freshness_answer(
            clean_prompt,
            freshness_context,
            locale=_response_locale(clean_prompt, view_context),
        )
        evidence_prompt, resource_followup = contextualize_resource_followup(
            clean_prompt,
            resource_context,
        )
        if resource_followup:
            view_context["_resource_followup"] = {"authority": "selector_hint"}
        evidence_prompt, inventory_scope_followup = contextualize_inventory_scope_followup(
            evidence_prompt,
            history,
        )
        evidence_prompt, inventory_screen_scope_resolution = contextualize_inventory_screen_scope(
            evidence_prompt,
            view_context,
        )
        if inventory_screen_scope_resolution is not None:
            view_context["_inventory_screen_scope"] = inventory_screen_scope_resolution.to_context()
        compiled_inventory = (
            compile_inventory_query(evidence_prompt) if self._tool_resolver is not None else None
        )
        semantic_inventory_completion = compiled_inventory is not None and (
            inventory_query_requires_semantic_completion(
                compiled_inventory,
                prompt=evidence_prompt,
            )
        )
        deterministic_followup = _is_deterministic_followup(
            clean_prompt=clean_prompt,
            evidence_prompt=evidence_prompt,
            view_context=view_context,
            conversation_context=conversation_context,
            resource_followup=resource_followup,
            inventory_scope_followup=inventory_scope_followup,
            inventory_screen_scope=inventory_screen_scope_resolution is not None,
            selector_hold=selector_hold,
            compiled_inventory=compiled_inventory,
            freshness_answer=freshness_answer,
        )
        answer_plan = build_answer_plan(
            evidence_prompt,
            route_id=str(view_context.get("routeId") or "") or None,
            preferences=answer_preferences,
        )
        view_context["_answer_plan"] = answer_plan.to_dict()
        self._lifecycle.publish_handover_availability(principal_id, session_id)
        turn_execution = self._turn_service.start_turn(turn_input)
        active_turn = await self._lifecycle.begin_active_turn(
            principal_id=principal_id,
            session_id=session_id,
            request_id=request_id,
            turn_execution=turn_execution,
        )
        planning_task: asyncio.Task[Any] | None = None
        operator_turn = None
        try:
            semantic_plan = None
            try:
                if self._lifecycle.should_plan(
                    clean_prompt=clean_prompt,
                    vision_attachments=vision_attachments,
                    deterministic_followup=deterministic_followup,
                    semantic_inventory_completion=semantic_inventory_completion,
                ):
                    semantic_plan = await self._lifecycle.plan_turn(
                        clean_prompt=clean_prompt,
                        history=history,
                        view_context=view_context,
                        resource_context=resource_context,
                        conversation_context=conversation_context,
                        document_evidence_refs=document_evidence_refs,
                        request_id=request_id,
                    )
                    if semantic_plan is not None:
                        answer_plan = (
                            apply_intent_graph_to_answer_plan(answer_plan, semantic_plan)
                            if isinstance(semantic_plan, IntentGraph)
                            else apply_turn_plan_to_answer_plan(answer_plan, semantic_plan)
                        )
                        view_context["_answer_plan"] = answer_plan.to_dict()
                        view_context[
                            "_intent_graph"
                            if isinstance(semantic_plan, IntentGraph)
                            else "_turn_plan"
                        ] = semantic_plan.to_dict()
                operator_turn, replay = await self._lifecycle.persist_operator_turn(
                    principal_id=principal_id,
                    session_id=session_id,
                    request_id=request_id,
                    clean_prompt=clean_prompt,
                    document_evidence_refs=document_evidence_refs,
                    vision_attachments=vision_attachments,
                    history_metadata=history_metadata,
                )
                if replay is not None:
                    result = self._turn_service.complete_turn(
                        turn_execution,
                        completed_replay_payload(replay),
                    )
                    return JsonTurnExecutionResult(result.to_wire_payload())
                draft = self._lifecycle.confirmation_result(
                    semantic_plan=semantic_plan,
                    request_id=request_id,
                    session_id=session_id,
                    turn_execution=turn_execution,
                )
                if draft is not None:
                    return draft
                view_context = await with_compiled_user_policy(
                    view_context,
                    user_id=principal_id,
                    store=self._conversation_policy_store,
                )
                view_context = await with_assurance_policy(
                    view_context,
                    user_id=principal_id,
                    request_id=request_id,
                    runtime=self._conversation_assurance_runtime,
                )
                view_context = with_document_evidence(view_context, document_evidence_refs)
                view_context = _with_screen_scope(
                    evidence_prompt,
                    view_context,
                    self._agent_delegate,
                    conversation_context=conversation_context,
                    target_agent=target_agent,
                )
                view_context = await _with_behavior_evidence(
                    evidence_prompt,
                    view_context,
                    self._behavior_resolver,
                )

                async def ignore_evidence_progress(_event: Mapping[str, Any]) -> None:
                    return None

                view_context = await resolve_parallel_chat_evidence(
                    request_id=request_id,
                    prompt=evidence_prompt,
                    view_context=view_context,
                    user_id=principal_id,
                    session_id=session_id,
                    conversation_context=conversation_context,
                    target_agent=target_agent,
                    tool_resolver=self._tool_resolver,
                    planned_tool_resolver=self._planned_tool_resolver,
                    evidence_resolver=self._evidence_resolver,
                    agent_delegate=self._agent_delegate,
                    web_search_resolver=self._web_search_resolver,
                    progress_observer=ignore_evidence_progress,
                    intent_graph=(
                        semantic_plan if isinstance(semantic_plan, IntentGraph) else None
                    ),
                )
                view_context = _with_concept_evidence(evidence_prompt, view_context)
                view_context = _with_ontology_storage_contract(evidence_prompt, view_context)
                answer_plan, planning_task = start_shadow_answer_planning(
                    prompt=evidence_prompt,
                    plan=answer_plan,
                    delegate=(
                        None
                        if "_screen_scope" in view_context
                        or "_ontology_storage_contract" in view_context
                        or deterministic_followup
                        or uses_evidence_fast_path(view_context)
                        else self._answer_planning_delegate
                    ),
                )
                view_context["_answer_plan"] = answer_plan.to_dict()
            except Exception:
                await self._lifecycle.finish_active_turn(
                    principal_id,
                    session_id,
                    request_id,
                    active_turn,
                )
                active_turn = None
                raise

            started = time.monotonic()
            try:
                response_locale = _response_locale(clean_prompt, view_context)
                generated = await self._generator.generate(
                    principal_id=principal_id,
                    session_id=session_id,
                    clean_prompt=clean_prompt,
                    history=history,
                    history_metadata=history_metadata,
                    preferred_model=preferred_model,
                    view_context=view_context,
                    answer_plan=answer_plan,
                    active_turn=active_turn,
                    response_locale=response_locale,
                    resource_context=resource_context,
                    resource_followup=resource_followup,
                    freshness_context=freshness_context,
                    freshness_answer=freshness_answer,
                    document_evidence_refs=document_evidence_refs,
                )
                reply = generated.reply
                verification = generated.verification
                answer_plan = generated.answer_plan
                history_metadata = generated.history_metadata
            except ChatTurnInterruptedError:
                await cancel_planning(planning_task)
                payload = {
                    "detail": "chat turn interrupted",
                    "session_id": session_id,
                    "request_id": request_id,
                }
                interrupted = self._turn_service.terminate_turn(
                    turn_execution,
                    terminal_status=ConversationTurnTerminalStatus.CANCELLED,
                    code="chat_turn_interrupted",
                    detail=payload["detail"],
                    wire_payload=payload,
                )
                return JsonTurnExecutionResult(
                    interrupted.to_wire_payload(),
                    JsonTurnOutcome.INTERRUPTED,
                )
            except ChatBackendUnavailableError:
                await cancel_planning(planning_task)
                detail = "chat backend not configured on this deployment"
                self._turn_service.terminate_turn(
                    turn_execution,
                    terminal_status=ConversationTurnTerminalStatus.UNAVAILABLE,
                    code="chat_backend_unavailable",
                    detail=detail,
                    wire_payload={"detail": detail},
                )
                raise _error("backend_unavailable", detail) from None
            except ChatContentPolicyError as exc:
                await cancel_planning(planning_task)
                await self._lifecycle.record_content_policy_block(
                    exc=exc,
                    principal_id=principal_id,
                    session_id=session_id,
                    request_id=request_id,
                    operator_turn=operator_turn,
                    history_metadata=history_metadata,
                    turn_execution=turn_execution,
                )
                raise _error("content_policy_block", str(exc)) from exc
            except asyncio.CancelledError:
                await cancel_planning(planning_task)
                self._lifecycle.terminate_open_turn(
                    turn_execution,
                    ConversationTurnTerminalStatus.CANCELLED,
                    "chat_turn_cancelled",
                    "chat turn cancelled",
                )
                raise
            except Exception:
                await cancel_planning(planning_task)
                self._lifecycle.terminate_open_turn(
                    turn_execution,
                    ConversationTurnTerminalStatus.FAILED,
                    "chat_turn_failed",
                    "chat turn failed",
                )
                raise
            finally:
                await self._lifecycle.finish_active_turn(
                    principal_id,
                    session_id,
                    request_id,
                    active_turn,
                )
                active_turn = None
            try:
                terminal_payload = await complete_chat_response(
                    ResponseCompletionContext(
                        started=started,
                        reply=reply,
                        view_context=view_context,
                        verification=verification,
                        answer_plan=answer_plan,
                        planning_task=planning_task,
                        user_id=principal_id,
                        session_id=session_id,
                        request_id=request_id,
                        clean_prompt=clean_prompt,
                        history_metadata=history_metadata,
                        response_locale=response_locale,
                        resource_context=resource_context,
                        freshness_context=freshness_context,
                        conversation_history_store=self._conversation_history_store,
                        user_context_ontology_projector=self._user_context_ontology_projector,
                        post_turn_review_submitter=self._post_turn_review_submitter,
                        operator_turn=operator_turn,
                        turn_service=self._turn_service,
                        turn_execution=turn_execution,
                    ),
                    response_completion_dependencies(),
                )
                return JsonTurnExecutionResult(terminal_payload)
            except asyncio.CancelledError:
                self._lifecycle.terminate_open_turn(
                    turn_execution,
                    ConversationTurnTerminalStatus.CANCELLED,
                    "chat_turn_cancelled",
                    "chat turn cancelled",
                )
                raise
            except Exception:
                self._lifecycle.terminate_open_turn(
                    turn_execution,
                    ConversationTurnTerminalStatus.FAILED,
                    "chat_turn_failed",
                    "chat turn failed",
                )
                raise
        finally:
            await self._lifecycle.finish_active_turn(
                principal_id,
                session_id,
                request_id,
                active_turn,
            )


def _bounded_history(history_raw: list[Any]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for turn in history_raw:
        if isinstance(turn, dict):
            role = turn.get("role")
            content = turn.get("content")
            if isinstance(role, str) and isinstance(content, str):
                history.append({"role": role, "content": content})
    return history


def _is_deterministic_followup(
    *,
    clean_prompt: str,
    evidence_prompt: str,
    view_context: dict[str, Any],
    conversation_context: dict[str, str] | None,
    resource_followup: bool,
    inventory_scope_followup: bool,
    inventory_screen_scope: bool,
    selector_hold: Any | None,
    compiled_inventory: Any | None,
    freshness_answer: str | None,
) -> bool:
    return bool(
        resource_followup
        or has_bound_incident_analysis_context(clean_prompt, view_context, conversation_context)
        or has_screen_incident_analysis_context(clean_prompt, view_context)
        or inventory_screen_scope
        or inventory_scope_followup
        or selector_hold is not None
        or is_topology_question(evidence_prompt)
        or (
            compiled_inventory is not None
            and not inventory_query_requires_semantic_completion(
                compiled_inventory,
                prompt=evidence_prompt,
            )
        )
        or needs_subscription_health(evidence_prompt)
        or needs_log_query(evidence_prompt)
        or needs_action_context(evidence_prompt)
        or needs_conversation_context(evidence_prompt)
        or needs_llm_usage(evidence_prompt)
        or is_llm_usage_followup(evidence_prompt)
        or needs_operational_evidence(evidence_prompt, view_context)
        or needs_current_time(evidence_prompt)
        or freshness_answer is not None
    )


def _error(code: str, detail: str) -> JsonTurnExecutionError:
    return JsonTurnExecutionError(code=code, detail=detail)


__all__ = ["JsonTurnExecutionService"]

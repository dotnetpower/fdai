"""Read-only, screen-aware conversational route for the operator console.

Prompt, evidence, backend, and stream responsibilities live in sibling modules.
This module owns the JSON chat route and remains the compatibility import surface.
"""

# ruff: noqa: F401 - the original module intentionally re-exports extracted symbols

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.conversation.busy_input_coordinator import BusyInputCoordinator
from fdai.core.conversation_assurance import ConversationPolicyRuntime
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.handover_events import HandoverAvailabilityPublisher
from fdai.delivery.operator_api.routes.chat_action_context import (
    is_explicit_action_draft_request,
    needs_action_context,
)
from fdai.delivery.operator_api.routes.chat_answer_planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    planning_metadata,
    start_shadow_answer_planning,
)
from fdai.delivery.operator_api.routes.chat_answer_quality import (
    review_korean_narrator_answer,
    verify_quality_result,
)
from fdai.delivery.operator_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.operator_api.routes.chat_backend_common import (
    _COGNITIVE_SCOPE,
    _COMPLETION_TOKEN_PARAM_MODELS,
    _CONTENT_FILTER_MARKERS,
    _DIRECT_OVERRIDE,
    ChatBackend,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
    DisabledChatBackend,
    _completion_body_params,
    _default_chat_http_client,
    _raise_upstream_error,
    _reject_direct_override,
    _usage_summary,
)
from fdai.delivery.operator_api.routes.chat_backend_factory import (
    _build_routed_backend,
    _build_single_azure_backend,
    _find_resolved_models,
    _host_of,
    _resolve_disk_azure_backend,
    _search_roots,
    backend_from_env,
    describe_backend,
)
from fdai.delivery.operator_api.routes.chat_backend_openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.operator_api.routes.chat_backend_router import (
    _ROUTER_FAILURE_PENALTY_MS,
    _ROUTER_WARMUP_SAMPLES,
    _ROUTER_WINDOW_SIZE,
    LatencyRoutedChatBackend,
    _p50,
    _p95,
)
from fdai.delivery.operator_api.routes.chat_busy_input import (
    ChatTurnInterruptedError,
    answer_with_busy_input,
    await_with_interrupt,
)
from fdai.delivery.operator_api.routes.chat_content_policy import (
    answer_with_content_policy_recovery,
)
from fdai.delivery.operator_api.routes.chat_conversation_context import (
    load_verified_prior_context,
    needs_conversation_context,
)
from fdai.delivery.operator_api.routes.chat_current_time import needs_current_time
from fdai.delivery.operator_api.routes.chat_document_evidence import (
    ChatDocumentEvidenceResolver,
    merge_document_verification,
    resolve_document_refs,
    with_document_evidence,
)
from fdai.delivery.operator_api.routes.chat_evidence import needs_operational_evidence
from fdai.delivery.operator_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatBehaviorEvidenceResolver,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    PlannedChatToolResolver,
    _delegation_summary,
    _explicit_agent_requested,
    _retrieval_source_previews,
    _screen_incident_context,
    _tool_matches_current_route,
    _web_search_summary,
    _with_agent_evidence,
    _with_behavior_evidence,
    _with_operational_evidence,
    _with_screen_scope,
    _with_tool_evidence,
    _with_web_evidence,
)
from fdai.delivery.operator_api.routes.chat_evidence_pipeline import (
    has_bound_incident_analysis_context,
    has_screen_incident_analysis_context,
    resolve_parallel_chat_evidence,
)
from fdai.delivery.operator_api.routes.chat_freshness_context import (
    freshness_evidence_refs,
    missing_evidence_freshness_context_evidence,
    needs_evidence_freshness_context,
    parse_evidence_freshness_context,
    render_evidence_freshness_answer,
    response_evidence_freshness_context,
)
from fdai.delivery.operator_api.routes.chat_history import (
    append_assistant_turn,
    append_content_policy_receipt,
    append_operator_turn,
    completed_replay_payload,
    content_policy_replay_stage,
    replay_metadata,
)
from fdai.delivery.operator_api.routes.chat_history_context import (
    DEFAULT_CHAT_HISTORY_POLICY,
    BackendChatHistoryCompressor,
    ChatHistoryPolicy,
    resolve_chat_history_result,
)
from fdai.delivery.operator_api.routes.chat_intent_graph import (
    IntentGraph,
    IntentGraphPlanner,
    apply_intent_graph_to_answer_plan,
    draft_capability_available,
    plan_semantic_turn,
    planner_context_envelope,
)
from fdai.delivery.operator_api.routes.chat_intent_graph_execution import (
    public_intent_graph_evidence,
)
from fdai.delivery.operator_api.routes.chat_inventory_compiler import compile_inventory_query
from fdai.delivery.operator_api.routes.chat_inventory_followup import (
    contextualize_inventory_scope_followup,
    contextualize_inventory_screen_scope,
)
from fdai.delivery.operator_api.routes.chat_log_query import (
    needs_log_query,
    needs_log_query_context,
)
from fdai.delivery.operator_api.routes.chat_presentation import (
    adapt_answer_plan_for_presentation,
)
from fdai.delivery.operator_api.routes.chat_prompt import (
    _AGENT_EVIDENCE_DIRECTIVE,
    _AGENT_NAME_TOKEN,
    _CAPABILITIES,
    _CAPABILITY_INTENT,
    _COMPILED_USER_POLICY_KEY,
    _CONCEPT_DOMAIN,
    _CONCEPT_EVIDENCE_DIRECTIVE,
    _CONCEPT_INTENT,
    _CONCEPT_PHRASING,
    _DATA_WORD,
    _GLOSSARY,
    _GLOSSARY_ALIASES,
    _GLOSSARY_STOP,
    _HOW_TO_GET_INTENT,
    _KOREAN_TEXT,
    _LOCALE_TAG,
    _OPERATIONAL_EVIDENCE_DIRECTIVE,
    _ROLE_EXPLAIN_INTENT,
    _ROLE_TOKEN,
    _SCREEN_EXPLANATION_DIRECTIVE,
    _SYSTEM_PROMPT,
    _TOOL_EVIDENCE_DIRECTIVE,
    _WEB_EVIDENCE_DIRECTIVE,
    _WHO_TOKEN,
    DEFAULT_MAX_CONTEXT_BYTES,
    DEFAULT_MAX_EXPLANATION_ITEMS,
    DEFAULT_MAX_RECORDS_PER_KEY,
    _build_messages,
    _concept_answer,
    _extract_locale,
    _glossary_matches,
    _is_capability_query,
    _is_concept_query,
    _locale_directive,
    _ontology_browse_answer,
    _response_locale,
    _snapshot_json_capped,
    _trim_view_context,
    _with_concept_evidence,
)
from fdai.delivery.operator_api.routes.chat_prompt_ontology import _with_ontology_storage_contract
from fdai.delivery.operator_api.routes.chat_resource_context import (
    contextualize_resource_followup,
    missing_read_investigation_context_evidence,
    parse_resource_context,
    resource_followup_verification,
    response_resource_context,
)
from fdai.delivery.operator_api.routes.chat_route_common import (
    DEFAULT_MAX_CHAT_BODY_BYTES,
    DEFAULT_MAX_SESSION_ID_CHARS,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _conversation_context,
    _metering_correlation_id,
    _request_id,
    _session_id,
    _target_agent,
    _turn_metadata,
    _uses_evidence_fast_path,
    _with_assurance_policy,
    _with_compiled_user_policy,
    assurance_policy_summary,
)
from fdai.delivery.operator_api.routes.chat_screen_data import render_screen_data_answer
from fdai.delivery.operator_api.routes.chat_stream import (
    DEFAULT_STREAM_PATH,
    make_chat_stream_route,
)
from fdai.delivery.operator_api.routes.chat_stream_protocol import (
    _CHUNK_RE,
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import (
    needs_subscription_health,
    needs_subscription_health_context,
)
from fdai.delivery.operator_api.routes.chat_system_health import render_system_health_answer
from fdai.delivery.operator_api.routes.chat_topology_intent import is_topology_question
from fdai.delivery.operator_api.routes.chat_turn_plan import (
    TurnPlanner,
    TurnTool,
    apply_turn_plan_to_answer_plan,
)
from fdai.delivery.operator_api.routes.chat_verification import AnswerVerification, verify_answer
from fdai.delivery.operator_api.routes.chat_vision_evidence import parse_vision_attachments
from fdai.delivery.operator_api.routes.post_turn_review import (
    PostTurnReviewSubmission,
    PostTurnReviewSubmitter,
    explicit_corrections,
)
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError
from fdai.shared.providers.user_context import ConversationHistoryStore, UserContextConflictError
from fdai.shared.telemetry.correlation import with_correlation

_LOG = logging.getLogger(__name__)


DEFAULT_ROUTE_PATH: Final[str] = "/chat"


def make_chat_health_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    path: str = "/chat/health",
) -> Route:
    """Return a ``GET`` health-check route describing the chat backend.

    The FE polls this once at deck-open time so the header can render
    ``LLM ready · gpt-4o-mini`` (or the disabled/fallback equivalent)
    without having to speculatively hit ``/chat`` first.
    """

    async def handler(request: Request) -> JSONResponse:
        await authorize(request)
        descriptor = describe_backend(backend)
        web_descriptor = getattr(web_search_resolver, "descriptor", None)
        if web_descriptor is not None:
            descriptor["web_search"] = web_descriptor()
        else:
            descriptor["web_search"] = {"available": False}
        return JSONResponse(descriptor)

    return Route(path, handler, methods=["GET"])


def make_chat_route(
    *,
    backend: ChatBackend,
    authorize: AuthorizeFn,
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
    path: str = DEFAULT_ROUTE_PATH,
    max_body_bytes: int = DEFAULT_MAX_CHAT_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat`` route.

    The route is POST because the browser sends a body; it is still
    read-only in the FDAI sense (no state mutation, no privileged call).
    Reader role is required (enforced by the shared ``authorize`` fn).
    """

    history_compressor = BackendChatHistoryCompressor(
        backend=backend,
        max_summary_chars=history_policy.max_summary_chars,
    )

    async def handler(request: Request) -> JSONResponse:
        user_id = await authorize(request)

        # Bound the body up-front so a malicious page cannot inflate cost.
        # Preflight Content-Length so an attacker cannot force us to
        # buffer megabytes just to reject on `len(body_bytes)`.
        declared_len = request.headers.get("content-length")
        if declared_len is not None:
            try:
                if int(declared_len) > max_body_bytes:
                    raise HTTPException(status_code=413, detail="chat body too large")
            except ValueError:
                pass
        body_bytes = await request.body()
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=413, detail="chat body too large")
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")
        try:
            document_evidence_refs = await resolve_document_refs(
                body=body,
                principal_id=user_id,
                resolver=document_evidence_resolver,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DocumentAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail="document reference access denied") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
        view_context = body.get("view_context")
        if view_context is None:
            view_context = {}
        if not isinstance(view_context, dict):
            raise HTTPException(status_code=400, detail="view_context MUST be an object")
        view_context.pop("_answer_plan", None)
        view_context.pop("_turn_plan", None)
        view_context.pop("_inventory_screen_scope", None)
        view_context.pop("_resource_followup", None)
        view_context.pop("_verified_prior_context", None)
        # `_attachments` is a server-owned, validated field: never trust a
        # client-supplied one, then set it from the parsed inline images.
        view_context.pop("_attachments", None)
        try:
            vision_attachments = parse_vision_attachments(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if vision_attachments:
            view_context["_attachments"] = [a.to_view_dict() for a in vision_attachments]
        conversation_context = _conversation_context(body)
        target_agent = _target_agent(body, conversation_context)
        history_raw = body.get("history", [])
        if not isinstance(history_raw, list):
            raise HTTPException(status_code=400, detail="history MUST be a list")
        history: list[dict[str, str]] = []
        for turn in history_raw:
            if isinstance(turn, dict):
                role = turn.get("role")
                content = turn.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    history.append({"role": role, "content": content})

        clean_prompt = prompt.strip()
        try:
            _reject_direct_override(clean_prompt)
        except ChatContentPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session_id = _session_id(body)
        request_id = _request_id(body)
        if conversation_history_store is not None:
            try:
                replay_stage = await content_policy_replay_stage(
                    store=conversation_history_store,
                    principal_id=user_id,
                    conversation_id=session_id,
                    request_id=request_id,
                    content=clean_prompt,
                )
            except UserContextConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="chat request id conflicts with an existing turn",
                ) from exc
            if replay_stage is not None:
                raise HTTPException(
                    status_code=422,
                    detail="chat request blocked by content policy",
                )
        preferred_model = (
            await model_preference_resolver(user_id)
            if model_preference_resolver is not None
            else None
        )
        answer_preferences = (
            await answer_preference_resolver(user_id)
            if answer_preference_resolver is not None
            else None
        )
        with (
            with_correlation(_metering_correlation_id(user_id, session_id)),
            with_invocation_scope(InvocationScope.OPERATOR_CHAT),
        ):
            history_result = await resolve_chat_history_result(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                client_history=history,
                compressor=history_compressor,
                policy=history_policy,
            )
            history = list(history_result.messages)
            history_metadata = history_result.metadata()
        prior_context = None
        if (
            needs_conversation_context(clean_prompt)
            or needs_subscription_health_context(clean_prompt)
            or needs_log_query_context(clean_prompt)
            or needs_evidence_freshness_context(clean_prompt)
        ):
            prior_context = await load_verified_prior_context(
                store=conversation_history_store,
                principal_id=user_id,
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
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        selector_hold = (
            None
            if needs_action_context(clean_prompt) or needs_subscription_health_context(clean_prompt)
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
        deterministic_followup = (
            resource_followup
            or (
                has_bound_incident_analysis_context(
                    clean_prompt, view_context, conversation_context
                )
                or has_screen_incident_analysis_context(clean_prompt, view_context)
            )
            or inventory_screen_scope_resolution is not None
            or inventory_scope_followup
            or selector_hold is not None
            or is_topology_question(evidence_prompt)
            or compile_inventory_query(evidence_prompt) is not None
            or needs_subscription_health(evidence_prompt)
            or needs_log_query(evidence_prompt)
            or needs_action_context(evidence_prompt)
            or needs_conversation_context(evidence_prompt)
            or needs_operational_evidence(evidence_prompt, view_context)
            or needs_current_time(evidence_prompt)
            or freshness_answer is not None
        )
        answer_plan = build_answer_plan(
            evidence_prompt,
            route_id=str(view_context.get("routeId") or "") or None,
            preferences=answer_preferences,
        )
        view_context["_answer_plan"] = answer_plan.to_dict()
        if handover_availability_publisher is not None:
            task = asyncio.create_task(
                handover_availability_publisher.publish(
                    subject_ref=user_id,
                    session_id=session_id,
                )
            )
            task.add_done_callback(_log_handover_availability_failure)
        active_turn = None
        if busy_input_coordinator is not None:
            try:
                active_turn = await busy_input_coordinator.begin_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="conversation session already has an active turn",
                ) from exc
        try:
            operator_turn = None
            semantic_plan = None
            if turn_planner is not None and not deterministic_followup:
                try:
                    semantic_plan = await plan_semantic_turn(
                        turn_planner,
                        prompt=clean_prompt,
                        tools=turn_tools() if callable(turn_tools) else turn_tools,
                        history=history,
                        attachments=view_context.get("_attachments"),
                        context=planner_context_envelope(
                            view_context,
                            resource_context=resource_context,
                            conversation_context=conversation_context,
                            document_refs=document_evidence_refs,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - shadow plan degrades closed
                    _LOG.warning(
                        "chat turn planning unavailable: %s",
                        type(exc).__name__,
                        extra={"request_id": request_id},
                    )
                else:
                    answer_plan = (
                        apply_intent_graph_to_answer_plan(answer_plan, semantic_plan)
                        if isinstance(semantic_plan, IntentGraph)
                        else apply_turn_plan_to_answer_plan(answer_plan, semantic_plan)
                    )
                    view_context["_answer_plan"] = answer_plan.to_dict()
                    view_context[
                        "_intent_graph" if isinstance(semantic_plan, IntentGraph) else "_turn_plan"
                    ] = semantic_plan.to_dict()
            if conversation_history_store is not None:
                try:
                    operator_turn = await append_operator_turn(
                        store=conversation_history_store,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        content=clean_prompt,
                        recorded_at=datetime.now(tz=UTC),
                        metadata={
                            "document_refs": list(document_evidence_refs),
                            **history_metadata,
                        },
                        ontology_projector=user_context_ontology_projector,
                    )
                except UserContextConflictError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail="chat request id conflicts with an existing turn",
                    ) from exc
                completed_turn = await conversation_history_store.get_turn_by_idempotency(
                    principal_id=user_id,
                    idempotency_key=f"{request_id}:assistant",
                )
                if completed_turn is not None:
                    if busy_input_coordinator is not None and active_turn is not None:
                        await busy_input_coordinator.finish_turn(
                            session_id=session_id,
                            turn_id=request_id,
                            principal_id=user_id,
                        )
                    return JSONResponse(completed_replay_payload(completed_turn))
            if semantic_plan is not None and semantic_plan.requires_confirmation:
                if isinstance(semantic_plan, IntentGraph) and not draft_capability_available(
                    semantic_plan,
                    turn_tools() if callable(turn_tools) else turn_tools,
                ):
                    if busy_input_coordinator is not None and active_turn is not None:
                        await busy_input_coordinator.finish_turn(
                            session_id=session_id,
                            turn_id=request_id,
                            principal_id=user_id,
                        )
                    return JSONResponse(
                        {"detail": "draft capability is no longer available"},
                        status_code=409,
                    )
                if busy_input_coordinator is not None and active_turn is not None:
                    await busy_input_coordinator.finish_turn(
                        session_id=session_id,
                        turn_id=request_id,
                        principal_id=user_id,
                    )
                return JSONResponse(
                    {
                        "answer": "Review this action draft before submitting it.",
                        "model": "semantic-turn-planner",
                        "source": "action-draft",
                        "action_draft": semantic_plan.confirmation_payload(
                            request_id=request_id,
                            session_id=session_id,
                        ),
                    }
                )
            view_context = await _with_compiled_user_policy(
                view_context,
                user_id=user_id,
                store=conversation_policy_store,
            )
            view_context = await _with_assurance_policy(
                view_context,
                user_id=user_id,
                request_id=request_id,
                runtime=conversation_assurance_runtime,
            )
            view_context = with_document_evidence(view_context, document_evidence_refs)
            view_context = _with_screen_scope(
                evidence_prompt,
                view_context,
                agent_delegate,
                conversation_context=conversation_context,
                target_agent=target_agent,
            )
            view_context = await _with_behavior_evidence(
                evidence_prompt,
                view_context,
                behavior_resolver,
            )

            async def ignore_evidence_progress(_event: Mapping[str, Any]) -> None:
                return None

            view_context = await resolve_parallel_chat_evidence(
                request_id=request_id,
                prompt=evidence_prompt,
                view_context=view_context,
                user_id=user_id,
                session_id=session_id,
                conversation_context=conversation_context,
                target_agent=target_agent,
                tool_resolver=tool_resolver,
                planned_tool_resolver=planned_tool_resolver,
                evidence_resolver=evidence_resolver,
                agent_delegate=agent_delegate,
                web_search_resolver=web_search_resolver,
                progress_observer=ignore_evidence_progress,
                intent_graph=(semantic_plan if isinstance(semantic_plan, IntentGraph) else None),
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
                    or _uses_evidence_fast_path(view_context)
                    else answer_planning_delegate
                ),
            )
            view_context["_answer_plan"] = answer_plan.to_dict()
        except Exception:
            if busy_input_coordinator is not None and active_turn is not None:
                await busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
            raise

        # Wall-clock latency around the backend call - surfaced to the FE
        # so the deck can render a "gpt-4o-mini · 830ms" badge next to
        # each turn. Kept out of the backend Protocol so any implementer
        # (real, disabled, or a future latency-routed wrapper) benefits
        # without opting in.
        started = time.monotonic()
        try:
            response_locale = _response_locale(clean_prompt, view_context)
            health_answer = render_system_health_answer(
                view_context,
                locale=response_locale,
            )
            screen_answer = render_screen_data_answer(
                clean_prompt,
                view_context,
                locale=response_locale,
            )
            concept_answer = (
                _concept_answer(view_context, answer_plan) if response_locale is None else None
            )
            ontology_answer = _ontology_browse_answer(
                clean_prompt,
                view_context,
                locale=response_locale,
            )
            contextual_verification = (
                resource_followup_verification(view_context, resource_context)
                if resource_followup
                else None
            )
            freshness_verification = (
                AnswerVerification(
                    status="verified",
                    answer=freshness_answer,
                    authority="server_evidence_freshness",
                    checks_completed=1,
                    checks_total=1,
                    evidence_refs=freshness_evidence_refs(freshness_context),
                    reason_code="evidence_freshness_grounded",
                )
                if freshness_answer is not None and freshness_context is not None
                else None
            )
            if _uses_evidence_fast_path(view_context):
                with (
                    with_correlation(_metering_correlation_id(user_id, session_id)),
                    with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                ):
                    answer_plan = await await_with_interrupt(
                        adapt_answer_plan_for_presentation(
                            backend=backend,
                            prompt=clean_prompt,
                            plan=answer_plan,
                            view_context=view_context,
                        ),
                        active_turn=active_turn,
                    )
                view_context["_answer_plan"] = answer_plan.to_dict()
            reply: dict[str, Any]
            if freshness_verification is not None:
                verification = freshness_verification
                reply = {
                    "answer": verification.answer,
                    "model": "evidence-freshness",
                    "source": "evidence:freshness",
                    "verification": verification.to_dict(),
                }
            elif contextual_verification is not None:
                verification = contextual_verification
                reply = {
                    "answer": verification.answer,
                    "model": "heimdall-read-investigation",
                    "source": "evidence:read-investigation",
                    "verification": verification.to_dict(),
                }
            elif _uses_evidence_fast_path(view_context):
                canonical = verify_answer(
                    "",
                    view_context,
                    locale=_response_locale(clean_prompt, view_context),
                )
                verification = verify_answer(
                    canonical.answer,
                    view_context,
                    locale=_response_locale(clean_prompt, view_context),
                )
                reply = {
                    "answer": verification.answer,
                    "model": "evidence-verifier",
                    "source": f"evidence:{verification.status}",
                    "verification": verification.to_dict(),
                }
            elif ontology_answer is not None:
                verification = verify_answer(
                    ontology_answer,
                    view_context,
                    locale=response_locale,
                )
                reply = {
                    "answer": verification.answer,
                    "model": "ontology-snapshot",
                    "source": "evidence:ontology-snapshot",
                    "verification": verification.to_dict(),
                }
            elif health_answer is not None:
                verification = verify_answer(
                    health_answer,
                    view_context,
                    locale=response_locale,
                )
                reply = {
                    "answer": verification.answer,
                    "model": "read-model-health",
                    "source": "evidence:system-health",
                    "verification": verification.to_dict(),
                }
            elif screen_answer is not None:
                verification = verify_answer(
                    screen_answer,
                    view_context,
                    locale=response_locale,
                )
                reply = {
                    "answer": verification.answer,
                    "model": "bragi-screen-t0",
                    "source": "evidence:current-screen",
                    "verification": verification.to_dict(),
                }
            elif concept_answer is not None:
                verification = verify_answer(
                    concept_answer,
                    view_context,
                    locale=None,
                )
                reply = {
                    "answer": verification.answer,
                    "model": "concept-glossary",
                    "source": "evidence:fdai-glossary",
                    "verification": verification.to_dict(),
                }
            else:

                async def invoke_backend(
                    active_history: list[dict[str, str]],
                ) -> dict[str, Any]:
                    nonlocal history_metadata

                    async def invoke_raw(candidate_history: list[dict[str, str]]) -> dict[str, Any]:
                        if isinstance(backend, LatencyRoutedChatBackend):
                            return await backend.answer(
                                prompt=clean_prompt,
                                view_context=view_context,
                                history=candidate_history,
                                preferred_model=preferred_model,
                            )
                        return await backend.answer(
                            prompt=clean_prompt,
                            view_context=view_context,
                            history=candidate_history,
                        )

                    backend_reply, recovery = await answer_with_content_policy_recovery(
                        invoke=invoke_raw,
                        history=active_history,
                        compressor=history_compressor,
                        policy=history_policy,
                    )
                    if recovery is not None:
                        history_metadata = recovery.metadata()
                    return backend_reply

                with (
                    with_correlation(_metering_correlation_id(user_id, session_id)),
                    with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                ):
                    draft_reply = await answer_with_busy_input(
                        invoke=invoke_backend,
                        history=history,
                        coordinator=busy_input_coordinator,
                        active_turn=active_turn,
                    )
                provisional_answer = str(draft_reply.get("answer", ""))

                async def invoke_quality(
                    quality_prompt: str,
                    quality_context: dict[str, Any],
                ) -> dict[str, Any]:
                    if isinstance(backend, LatencyRoutedChatBackend):
                        return await backend.answer(
                            prompt=quality_prompt,
                            view_context=quality_context,
                            history=[],
                            preferred_model=str(draft_reply.get("model") or preferred_model or "")
                            or None,
                        )
                    return await backend.answer(
                        prompt=quality_prompt,
                        view_context=quality_context,
                        history=[],
                    )

                with (
                    with_correlation(_metering_correlation_id(user_id, session_id)),
                    with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                ):
                    quality = await await_with_interrupt(
                        review_korean_narrator_answer(
                            answer=provisional_answer,
                            view_context=view_context,
                            locale=response_locale,
                            invoke=invoke_quality,
                        ),
                        active_turn=active_turn,
                    )
                verification = verify_quality_result(
                    quality,
                    view_context,
                    locale=_response_locale(clean_prompt, view_context),
                )
                reply = {
                    **draft_reply,
                    "answer": verification.answer,
                    "answer_quality": quality.to_dict(),
                }
            verification = merge_document_verification(
                verification,
                document_evidence_refs,
            )
            reply = {
                **reply,
                "answer": verification.answer,
                "verification": verification.to_dict(),
            }
        except ChatTurnInterruptedError:
            await cancel_planning(planning_task)
            return JSONResponse(
                {
                    "detail": "chat turn interrupted",
                    "session_id": session_id,
                    "request_id": request_id,
                },
                status_code=409,
            )
        except ChatBackendUnavailableError:
            await cancel_planning(planning_task)
            raise HTTPException(
                status_code=501,
                detail="chat backend not configured on this deployment",
            ) from None
        except ChatContentPolicyError as exc:
            await cancel_planning(planning_task)
            if conversation_history_store is not None and operator_turn is not None:
                try:
                    await append_content_policy_receipt(
                        store=conversation_history_store,
                        principal_id=user_id,
                        conversation_id=session_id,
                        request_id=request_id,
                        stage=exc.stage,
                        recorded_at=datetime.now(tz=UTC),
                        history_metadata=history_metadata,
                    )
                except Exception as receipt_error:  # noqa: BLE001 - preserve policy response
                    _LOG.error(
                        "chat content-policy receipt failed: %s",
                        type(receipt_error).__name__,
                        extra={"request_id": request_id},
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="content policy receipt unavailable",
                    ) from receipt_error
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            await cancel_planning(planning_task)
            raise
        finally:
            if busy_input_coordinator is not None and active_turn is not None:
                await busy_input_coordinator.finish_turn(
                    session_id=session_id,
                    turn_id=request_id,
                    principal_id=user_id,
                )
        latency_ms = int((time.monotonic() - started) * 1000)
        answer_planning = await planning_metadata(planning_task)
        enriched: dict[str, Any] = dict(reply)
        delegation = _delegation_summary(view_context)
        if delegation is not None:
            enriched["delegation"] = delegation
        web_search = _web_search_summary(view_context)
        if web_search is not None:
            enriched["web_search"] = web_search
        enriched["latency_ms"] = latency_ms
        enriched["history_context"] = history_metadata
        enriched["answer_plan"] = answer_plan.to_dict()
        if isinstance(view_context.get("_intent_graph"), Mapping):
            enriched["intent_graph"] = dict(view_context["_intent_graph"])
        if isinstance(view_context.get("_intent_graph_evidence"), Mapping):
            graph_evidence = public_intent_graph_evidence(view_context["_intent_graph_evidence"])
            enriched["intent_graph_evidence"] = graph_evidence
            enriched["evidence_mode"] = graph_evidence.get("evidence_mode")
        policy_summary = assurance_policy_summary(view_context)
        if policy_summary is not None:
            enriched["conversation_policy"] = policy_summary
        if answer_planning is not None:
            enriched["answer_planning"] = answer_planning
        selected_resource = response_resource_context(view_context, resource_context)
        if selected_resource is not None:
            enriched["resource_context"] = selected_resource
        selected_freshness = response_evidence_freshness_context(view_context, freshness_context)
        if selected_freshness is not None:
            enriched["evidence_freshness_context"] = selected_freshness.to_dict()
        enriched["code_artifacts"] = [
            artifact.to_dict() for artifact in extract_grounded_code(verification.answer)
        ]
        if conversation_history_store is not None:
            assistant_turn = await append_assistant_turn(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                content=verification.answer,
                recorded_at=datetime.now(tz=UTC),
                metadata=replay_metadata(
                    model=str(reply.get("model") or "unknown"),
                    payload=enriched,
                    additional=_turn_metadata(
                        model=str(reply.get("model") or "unknown"),
                        view_context=view_context,
                        answer_planning=answer_planning,
                    )
                    | history_metadata,
                ),
                ontology_projector=user_context_ontology_projector,
            )
            if post_turn_review_submitter is not None and operator_turn is not None:
                post_turn_review_submitter.submit_nowait(
                    operator_turn=operator_turn,
                    assistant_turn=assistant_turn,
                    submission=PostTurnReviewSubmission(
                        validation_outcomes=(verification.status,),
                        evidence_refs=verification.evidence_refs,
                        explicit_corrections=explicit_corrections(clean_prompt),
                    ),
                )
        return JSONResponse(enriched)

    return Route(path, handler, methods=["POST"])


def _log_handover_availability_failure(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except Exception as exc:  # noqa: BLE001 - availability never blocks chat
        _LOG.warning("handover availability publish failed: %s", type(exc).__name__)


__all__ = [
    "AgentChatDelegate",
    "ChatBackend",
    "ChatWebSearchEvidenceResolver",
    "LatencyRoutedChatBackend",
    "backend_from_env",
    "describe_backend",
    "make_chat_health_route",
    "make_chat_route",
    "make_chat_stream_route",
]

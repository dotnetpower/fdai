"""Read-only, screen-aware conversational route for the operator console.

Prompt, evidence, backend, and stream responsibilities live in sibling modules.
This module owns the JSON chat route and remains the compatibility import surface.
"""

# ruff: noqa: F401 - the original module intentionally re-exports extracted symbols

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai.core.conversation.answer_plan import build_answer_plan
from fdai.core.metering import InvocationScope, with_invocation_scope
from fdai.core.python_task.grounded_code import extract_grounded_code
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.read_api.routes.chat_answer_planning import (
    AnswerPlanningDelegate,
    cancel_planning,
    planning_metadata,
    start_shadow_answer_planning,
)
from fdai.delivery.read_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.read_api.routes.chat_backend_common import (
    _COGNITIVE_SCOPE,
    _COMPLETION_TOKEN_PARAM_MODELS,
    _CONTENT_FILTER_MARKERS,
    _DIRECT_OVERRIDE,
    ChatBackend,
    ChatBackendUnavailableError,
    DisabledChatBackend,
    _completion_body_params,
    _default_chat_http_client,
    _raise_upstream_error,
    _reject_direct_override,
    _usage_summary,
)
from fdai.delivery.read_api.routes.chat_backend_factory import (
    _build_routed_backend,
    _build_single_azure_backend,
    _find_resolved_models,
    _host_of,
    _resolve_disk_azure_backend,
    _search_roots,
    backend_from_env,
    describe_backend,
)
from fdai.delivery.read_api.routes.chat_backend_openai import (
    OpenAiCompatibleChatBackend,
    OpenAiCompatibleChatBackendConfig,
)
from fdai.delivery.read_api.routes.chat_backend_router import (
    _ROUTER_FAILURE_PENALTY_MS,
    _ROUTER_WARMUP_SAMPLES,
    _ROUTER_WINDOW_SIZE,
    LatencyRoutedChatBackend,
    _p50,
    _p95,
)
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    AgentChatDelegate,
    ChatToolResolver,
    ChatWebSearchEvidenceResolver,
    OperationalEvidenceResolverProtocol,
    _delegation_summary,
    _explicit_agent_requested,
    _retrieval_source_previews,
    _tool_matches_current_route,
    _web_search_summary,
    _with_agent_evidence,
    _with_operational_evidence,
    _with_tool_evidence,
    _with_web_evidence,
)
from fdai.delivery.read_api.routes.chat_history import append_assistant_turn, append_operator_turn
from fdai.delivery.read_api.routes.chat_prompt import (
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
    DEFAULT_MAX_HISTORY_TURNS,
    DEFAULT_MAX_RECORDS_PER_KEY,
    _build_messages,
    _concept_answer,
    _extract_locale,
    _glossary_matches,
    _is_capability_query,
    _is_concept_query,
    _locale_directive,
    _response_locale,
    _snapshot_json_capped,
    _trim_view_context,
    _with_concept_evidence,
)
from fdai.delivery.read_api.routes.chat_route_common import (
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_HISTORY_ITEMS,
    DEFAULT_MAX_SESSION_ID_CHARS,
    AnswerPreferenceResolver,
    AuthorizeFn,
    ModelPreferenceResolver,
    _metering_correlation_id,
    _request_id,
    _session_id,
    _turn_metadata,
    _uses_evidence_fast_path,
    _with_compiled_user_policy,
)
from fdai.delivery.read_api.routes.chat_stream import (
    DEFAULT_STREAM_PATH,
    make_chat_stream_route,
)
from fdai.delivery.read_api.routes.chat_stream_protocol import (
    _CHUNK_RE,
    DEFAULT_STREAM_HEARTBEAT_S,
    _chunk_answer_for_stream,
    _sse,
    _sse_heartbeat,
    _with_sse_heartbeats,
)
from fdai.delivery.read_api.routes.chat_system_health import render_system_health_answer
from fdai.delivery.read_api.routes.chat_verification import verify_answer
from fdai.shared.providers.briefing import ConversationPolicyStore
from fdai.shared.providers.user_context import ConversationHistoryStore
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
    evidence_resolver: OperationalEvidenceResolverProtocol | None = None,
    tool_resolver: ChatToolResolver | None = None,
    web_search_resolver: ChatWebSearchEvidenceResolver | None = None,
    agent_delegate: AgentChatDelegate | None = None,
    answer_planning_delegate: AnswerPlanningDelegate | None = None,
    conversation_policy_store: ConversationPolicyStore | None = None,
    conversation_history_store: ConversationHistoryStore | None = None,
    user_context_ontology_projector: UserContextOntologyProjector | None = None,
    model_preference_resolver: ModelPreferenceResolver | None = None,
    answer_preference_resolver: AnswerPreferenceResolver | None = None,
    path: str = DEFAULT_ROUTE_PATH,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build the ``POST /chat`` route.

    The route is POST because the browser sends a body; it is still
    read-only in the FDAI sense (no state mutation, no privileged call).
    Reader role is required (enforced by the shared ``authorize`` fn).
    """

    async def handler(request: Request) -> JSONResponse:
        user_id = await authorize(request)
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

        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt MUST be a non-empty string")
        view_context = body.get("view_context")
        if view_context is None:
            view_context = {}
        if not isinstance(view_context, dict):
            raise HTTPException(status_code=400, detail="view_context MUST be an object")
        view_context.pop("_answer_plan", None)
        history_raw = body.get("history", [])
        if not isinstance(history_raw, list):
            raise HTTPException(status_code=400, detail="history MUST be a list")
        # Bound the input list BEFORE materializing dicts - a pathological
        # payload of 10k+ one-char turns would slip past the body-byte cap
        # (each turn is ~20 bytes) and force the interpreter to allocate a
        # huge intermediate list only to slice to the last 8.
        if len(history_raw) > DEFAULT_MAX_HISTORY_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=(f"history exceeds cap ({len(history_raw)} > {DEFAULT_MAX_HISTORY_ITEMS})"),
            )
        history: list[dict[str, str]] = []
        for turn in history_raw:
            if isinstance(turn, dict):
                role = turn.get("role")
                content = turn.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    history.append({"role": role, "content": content})

        clean_prompt = prompt.strip()
        _reject_direct_override(clean_prompt)
        answer_plan = build_answer_plan(
            clean_prompt,
            route_id=str(view_context.get("routeId") or "") or None,
            preferences=answer_preferences,
        )
        view_context["_answer_plan"] = answer_plan.to_dict()
        session_id = _session_id(body)
        request_id = _request_id(body)
        if conversation_history_store is not None:
            await append_operator_turn(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                content=clean_prompt,
                recorded_at=datetime.now(tz=UTC),
                ontology_projector=user_context_ontology_projector,
            )
        view_context = await _with_compiled_user_policy(
            view_context,
            user_id=user_id,
            store=conversation_policy_store,
        )
        view_context = await _with_tool_evidence(clean_prompt, view_context, tool_resolver)
        view_context = await _with_operational_evidence(
            clean_prompt, view_context, evidence_resolver
        )
        view_context = await _with_agent_evidence(
            clean_prompt,
            view_context,
            agent_delegate,
            user_id=user_id,
            session_id=session_id,
        )
        view_context = _with_concept_evidence(clean_prompt, view_context)
        view_context = await _with_web_evidence(
            clean_prompt,
            view_context,
            web_search_resolver,
        )
        answer_plan, planning_task = start_shadow_answer_planning(
            prompt=clean_prompt,
            plan=answer_plan,
            delegate=answer_planning_delegate,
        )
        view_context["_answer_plan"] = answer_plan.to_dict()

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
            concept_answer = (
                _concept_answer(view_context, answer_plan) if response_locale is None else None
            )
            if _uses_evidence_fast_path(view_context):
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
                reply: dict[str, Any] = {
                    "answer": verification.answer,
                    "model": "evidence-verifier",
                    "source": f"evidence:{verification.status}",
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
                with (
                    with_correlation(_metering_correlation_id(user_id, session_id)),
                    with_invocation_scope(InvocationScope.OPERATOR_CHAT),
                ):
                    if isinstance(backend, LatencyRoutedChatBackend):
                        reply = await backend.answer(
                            prompt=clean_prompt,
                            view_context=view_context,
                            history=history,
                            preferred_model=preferred_model,
                        )
                    else:
                        reply = await backend.answer(
                            prompt=clean_prompt,
                            view_context=view_context,
                            history=history,
                        )
                provisional_answer = str(reply.get("answer", ""))
                verification = verify_answer(
                    provisional_answer,
                    view_context,
                    locale=_response_locale(clean_prompt, view_context),
                )
                reply = {
                    **reply,
                    "answer": verification.answer,
                }
            reply = {
                **reply,
                "answer": verification.answer,
                "verification": verification.to_dict(),
            }
        except ChatBackendUnavailableError:
            await cancel_planning(planning_task)
            raise HTTPException(
                status_code=501,
                detail="chat backend not configured on this deployment",
            ) from None
        except Exception:
            await cancel_planning(planning_task)
            raise
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
        enriched["answer_plan"] = answer_plan.to_dict()
        if answer_planning is not None:
            enriched["answer_planning"] = answer_planning
        enriched["code_artifacts"] = [
            artifact.to_dict() for artifact in extract_grounded_code(verification.answer)
        ]
        if conversation_history_store is not None:
            await append_assistant_turn(
                store=conversation_history_store,
                principal_id=user_id,
                conversation_id=session_id,
                request_id=request_id,
                content=verification.answer,
                recorded_at=datetime.now(tz=UTC),
                metadata=_turn_metadata(
                    model=str(reply.get("model") or "unknown"),
                    view_context=view_context,
                    answer_planning=answer_planning,
                ),
                ontology_projector=user_context_ontology_projector,
            )
        return JSONResponse(enriched)

    return Route(path, handler, methods=["POST"])


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

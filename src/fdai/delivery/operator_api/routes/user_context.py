"""Principal-scoped user context, policy, and proactive briefing routes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.briefing import OpeningBriefingService, next_cron_run
from fdai.core.scheduler.continuation import (
    ContinuationAccess,
    ContinuationAccessDeniedError,
    ScheduledContinuationService,
    scheduled_result_to_typed_fact,
)
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.shared.providers.briefing import (
    BriefingConflictError,
    BriefingDeliveryMode,
    BriefingKind,
    BriefingRunStore,
    BriefingSpec,
    BriefingSubscription,
    BriefingSubscriptionStore,
    ConversationPolicyKind,
    ConversationPolicyRecord,
    ConversationPolicyStore,
)
from fdai.shared.providers.conversation_search import (
    ConversationSearch,
    ConversationSearchMode,
    ConversationSearchQuery,
    ConversationSearchScope,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledConversationAnchorStore,
    ScheduledResultOrigin,
)
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRole,
    UserContextConflictError,
    UserMemoryCategory,
    UserMemoryFact,
    UserMemoryStore,
    UserPreferenceRecord,
    UserPreferenceStore,
)

AuthorizeFn = Callable[[Request], Awaitable[str]]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _same_subscription_intent(
    existing: BriefingSubscription,
    requested: BriefingSubscription,
) -> bool:
    return (
        existing.name == requested.name
        and existing.spec == requested.spec
        and existing.cron_expression == requested.cron_expression
        and existing.timezone == requested.timezone
        and existing.delivery_modes == requested.delivery_modes
        and existing.channel_binding_ref == requested.channel_binding_ref
        and existing.max_lateness_seconds == requested.max_lateness_seconds
        and existing.continuation_mode is requested.continuation_mode
        and existing.continuation_origin == requested.continuation_origin
        and existing.continuation_ttl_seconds == requested.continuation_ttl_seconds
    )


@dataclass(frozen=True, slots=True)
class UserContextRoutesConfig:
    conversations: ConversationHistoryStore
    conversation_search: ConversationSearch
    preferences: UserPreferenceStore
    memories: UserMemoryStore
    policies: ConversationPolicyStore
    subscriptions: BriefingSubscriptionStore
    runs: BriefingRunStore
    opening_briefing: OpeningBriefingService
    ontology_projector: UserContextOntologyProjector | None = None
    continuations: ScheduledConversationAnchorStore | None = None
    continuation_service: ScheduledContinuationService | None = None
    clock: Callable[[], datetime] = _utc_now


def make_user_context_routes(
    *, config: UserContextRoutesConfig, authorize: AuthorizeFn
) -> tuple[Route, ...]:
    async def context(request: Request) -> Response:
        principal_id = await authorize(request)
        now = config.clock()
        preference = await config.preferences.get(principal_id=principal_id)
        memories = await config.memories.list_active(principal_id=principal_id, now=now)
        policies = await config.policies.list_for_principal(principal_id=principal_id)
        subscriptions = await config.subscriptions.list_for_principal(principal_id=principal_id)
        runs = await config.runs.list_for_principal(principal_id=principal_id, limit=50)
        conversations = await config.conversations.list_conversations(
            principal_id=principal_id, limit=50
        )
        latest_operator_turns = await config.conversations.latest_operator_turn_ids(
            principal_id=principal_id,
            conversation_ids=tuple(item.conversation_id for item in conversations),
        )
        conversation_views: list[dict[str, Any]] = []
        for conversation in conversations:
            conversation_views.append(
                {
                    **_json(conversation),
                    "latest_operator_turn_id": latest_operator_turns.get(
                        conversation.conversation_id
                    ),
                }
            )
        continuations = (
            await config.continuations.list_for_principal(
                principal_id=principal_id,
                limit=100,
            )
            if config.continuations is not None
            else ()
        )
        return JSONResponse(
            {
                "preference": _json(preference) if preference else None,
                "memories": [_json(item) for item in memories],
                "policies": [_json(item) for item in policies],
                "subscriptions": [_json(item) for item in subscriptions],
                "briefing_runs": [_json(item) for item in runs],
                "scheduled_continuations": [_json(item) for item in continuations],
                "conversations": conversation_views,
            }
        )

    async def put_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _body(request)
        expected = _required_revision(body)
        try:
            record = UserPreferenceRecord(
                principal_id=principal_id,
                locale=str(body.get("locale") or "en"),
                verbosity=str(body.get("verbosity") or "concise"),
                answer_detail=str(body.get("answer_detail") or "standard"),
                answer_format=str(body.get("answer_format") or "prose"),
                answer_preferences_enabled=_optional_bool(
                    body,
                    "answer_preferences_enabled",
                    default=True,
                ),
                answer_intent_detail=_optional_string_mapping(body, "answer_intent_detail"),
                answer_intent_format=_optional_string_mapping(body, "answer_intent_format"),
                timezone=_optional_text(body, "timezone"),
                share_with_learner=_optional_bool(
                    body,
                    "share_with_learner",
                    default=False,
                ),
                updated_at=config.clock(),
            )
            stored = await config.preferences.put(record, expected_revision=expected)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_preference(stored)
        except UserContextConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored))

    async def delete_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        deleted = await config.preferences.delete(principal_id=principal_id)
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(f"preference:{principal_id}")
        return Response(status_code=204 if deleted else 404)

    async def conversation_turns(request: Request) -> Response:
        principal_id = await authorize(request)
        conversation_id = request.path_params["conversation_id"]
        conversation = await config.conversations.get_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        limit_raw = request.query_params.get("limit", "200")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="limit MUST be an integer") from exc
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=400, detail="limit MUST be in [1, 1000]")
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=limit,
        )
        return JSONResponse({"turns": [_json(turn) for turn in turns]})

    async def search_conversations(request: Request) -> Response:
        principal_id = await authorize(request)
        try:
            query = _conversation_search_query(request)
            page = await config.conversation_search.search(
                scope=ConversationSearchScope(principal_id=principal_id),
                query=query,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = _json(page)
        payload.pop("query_ms", None)
        return JSONResponse(payload)

    async def conversation_search_context(request: Request) -> Response:
        principal_id = await authorize(request)
        try:
            context_result = await config.conversation_search.context(
                scope=ConversationSearchScope(principal_id=principal_id),
                result_id=request.path_params["result_id"],
                before=_query_int(request, "before", default=1),
                after=_query_int(request, "after", default=1),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if context_result is None:
            raise HTTPException(status_code=404, detail="conversation search result not found")
        return JSONResponse(_json(context_result))

    async def conversation_lineage(request: Request) -> Response:
        principal_id = await authorize(request)
        lineage = await config.conversation_search.lineage(
            scope=ConversationSearchScope(principal_id=principal_id),
            conversation_id=request.path_params["conversation_id"],
        )
        if lineage is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return JSONResponse(_json(lineage))

    async def delete_conversation(request: Request) -> Response:
        principal_id = await authorize(request)
        conversation_id = request.path_params["conversation_id"]
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=1000,
        )
        deleted = await config.conversations.delete_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        if deleted and config.ontology_projector is not None:
            for turn in turns:
                await config.ontology_projector.delete(f"turn:{principal_id}:{turn.turn_id}")
            await config.ontology_projector.delete(f"conversation:{principal_id}:{conversation_id}")
        return Response(status_code=204 if deleted else 404)

    async def create_memory(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        conversation_id = _required_text(body, "conversation_id")
        source_turn_id = _required_text(body, "source_turn_id")
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=1000,
        )
        if not any(turn.turn_id == source_turn_id for turn in turns):
            raise HTTPException(status_code=404, detail="source turn not found")
        now = config.clock()
        category_raw = _required_text(body, "category")
        try:
            category = UserMemoryCategory(category_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid memory category") from exc
        try:
            fact = UserMemoryFact(
                memory_id=f"memory-{uuid4().hex}",
                principal_id=principal_id,
                category=category,
                body=_required_text(body, "body"),
                source_turn_id=source_turn_id,
                consented_at=now,
                created_at=now,
                expires_at=_optional_datetime(body, "expires_at"),
            )
            stored = await config.memories.create(fact)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_memory(stored)
        except UserContextConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored), status_code=201)

    async def delete_memory(request: Request) -> Response:
        principal_id = await authorize(request)
        deleted = await config.memories.delete(
            principal_id=principal_id,
            memory_id=request.path_params["memory_id"],
        )
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(
                f"memory:{principal_id}:{request.path_params['memory_id']}"
            )
        return Response(status_code=204 if deleted else 404)

    async def put_policy(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        try:
            kind = ConversationPolicyKind(_required_text(body, "kind"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid policy kind") from exc
        briefing_spec = _briefing_spec(body.get("briefing_spec"))
        defaults = body.get("response_defaults", {})
        if not isinstance(defaults, Mapping):
            raise HTTPException(status_code=400, detail="response_defaults MUST be an object")
        try:
            record = ConversationPolicyRecord(
                policy_id=_required_text(body, "policy_id"),
                principal_id=principal_id,
                kind=kind,
                enabled=_optional_bool(body, "enabled", default=True),
                revision=0,
                confirmed_at=config.clock(),
                source_turn_id=_required_text(body, "source_turn_id"),
                briefing_spec=briefing_spec,
                response_defaults={str(key): str(value) for key, value in defaults.items()},
            )
            stored = await config.policies.put(
                record,
                expected_revision=_required_revision(body),
            )
            if config.ontology_projector is not None:
                await config.ontology_projector.project_policy(stored)
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored))

    async def delete_policy(request: Request) -> Response:
        principal_id = await authorize(request)
        policy_id = request.path_params["policy_id"]
        try:
            deleted = await config.policies.delete(
                principal_id=principal_id,
                policy_id=policy_id,
                expected_revision=_query_revision(request),
            )
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(f"policy:{principal_id}:{policy_id}")
        return Response(status_code=204 if deleted else 404)

    async def create_subscription(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        now = config.clock()
        idempotency_key = _required_text(body, "idempotency_key")
        if len(idempotency_key) > 200:
            raise HTTPException(status_code=400, detail="idempotency_key MUST be bounded")
        subscription_id = (
            "briefing-" + sha256(f"{principal_id}::{idempotency_key}".encode()).hexdigest()[:32]
        )
        cron_expression = _required_text(body, "cron_expression")
        timezone = _required_text(body, "timezone")
        modes_raw = body.get("delivery_modes", [BriefingDeliveryMode.IN_APP.value])
        if not isinstance(modes_raw, list):
            raise HTTPException(status_code=400, detail="delivery_modes MUST be a list")
        try:
            modes = tuple(BriefingDeliveryMode(str(item)) for item in modes_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid delivery mode") from exc
        if any(mode is not BriefingDeliveryMode.IN_APP for mode in modes):
            raise HTTPException(
                status_code=400,
                detail="only in_app briefing delivery is currently supported",
            )
        try:
            continuation_mode = ContinuationMode(str(body.get("continuation_mode", "none")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid continuation_mode") from exc
        continuation_origin = None
        if continuation_mode is not ContinuationMode.NONE:
            conversation_id = _required_text(body, "origin_conversation_id")
            conversation = await config.conversations.get_conversation(
                principal_id=principal_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                raise HTTPException(status_code=404, detail="origin conversation not found")
            continuation_origin = ScheduledResultOrigin(
                channel_kind="web",
                channel_ref=conversation.channel_id,
                conversation_ref=conversation.conversation_id,
            )
        try:
            record = BriefingSubscription(
                subscription_id=subscription_id,
                principal_id=principal_id,
                name=_required_text(body, "name"),
                spec=_briefing_spec(body.get("spec")) or BriefingSpec(),
                cron_expression=cron_expression,
                timezone=timezone,
                delivery_modes=modes,
                enabled=True,
                next_run_at=next_cron_run(cron_expression, timezone, after=now),
                created_at=now,
                channel_binding_ref=_optional_text(body, "channel_binding_ref"),
                max_lateness_seconds=int(body.get("max_lateness_seconds", 3600)),
                continuation_mode=continuation_mode,
                continuation_origin=continuation_origin,
                continuation_ttl_seconds=int(body.get("continuation_ttl_seconds", 604_800)),
            )
            existing = next(
                (
                    item
                    for item in await config.subscriptions.list_for_principal(
                        principal_id=principal_id
                    )
                    if item.subscription_id == subscription_id
                ),
                None,
            )
            if existing is not None:
                if not _same_subscription_intent(existing, record):
                    raise BriefingConflictError("idempotency key reused with different input")
                return JSONResponse(_json(existing), status_code=200)
            stored = await config.subscriptions.create(record)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_subscription(stored)
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored), status_code=201)

    async def delete_subscription(request: Request) -> Response:
        principal_id = await authorize(request)
        try:
            deleted = await config.subscriptions.delete(
                principal_id=principal_id,
                subscription_id=request.path_params["subscription_id"],
                expected_revision=_query_revision(request),
            )
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(
                f"briefing-subscription:{principal_id}:{request.path_params['subscription_id']}"
            )
        return Response(status_code=204 if deleted else 404)

    async def opening_briefing(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _body(request)
        run = await config.opening_briefing.open(
            principal_id=principal_id,
            conversation_id=_required_text(body, "conversation_id"),
        )
        if run is not None and config.ontology_projector is not None:
            await config.ontology_projector.project_briefing_run(run)
        return JSONResponse({"briefing": _json(run) if run else None})

    async def open_continuation(request: Request) -> Response:
        principal_id = await authorize(request)
        service = config.continuation_service
        if service is None:
            raise HTTPException(status_code=404, detail="scheduled continuation unavailable")
        try:
            anchor = await service.resolve(
                anchor_id=request.path_params["anchor_id"],
                access=ContinuationAccess(principal_id=principal_id),
                now=config.clock(),
            )
        except ContinuationAccessDeniedError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        fact = scheduled_result_to_typed_fact(anchor, token_estimator=lambda text: len(text) // 4)
        return JSONResponse(
            {
                "anchor": _json(anchor),
                "context_fact": _json(fact),
            }
        )

    async def expire_continuation(request: Request) -> Response:
        principal_id = await authorize(request)
        service = config.continuation_service
        if service is None:
            raise HTTPException(status_code=404, detail="scheduled continuation unavailable")
        try:
            anchor = await service.expire(
                anchor_id=request.path_params["anchor_id"],
                access=ContinuationAccess(principal_id=principal_id),
                now=config.clock(),
            )
        except ContinuationAccessDeniedError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(_json(anchor))

    return (
        Route("/me/context", context, methods=["GET"]),
        Route("/me/conversations/search", search_conversations, methods=["GET"]),
        Route(
            "/me/conversations/search/{result_id:str}/context",
            conversation_search_context,
            methods=["GET"],
        ),
        Route(
            "/me/conversations/{conversation_id:str}/lineage",
            conversation_lineage,
            methods=["GET"],
        ),
        Route(
            "/me/conversations/{conversation_id:str}/turns",
            conversation_turns,
            methods=["GET"],
        ),
        Route(
            "/me/conversations/{conversation_id:str}",
            delete_conversation,
            methods=["DELETE"],
        ),
        Route("/me/preferences", put_preference, methods=["PUT"]),
        Route("/me/preferences", delete_preference, methods=["DELETE"]),
        Route("/me/memories", create_memory, methods=["POST"]),
        Route("/me/memories/{memory_id:str}", delete_memory, methods=["DELETE"]),
        Route("/me/policies", put_policy, methods=["PUT"]),
        Route("/me/policies/{policy_id:str}", delete_policy, methods=["DELETE"]),
        Route("/me/briefing-subscriptions", create_subscription, methods=["POST"]),
        Route(
            "/me/briefing-subscriptions/{subscription_id:str}",
            delete_subscription,
            methods=["DELETE"],
        ),
        Route("/me/opening-briefing", opening_briefing, methods=["POST"]),
        Route(
            "/me/scheduled-continuations/{anchor_id:str}/open",
            open_continuation,
            methods=["POST"],
        ),
        Route(
            "/me/scheduled-continuations/{anchor_id:str}",
            expire_continuation,
            methods=["DELETE"],
        ),
    )


def _conversation_search_query(request: Request) -> ConversationSearchQuery:
    text = request.query_params.get("q", "")
    mode = ConversationSearchMode(request.query_params.get("mode", "terms"))
    roles_raw = _query_values(request, "role")
    channels = _query_values(request, "channel")
    return ConversationSearchQuery(
        text=text,
        mode=mode,
        limit=_query_int(request, "limit", default=20),
        context_turns=_query_int(request, "context", default=1),
        channels=channels,
        roles=tuple(ConversationTurnRole(value) for value in roles_raw),
        conversation_id=request.query_params.get("conversation_id") or None,
        incident_id=request.query_params.get("incident_id") or None,
        correlation_id=request.query_params.get("correlation_id") or None,
        recorded_after=_query_datetime(request, "after"),
        recorded_before=_query_datetime(request, "before"),
    )


def _query_values(request: Request, name: str) -> tuple[str, ...]:
    values = request.query_params.getlist(name)
    return tuple(value.strip() for value in values if value.strip())


def _query_int(request: Request, name: str, *, default: int) -> int:
    raw = request.query_params.get(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc


def _query_datetime(request: Request, name: str) -> datetime | None:
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an ISO 8601 timestamp") from exc


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    value.pop("principal_id", None)
    value.pop("user_id", None)
    return value


async def _confirmed_body(request: Request) -> dict[str, Any]:
    body = await _body(request)
    if body.get("confirmed") is not True:
        raise HTTPException(status_code=409, detail="explicit confirmation is required")
    return body


def _briefing_spec(raw: object) -> BriefingSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise HTTPException(status_code=400, detail="briefing spec MUST be an object")
    try:
        return BriefingSpec(
            kind=BriefingKind(str(raw.get("kind", BriefingKind.MAJOR_ISSUES.value))),
            lookback_seconds=int(raw.get("lookback_seconds", 86_400)),
            minimum_severity=str(raw.get("minimum_severity", "high")),
            categories=tuple(str(item) for item in raw.get("categories", ())),
            max_items=int(raw.get("max_items", 5)),
            include_pending_approvals=_mapping_bool(
                raw,
                "include_pending_approvals",
                default=True,
            ),
            include_failed_actions=_mapping_bool(
                raw,
                "include_failed_actions",
                default=True,
            ),
            scope_ref=(str(raw["scope_ref"]) if raw.get("scope_ref") else None),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid briefing spec") from exc


def _json(value: Any) -> Any:
    raw = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    return json.loads(json.dumps(raw, default=lambda item: getattr(item, "value", str(item))))


def _required_text(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_text(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_int(body: Mapping[str, Any], key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def _required_revision(body: Mapping[str, Any]) -> int:
    value = body.get("expected_revision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HTTPException(
            status_code=400,
            detail="expected_revision MUST be a non-negative integer",
        )
    return value


def _query_revision(request: Request) -> int:
    raw = request.query_params.get("expected_revision")
    try:
        revision = int(raw) if raw is not None else -1
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="expected_revision MUST be an integer",
        ) from exc
    if revision < 1:
        raise HTTPException(status_code=400, detail="expected_revision MUST be >= 1")
    return revision


def _optional_bool(body: Mapping[str, Any], key: str, *, default: bool) -> bool:
    if key not in body:
        return default
    value = body.get(key)
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be a boolean")
    return value


def _optional_string_mapping(body: Mapping[str, Any], key: str) -> dict[str, str]:
    value = body.get(key, {})
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an object")
    if not all(
        isinstance(item_key, str) and isinstance(item_value, str)
        for item_key, item_value in value.items()
    ):
        raise HTTPException(status_code=400, detail=f"{key} MUST map strings to strings")
    return dict(value)


def _mapping_bool(body: Mapping[str, object], key: str, *, default: bool) -> bool:
    if key not in body:
        return default
    value = body.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} MUST be a boolean")
    return value


def _optional_datetime(body: Mapping[str, Any], key: str) -> datetime | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} MUST be ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{key} MUST be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail=f"{key} MUST include timezone")
    return parsed


__all__ = ["UserContextRoutesConfig", "make_user_context_routes"]

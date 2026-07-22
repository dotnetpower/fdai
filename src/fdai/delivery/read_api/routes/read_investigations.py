"""Authenticated direct, streamed, and detached read investigations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from fdai.core.background_task import (
    BackgroundTaskBudget,
    BackgroundTaskOrigin,
    BackgroundTaskQuotaExceededError,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.core.read_investigation import (
    InvestigationExecutionPolicy,
    PlanLatencyEstimate,
    ReadInvestigationBudget,
    ReadInvestigationExecutionMode,
    ReadInvestigationPlan,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationService,
    estimate_plan_latency,
    latency_profile,
    plan_read_investigation,
    read_tool_spec,
)
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadLatencyProfileStore,
    ResourceSelector,
)

AuthorizePrincipal = Callable[[Request], Awaitable[Principal]]
_MAX_BODY: Final = 16_000


@dataclass(frozen=True, slots=True)
class ReadInvestigationRoutesConfig:
    service: ReadInvestigationService
    latency_store: ReadLatencyProfileStore
    background: BackgroundTaskRoutesConfig
    scope_ref: str
    execution_policy: InvestigationExecutionPolicy = InvestigationExecutionPolicy()

    def __post_init__(self) -> None:
        if not self.scope_ref.strip() or len(self.scope_ref) > 256:
            raise ValueError("read investigation scope_ref MUST be bounded")


def make_read_investigation_routes(
    *,
    config: ReadInvestigationRoutesConfig,
    authorize_principal: AuthorizePrincipal,
) -> tuple[Route, ...]:
    async def start(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.START_READ_INVESTIGATION):
            raise HTTPException(
                status_code=403,
                detail="start-read-investigation capability is required",
            )
        body = await _body(request)
        try:
            investigation = _request(body, principal=principal, scope_ref=config.scope_ref)
            plan = plan_read_investigation(investigation)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        profiles = {}
        for step in plan.steps:
            spec = read_tool_spec(step.tool_id)
            samples = await config.latency_store.recent(
                tool_id=step.tool_id,
                transport=config.service.transport,
                operation_class=spec.operation_class,
                limit=200,
            )
            profiles[step.tool_id] = latency_profile(samples)
        estimate = estimate_plan_latency(
            plan,
            profiles,
            minimum_samples=config.execution_policy.minimum_profile_samples,
        )
        mode = config.execution_policy.select(plan, estimate)
        if mode is ReadInvestigationExecutionMode.DETACHED:
            return await _detach(
                config,
                investigation,
                body,
                principal=principal,
                estimate=estimate,
            )
        if mode is ReadInvestigationExecutionMode.STREAMED:
            return _stream(config.service, plan, estimate=estimate)
        result = await config.service.execute(plan)
        return JSONResponse(
            {
                "mode": mode.value,
                "estimate": _estimate(estimate),
                "result": _result(result),
            }
        )

    return (Route("/read-investigations", start, methods=["POST"]),)


async def _detach(
    config: ReadInvestigationRoutesConfig,
    request: ReadInvestigationRequest,
    body: dict[str, Any],
    *,
    principal: Principal,
    estimate: PlanLatencyEstimate,
) -> Response:
    prompt = _canonical_prompt(request)
    context_digest = hashlib.sha256(
        json.dumps(
            {
                "intent": request.intent.value,
                "resource_name": request.selector.name,
                "principal_id": principal.oid,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    try:
        attempt, created = await config.background.service.create(
            owner_principal_id=principal.oid,
            origin=BackgroundTaskOrigin(
                conversation_id=request.conversation_ref,
                channel_kind=_string(body, "channel_kind"),
                channel_id=_string(body, "channel_id"),
                thread_id=_optional_string(body, "thread_id"),
                message_id=_string(body, "message_id"),
            ),
            prompt=prompt,
            context_digest=f"sha256:{context_digest}",
            correlation_id=request.correlation_ref,
            idempotency_key=request.idempotency_key,
            budget=BackgroundTaskBudget(
                max_wall_seconds=request.budget.max_wall_seconds,
                max_cost_microusd=request.budget.max_cost_microusd,
                max_tool_calls=request.budget.max_tool_calls,
            ),
            retention_days=_integer(body, "retention_days", default=30),
        )
    except BackgroundTaskQuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    config.background.coordinator.wake()
    return JSONResponse(
        {
            "mode": ReadInvestigationExecutionMode.DETACHED.value,
            "estimate": _estimate(estimate),
            "task_id": attempt.task.task_id,
            "status": attempt.status.value,
        },
        status_code=202 if created else 200,
    )


def _stream(
    service: ReadInvestigationService,
    plan: ReadInvestigationPlan,
    *,
    estimate: PlanLatencyEstimate,
) -> Response:
    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)

        async def observe(kind: ReadInvestigationProgressKind) -> None:
            await queue.put(kind.value)

        execution = asyncio.create_task(service.execute(plan, progress_observer=observe))
        while not execution.done() or not queue.empty():
            try:
                kind = await asyncio.wait_for(queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            yield f"event: progress\ndata: {json.dumps({'kind': kind})}\n\n"
        result = await execution
        payload = {
            "mode": ReadInvestigationExecutionMode.STREAMED.value,
            "estimate": _estimate(estimate),
            "result": _result(result),
        }
        yield f"event: terminal\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def _request(
    body: dict[str, Any],
    *,
    principal: Principal,
    scope_ref: str,
) -> ReadInvestigationRequest:
    try:
        intent = ReadInvestigationIntent(_string(body, "intent"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="intent is unsupported") from exc
    budget = body.get("budget") or {}
    if not isinstance(budget, dict):
        raise HTTPException(status_code=400, detail="budget MUST be an object")
    explicit_deep = body.get("explicit_deep", False)
    if not isinstance(explicit_deep, bool):
        raise HTTPException(status_code=400, detail="explicit_deep MUST be boolean")
    return ReadInvestigationRequest(
        requester_ref=principal.oid,
        conversation_ref=_string(body, "conversation_id"),
        correlation_ref=_string(body, "correlation_id"),
        intent=intent,
        selector=ResourceSelector(
            name=_string(body, "resource_name", maximum=128),
            scope_ref=scope_ref,
            resource_type=_optional_string(body, "resource_type"),
            resource_group=_optional_string(body, "resource_group"),
        ),
        lookback_seconds=_integer(body, "lookback_seconds", default=3_600),
        requested_evidence=(),
        budget=ReadInvestigationBudget(
            max_wall_seconds=_mapping_int(budget, "max_wall_seconds", 60),
            max_cost_microusd=_mapping_int(budget, "max_cost_microusd", 100_000),
            max_tool_calls=_mapping_int(budget, "max_tool_calls", 5),
            max_results=_mapping_int(budget, "max_results", 32),
            max_output_bytes=_mapping_int(budget, "max_output_bytes", 256_000),
        ),
        idempotency_key=_string(body, "idempotency_key"),
        created_at=datetime.now(UTC),
        explicit_deep=explicit_deep,
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="request body exceeds cap")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def _canonical_prompt(request: ReadInvestigationRequest) -> str:
    phrase = {
        ReadInvestigationIntent.RESOURCE_STATE: "Check the current state of",
        ReadInvestigationIntent.CHANGE_ATTRIBUTION: "Who changed or stopped",
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY: "Show the change history of",
        ReadInvestigationIntent.PLATFORM_HEALTH: "Check the platform health of",
        ReadInvestigationIntent.GUEST_SHUTDOWN: "Find guest OS shutdown events for",
    }[request.intent]
    suffix = " with deep analysis" if request.explicit_deep else ""
    return f"{phrase} {request.selector.name}{suffix}."


def _result(result: ReadInvestigationResult) -> dict[str, object]:
    return {
        "outcome": result.outcome.value,
        "resolution": {
            "status": result.resolution.status.value,
            "resource": (
                {
                    "resource_ref": result.resolution.resource.resource_ref,
                    "name": result.resolution.resource.name,
                    "resource_type": result.resolution.resource.resource_type,
                    "resource_group": result.resolution.resource.resource_group,
                }
                if result.resolution.resource is not None
                else None
            ),
            "candidates": [
                {
                    "resource_ref": item.resource_ref,
                    "name": item.name,
                    "resource_type": item.resource_type,
                    "resource_group": item.resource_group,
                }
                for item in result.resolution.candidates
            ],
        },
        "evidence": [
            {
                "status": item.status.value,
                "authority": item.authority,
                "resource_ref": item.resource_ref,
                "observed_at": item.observed_at.isoformat(),
                "freshness": item.freshness.value,
                "truncated": item.truncated,
                "records": len(item.records),
                "evidence_refs": list(item.evidence_refs),
            }
            for item in result.evidence
        ],
        "evidence_refs": list(result.evidence_refs),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }


def _estimate(value: PlanLatencyEstimate) -> dict[str, object]:
    return {
        "lower_ms": value.lower_ms,
        "upper_ms": value.upper_ms,
        "measured": value.measured,
        "sample_count": value.sample_count,
    }


def _string(body: dict[str, Any], key: str, *, maximum: int = 256) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def _integer(body: dict[str, Any], key: str, *, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def _mapping_int(body: dict[str, Any], key: str, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"budget.{key} MUST be an integer")
    return value


__all__ = ["ReadInvestigationRoutesConfig", "make_read_investigation_routes"]

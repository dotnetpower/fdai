"""Read-only automation blueprint cards and separate ChatOps review routes."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation import Principal
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintCandidate,
    AutomationBlueprintReviewService,
    AutomationBlueprintState,
    AutomationBlueprintStore,
)
from fdai.delivery.read_api.routes.panels import PanelQueryError

BlueprintAuthorizer = Callable[[Request], Awaitable[Principal]]


class AutomationBlueprintPanel:
    """Project durable candidate cards without review or scheduling controls."""

    def __init__(self, store: AutomationBlueprintStore, *, path: str = "/automation-blueprints"):
        self._store = store
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "automation-blueprints"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        unknown = set(params) - {"state", "limit"}
        if unknown:
            raise PanelQueryError(f"unknown automation blueprint parameters: {sorted(unknown)}")
        state = params.get("state", "all")
        if state != "all" and state not in {item.value for item in AutomationBlueprintState}:
            raise PanelQueryError("automation blueprint state filter is invalid")
        try:
            limit = int(params.get("limit", "100"))
        except ValueError as exc:
            raise PanelQueryError("automation blueprint limit MUST be an integer") from exc
        if not 1 <= limit <= 200:
            raise PanelQueryError("automation blueprint limit MUST be in [1, 200]")
        all_candidates = tuple(await self._store.list_all())
        visible = tuple(
            candidate
            for candidate in all_candidates
            if state == "all" or candidate.state.value == state
        )[:limit]
        return {
            "source": "automation-blueprint-store",
            "mutation_controls": False,
            "count": len(visible),
            "candidates": [_candidate_view(candidate) for candidate in visible],
            "metrics": _metrics(all_candidates),
        }


def make_automation_blueprint_review_routes(
    *,
    service: AutomationBlueprintReviewService,
    authorize: BlueprintAuthorizer,
) -> tuple[Route, ...]:
    """Build ChatOps-facing review routes; the console does not register controls."""

    async def review(request: Request) -> Response:
        principal = await authorize(request)
        body = await _json_body(request)
        decision = body.get("decision")
        reason = body.get("reason")
        if decision not in {"accept", "reject"} or not isinstance(reason, str):
            raise HTTPException(status_code=400, detail="review requires decision and reason")
        candidate = await service.review(
            request.path_params["candidate_id"],
            principal=principal,
            approve=decision == "accept",
            reason=reason,
            at=_request_time(request),
        )
        return JSONResponse(_candidate_view(candidate))

    async def materialize(request: Request) -> Response:
        principal = await authorize(request)
        candidate = await service.materialize(
            request.path_params["candidate_id"],
            principal=principal,
            at=_request_time(request),
        )
        return JSONResponse(_candidate_view(candidate))

    return (
        Route(
            "/automation-blueprints/{candidate_id:str}/review",
            review,
            methods=["POST"],
        ),
        Route(
            "/automation-blueprints/{candidate_id:str}/materialize",
            materialize,
            methods=["POST"],
        ),
    )


def _candidate_view(candidate: AutomationBlueprintCandidate) -> dict[str, Any]:
    profile = candidate.isolation_profile
    return {
        "candidate_id": candidate.candidate_id,
        "state": candidate.state.value,
        "normalized_task_intent": candidate.normalized_task_intent,
        "schedule_class": candidate.schedule_class,
        "schedule_expression": candidate.schedule_expression,
        "event_type": candidate.event_type,
        "principal_id": candidate.principal_id,
        "resource_scope": candidate.resource_scope,
        "delivery_intent": candidate.delivery_intent,
        "required_tools": list(candidate.required_tools),
        "isolation_profile": {
            "profile_id": profile.profile_id,
            "max_session_seconds": profile.max_session_seconds,
            "max_context_chars": profile.max_context_chars,
            "max_tool_calls": profile.max_tool_calls,
            "allowed_tool_ids": sorted(profile.allowed_tool_ids),
        },
        "estimated_cost_microusd": candidate.estimated_cost_microusd,
        "evidence_fingerprints": list(candidate.evidence_fingerprints),
        "proposer": candidate.proposer,
        "confidence": candidate.confidence,
        "created_at": candidate.created_at.isoformat(),
        "expires_at": candidate.expires_at.isoformat(),
        "enabled": candidate.enabled,
        "shadow_only": candidate.shadow_only,
        "mutation_tool_ids": list(candidate.mutation_tool_ids),
        "reviewed_by": candidate.reviewed_by,
        "review_reason": candidate.review_reason,
        "resulting_task_id": candidate.resulting_task_id,
        "realized_usage_count": candidate.realized_usage_count,
    }


def _metrics(candidates: Sequence[AutomationBlueprintCandidate]) -> dict[str, Any]:
    counts = Counter(candidate.state.value for candidate in candidates)
    reviewed = counts["accepted"] + counts["rejected"] + counts["materialized"]
    accepted = counts["accepted"] + counts["materialized"]
    reasons = Counter(
        candidate.review_reason
        for candidate in candidates
        if candidate.state is AutomationBlueprintState.REJECTED and candidate.review_reason
    )
    return {
        "proposed": len(candidates),
        "accepted": accepted,
        "rejected": counts["rejected"],
        "expired": counts["expired"],
        "materialized": counts["materialized"],
        "realized_usage": sum(candidate.realized_usage_count for candidate in candidates),
        "candidate_precision": accepted / reviewed if reviewed else 0.0,
        "acceptance_rate": accepted / reviewed if reviewed else 0.0,
        "rejection_reasons": dict(sorted(reasons.items())),
    }


async def _json_body(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > 16 * 1024:
        raise HTTPException(status_code=413, detail="automation blueprint body too large")
    try:
        decoded = json.loads(body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="automation blueprint body MUST be JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="automation blueprint body MUST be an object")
    return decoded


def _request_time(request: Request) -> datetime:
    value = getattr(request.state, "blueprint_now", None)
    return value if isinstance(value, datetime) else datetime.now(tz=UTC)


__all__ = [
    "AutomationBlueprintPanel",
    "BlueprintAuthorizer",
    "make_automation_blueprint_review_routes",
]

"""HTTP payload parsing and projection for read investigations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request

from fdai.core.rbac.resolver import Principal
from fdai.core.read_investigation import (
    PlanLatencyEstimate,
    ReadInvestigationBudget,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.shared.providers.read_investigation import ReadInvestigationIntent, ResourceSelector

_MAX_BODY: Final = 16_000


def request_from_body(
    body: dict[str, Any],
    *,
    principal: Principal,
    scope_ref: str,
) -> ReadInvestigationRequest:
    try:
        intent = ReadInvestigationIntent(required_string(body, "intent"))
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
        conversation_ref=required_string(body, "conversation_id"),
        correlation_ref=required_string(body, "correlation_id"),
        intent=intent,
        selector=ResourceSelector(
            name=required_string(body, "resource_name", maximum=128),
            scope_ref=scope_ref,
            resource_type=optional_string(body, "resource_type"),
            resource_group=optional_string(body, "resource_group"),
        ),
        lookback_seconds=integer(body, "lookback_seconds", default=3_600),
        requested_evidence=(),
        budget=ReadInvestigationBudget(
            max_wall_seconds=mapping_int(budget, "max_wall_seconds", 60),
            max_cost_microusd=mapping_int(budget, "max_cost_microusd", 100_000),
            max_tool_calls=mapping_int(budget, "max_tool_calls", 5),
            max_results=mapping_int(budget, "max_results", 32),
            max_output_bytes=mapping_int(budget, "max_output_bytes", 256_000),
        ),
        idempotency_key=required_string(body, "idempotency_key"),
        created_at=datetime.now(UTC),
        explicit_deep=explicit_deep,
    )


async def read_body(request: Request) -> dict[str, Any]:
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


def canonical_prompt(request: ReadInvestigationRequest) -> str:
    phrase = {
        ReadInvestigationIntent.RESOURCE_STATE: "Check the current state of",
        ReadInvestigationIntent.CHANGE_ATTRIBUTION: "Who changed or stopped",
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY: "Show the change history of",
        ReadInvestigationIntent.PLATFORM_HEALTH: "Check the platform health of",
        ReadInvestigationIntent.GUEST_SHUTDOWN: "Find guest OS shutdown events for",
    }[request.intent]
    suffix = " with deep analysis" if request.explicit_deep else ""
    return f"{phrase} {request.selector.name}{suffix}."


def result_payload(result: ReadInvestigationResult) -> dict[str, object]:
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


def estimate_payload(value: PlanLatencyEstimate) -> dict[str, object]:
    return {
        "lower_ms": value.lower_ms,
        "upper_ms": value.upper_ms,
        "measured": value.measured,
        "sample_count": value.sample_count,
    }


def required_string(body: dict[str, Any], key: str, *, maximum: int = 256) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def optional_string(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HTTPException(status_code=400, detail=f"{key} MUST be a bounded string")
    return value.strip()


def integer(body: dict[str, Any], key: str, *, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def mapping_int(body: dict[str, Any], key: str, default: int) -> int:
    value = body.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"budget.{key} MUST be an integer")
    return value

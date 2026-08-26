"""Canonical identities for read-investigation requests."""

from __future__ import annotations

import hashlib
import json

from fdai.core.read_investigation.models import ReadInvestigationRequest


def read_investigation_request_projection(
    request: ReadInvestigationRequest,
) -> dict[str, object]:
    """Return the provider-neutral canonical projection used for request digesting."""

    return {
        "intent": request.intent.value,
        "selector": {
            "name": request.selector.name,
            "scope_ref": request.selector.scope_ref,
            "resource_type": request.selector.resource_type,
            "resource_group": request.selector.resource_group,
        },
        "lookback_seconds": request.lookback_seconds,
        "requested_evidence": [tool_id.value for tool_id in request.requested_evidence],
        "budget": {
            "max_wall_seconds": request.budget.max_wall_seconds,
            "max_cost_microusd": request.budget.max_cost_microusd,
            "max_tool_calls": request.budget.max_tool_calls,
            "max_results": request.budget.max_results,
            "max_output_bytes": request.budget.max_output_bytes,
        },
        "explicit_deep": request.explicit_deep,
    }


def read_investigation_request_digest(request: ReadInvestigationRequest) -> str:
    """Return the lowercase SHA-256 digest of the canonical request projection."""

    payload = json.dumps(
        read_investigation_request_projection(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "read_investigation_request_digest",
    "read_investigation_request_projection",
]

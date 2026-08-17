"""Pure request and action integrity helpers for HIL resume."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.direct_api import DirectApiExecutionOutcome, DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionOutcome, ToolCallExecutionResult
from fdai.shared.contracts.models import Action, Rule


def approval_request_fingerprint(
    *,
    action: Action,
    rule: Rule,
    submitter_oid: str,
    correlation_id: str,
    reasons: Sequence[str],
    blast_radius_summary: str,
    ttl_seconds: int,
    assignee_oid: str | None,
) -> str:
    """Return the canonical identity of one approval request."""
    payload = {
        "action": action.model_dump(mode="json"),
        "rule": {"id": rule.id, "version": rule.version},
        "submitter_oid": submitter_oid,
        "correlation_id": correlation_id,
        "reasons": list(reasons),
        "blast_radius_summary": blast_radius_summary,
        "ttl_seconds": ttl_seconds,
        "assignee_oid": assignee_oid,
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def action_payload_hash(action: Mapping[str, Any]) -> str:
    """Return the canonical digest used to detect parked-action tampering."""
    canonical = json.dumps(action, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parked_action_integrity_matches(parked: Mapping[str, Any]) -> bool:
    """Accept only an action whose payload still matches its parked digest."""
    expected = parked.get("action_hash")
    escalation = parked.get("escalation")
    if expected is None and isinstance(escalation, Mapping):
        expected = escalation.get("action_hash")
    if expected is None:
        return True
    action = parked.get("action")
    return (
        isinstance(expected, str)
        and isinstance(action, Mapping)
        and expected == action_payload_hash(action)
    )


def is_execution_success(
    result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult,
) -> bool:
    """Check success consistently across every HIL executor path."""
    outcome = getattr(result, "outcome", None)
    return outcome in (
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    )


__all__ = [
    "action_payload_hash",
    "approval_request_fingerprint",
    "is_execution_success",
    "parked_action_integrity_matches",
]

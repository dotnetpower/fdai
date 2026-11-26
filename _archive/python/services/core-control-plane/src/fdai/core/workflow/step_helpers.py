"""Small helpers for workflow step execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.workflow_runtime import event_id
from fdai.rule_catalog.schema.action_type import argument_schema_redaction_paths
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind


def redacted_params(
    step: RunbookStep,
    params: Mapping[str, object],
    action_types: Mapping[str, OntologyActionType],
) -> tuple[dict[str, object], frozenset[str]]:
    action_type = action_types.get(step.action_type)
    if action_type is None:
        return dict(params), frozenset()
    configured = argument_schema_redaction_paths(action_type)
    present = frozenset(path for path in configured if path in params)
    safe = {key: "[REDACTED]" if key in present else value for key, value in params.items()}
    return safe, present


def branch_event(
    *,
    process_id: str,
    step: RunbookStep,
    branch: str,
    kind: ProcessEventKind,
    suffix: str,
    recorded_at: datetime,
    correlation_id: str,
    attempt: int,
) -> ProcessEvent:
    return ProcessEvent(
        event_id=event_id(process_id, f"step:{step.id}:attempt:{attempt}:branch:{branch}:{suffix}"),
        process_id=process_id,
        kind=kind,
        idempotency_key=f"{process_id}:step:{step.id}:attempt:{attempt}:branch:{branch}:{suffix}",
        recorded_at=recorded_at,
        correlation_id=correlation_id,
        step_id=step.id,
        attempt=attempt,
        payload={"branch": branch},
    )


def timed_out(step: RunbookStep, *, context: Mapping[str, str], now: datetime) -> bool:
    if step.timeout_seconds is None:
        return False
    raw = context.get(f"started_at.{step.id}")
    if raw is None:
        return False
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - started).total_seconds() >= step.timeout_seconds


__all__ = ["branch_event", "redacted_params", "timed_out"]

"""Serialization helpers for PostgreSQL background task records."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskCompletion,
    BackgroundTaskCompletionState,
    BackgroundTaskKind,
    BackgroundTaskLease,
    BackgroundTaskOrigin,
    BackgroundTaskProgress,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)

ATTEMPT_COLUMNS: Final = (
    "attempt_id, task_id, owner_principal_id, idempotency_key, task, "
    "attempt_number, status, revision, created_at, retention_until, updated_at, "
    "max_progress_events, lease_owner, lease_token, lease_expires_at, usage, "
    "result, parent_attempt_id"
)
PROGRESS_COLUMNS: Final = "attempt_id, sequence, kind, message, at, usage"
COMPLETION_COLUMNS: Final = (
    "attempt_id, state, created_at, due_at, retention_until, attempt_count, "
    "lease_owner, lease_token, lease_expires_at, last_error_code, terminal_at"
)


def attempt_from_row(row: dict[str, Any]) -> BackgroundTaskAttempt:
    lease_owner = row["lease_owner"]
    result_raw = row["result"]
    return BackgroundTaskAttempt(
        attempt_id=str(row["attempt_id"]),
        task=_task(_mapping(row["task"])),
        attempt_number=int(row["attempt_number"]),
        status=BackgroundTaskStatus(str(row["status"])),
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
        lease=(
            BackgroundTaskLease(
                owner=str(lease_owner),
                token=str(row["lease_token"]),
                expires_at=row["lease_expires_at"],
            )
            if lease_owner is not None
            else None
        ),
        usage=_usage(_mapping(row["usage"])),
        result=_result(_mapping(result_raw)) if result_raw is not None else None,
        parent_attempt_id=(
            str(row["parent_attempt_id"]) if row["parent_attempt_id"] is not None else None
        ),
    )


def progress_from_row(row: dict[str, Any]) -> BackgroundTaskProgress:
    return BackgroundTaskProgress(
        attempt_id=str(row["attempt_id"]),
        sequence=int(row["sequence"]),
        kind=str(row["kind"]),
        message=str(row["message"]),
        at=row["at"],
        usage=_usage(_mapping(row["usage"])),
    )


def completion_from_row(row: dict[str, Any]) -> BackgroundTaskCompletion:
    lease_owner = row["lease_owner"]
    return BackgroundTaskCompletion(
        attempt_id=str(row["attempt_id"]),
        state=BackgroundTaskCompletionState(str(row["state"])),
        created_at=row["created_at"],
        due_at=row["due_at"],
        retention_until=row["retention_until"],
        attempt_count=int(row["attempt_count"]),
        lease=(
            BackgroundTaskLease(
                owner=str(lease_owner),
                token=str(row["lease_token"]),
                expires_at=row["lease_expires_at"],
            )
            if lease_owner is not None
            else None
        ),
        last_error_code=(
            str(row["last_error_code"]) if row["last_error_code"] is not None else None
        ),
        terminal_at=row["terminal_at"],
    )


def task_to_dict(task: BackgroundTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "owner_principal_id": task.owner_principal_id,
        "origin": {
            "conversation_id": task.origin.conversation_id,
            "channel_kind": task.origin.channel_kind,
            "channel_id": task.origin.channel_id,
            "thread_id": task.origin.thread_id,
            "message_id": task.origin.message_id,
        },
        "kind": task.kind.value,
        "prompt": task.prompt,
        "context_digest": task.context_digest,
        "capability_profile_id": task.capability_profile_id,
        "budget": {
            "max_wall_seconds": task.budget.max_wall_seconds,
            "max_tokens": task.budget.max_tokens,
            "max_cost_microusd": task.budget.max_cost_microusd,
            "max_tool_calls": task.budget.max_tool_calls,
            "max_progress_events": task.budget.max_progress_events,
        },
        "correlation_id": task.correlation_id,
        "idempotency_key": task.idempotency_key,
        "created_at": task.created_at.isoformat(),
        "retention_until": task.retention_until.isoformat(),
        "retryable": task.retryable,
    }


def usage_to_dict(usage: BackgroundTaskUsage) -> dict[str, int]:
    return {
        "tokens": usage.tokens,
        "cost_microusd": usage.cost_microusd,
        "tool_calls": usage.tool_calls,
    }


def result_to_dict(result: BackgroundTaskResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "evidence_refs": list(result.evidence_refs),
        "terminal_reason": result.terminal_reason,
        "usage": usage_to_dict(result.usage),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "trusted": result.trusted,
    }


def qualified_attempt_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in ATTEMPT_COLUMNS.split(","))


def qualified_completion_columns(alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in COMPLETION_COLUMNS.split(","))


def _task(raw: dict[str, Any]) -> BackgroundTask:
    origin = _mapping(raw["origin"])
    budget = _mapping(raw["budget"])
    thread_id = origin.get("thread_id")
    message_id = origin.get("message_id")
    return BackgroundTask(
        task_id=str(raw["task_id"]),
        owner_principal_id=str(raw["owner_principal_id"]),
        origin=BackgroundTaskOrigin(
            conversation_id=str(origin["conversation_id"]),
            channel_kind=str(origin["channel_kind"]),
            channel_id=str(origin["channel_id"]),
            thread_id=str(thread_id) if thread_id is not None else None,
            message_id=str(message_id) if message_id is not None else None,
        ),
        kind=BackgroundTaskKind(str(raw["kind"])),
        prompt=str(raw["prompt"]),
        context_digest=str(raw["context_digest"]),
        capability_profile_id=str(raw["capability_profile_id"]),
        budget=BackgroundTaskBudget(
            max_wall_seconds=int(budget["max_wall_seconds"]),
            max_tokens=int(budget["max_tokens"]),
            max_cost_microusd=int(budget["max_cost_microusd"]),
            max_tool_calls=int(budget["max_tool_calls"]),
            max_progress_events=int(budget["max_progress_events"]),
        ),
        correlation_id=str(raw["correlation_id"]),
        idempotency_key=str(raw["idempotency_key"]),
        created_at=datetime.fromisoformat(str(raw["created_at"])),
        retention_until=datetime.fromisoformat(str(raw["retention_until"])),
        retryable=bool(raw["retryable"]),
    )


def _usage(raw: dict[str, Any]) -> BackgroundTaskUsage:
    return BackgroundTaskUsage(
        tokens=int(raw["tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
        tool_calls=int(raw["tool_calls"]),
    )


def _result(raw: dict[str, Any]) -> BackgroundTaskResult:
    summary = raw.get("summary")
    return BackgroundTaskResult(
        summary=str(summary) if summary is not None else None,
        evidence_refs=tuple(str(item) for item in raw["evidence_refs"]),
        terminal_reason=str(raw["terminal_reason"]),
        usage=_usage(_mapping(raw["usage"])),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        finished_at=datetime.fromisoformat(str(raw["finished_at"])),
        trusted=bool(raw["trusted"]),
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("background task JSON column is not an object")

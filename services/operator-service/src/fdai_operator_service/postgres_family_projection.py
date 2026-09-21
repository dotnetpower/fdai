"""Pure row decoding for Operator PostgreSQL family projections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, cast

from fdai_operator_service.families.conversation.background_tasks import (
    BackgroundTaskProgressProjection,
    BackgroundTaskProjection,
)
from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.postgres_family_models import PostgresFamilyStoreUnavailableError

_BACKGROUND_TASK_STATUSES: Final = frozenset(
    {"queued", "claimed", "running", "succeeded", "failed", "cancelled", "timed_out", "unknown"}
)
_TERMINAL_BACKGROUND_TASK_STATUSES: Final = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "unknown"}
)
_BACKGROUND_COMPLETION_STATES: Final = frozenset(
    {"pending", "sending", "failed", "delivered", "abandoned"}
)


def background_task_projection(row: Mapping[str, object]) -> BackgroundTaskProjection:
    """Decode one fail-closed background-task projection row."""
    task_status = _required_row_text(row, "status")
    if task_status not in _BACKGROUND_TASK_STATUSES:
        raise PostgresFamilyStoreUnavailableError("background task status is malformed")
    completion_state = _optional_row_text(row, "completion_state")
    if completion_state is not None and completion_state not in _BACKGROUND_COMPLETION_STATES:
        raise PostgresFamilyStoreUnavailableError("background task completion_state is malformed")
    progress_watermark = _optional_row_integer(row, "progress_watermark", minimum=0)
    if task_status in _TERMINAL_BACKGROUND_TASK_STATUSES and progress_watermark is None:
        raise PostgresFamilyStoreUnavailableError("background task progress_watermark is malformed")
    if task_status not in _TERMINAL_BACKGROUND_TASK_STATUSES and progress_watermark is not None:
        raise PostgresFamilyStoreUnavailableError("background task progress_watermark is malformed")
    accountable_agent = _optional_row_text(row, "accountable_agent")
    if accountable_agent is not None and accountable_agent != "Heimdall":
        raise PostgresFamilyStoreUnavailableError("background task accountable_agent is malformed")
    evidence_refs = _background_evidence_refs(row.get("evidence_refs"))
    return BackgroundTaskProjection(
        task_id=_required_row_text(row, "task_id"),
        attempt_id=_required_row_text(row, "attempt_id"),
        kind=_required_row_text(row, "task_kind"),
        status=task_status,
        revision=_required_row_integer(row, "revision"),
        created_at=stored_timestamp(row.get("created_at"), label="background task creation"),
        updated_at=stored_timestamp(row.get("updated_at"), label="background task update"),
        retention_until=stored_timestamp(
            row.get("retention_until"), label="background task retention"
        ),
        progress_watermark=progress_watermark,
        latest_progress_order=_row_integer_or_default(
            row,
            "latest_progress_order",
            default=0,
            minimum=0,
        ),
        lease_expires_at=optional_timestamp(row.get("lease_expires_at")),
        budget=cast(JsonObject, _json_object(row.get("budget"), label="background task budget")),
        usage=cast(JsonObject, _json_object(row.get("usage"), label="background task usage")),
        terminal_reason=_optional_row_text(row, "terminal_reason"),
        started_at=optional_timestamp(row.get("started_at")),
        finished_at=optional_timestamp(row.get("finished_at")),
        completion_state=completion_state,
        request_summary=_optional_row_text(row, "request_summary", maximum=500),
        request_truncated=_required_row_boolean(row, "request_truncated"),
        accountable_agent=accountable_agent,
        result_summary=_optional_row_text(row, "result_summary", maximum=2_000),
        result_truncated=_required_row_boolean(row, "result_truncated"),
        evidence_refs=evidence_refs,
        evidence_truncated=_required_row_boolean(row, "evidence_truncated"),
    )


def _background_evidence_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or len(value) > 16:
        raise PostgresFamilyStoreUnavailableError("background task evidence_refs are malformed")
    refs = tuple(value)
    if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 256 for ref in refs):
        raise PostgresFamilyStoreUnavailableError("background task evidence_refs are malformed")
    if len(set(refs)) != len(refs):
        raise PostgresFamilyStoreUnavailableError("background task evidence_refs are malformed")
    return cast(tuple[str, ...], refs)


def background_task_progress(row: Mapping[str, object]) -> BackgroundTaskProgressProjection:
    """Decode one fail-closed background-task progress row."""
    return BackgroundTaskProgressProjection(
        sequence=_required_row_integer(row, "sequence", minimum=0),
        order=_row_integer_or_default(row, "progress_order", default=0, minimum=0),
        kind=_required_row_text(row, "kind"),
        message=_required_row_text(row, "message", maximum=1_000),
        at=stored_timestamp(row.get("at"), label="background task progress"),
        usage=cast(
            JsonObject,
            _json_object(row.get("usage"), label="background task progress usage"),
        ),
    )


def _required_row_text(
    row: Mapping[str, object],
    field: str,
    *,
    maximum: int = 256,
) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PostgresFamilyStoreUnavailableError(f"background task {field} is malformed")
    return value


def _optional_row_text(
    row: Mapping[str, object],
    field: str,
    *,
    maximum: int = 256,
) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    return _required_row_text(row, field, maximum=maximum)


def _required_row_boolean(row: Mapping[str, object], field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise PostgresFamilyStoreUnavailableError(f"background task {field} is malformed")
    return value


def _required_row_integer(
    row: Mapping[str, object],
    field: str,
    *,
    minimum: int = 1,
) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailableError(f"background task {field} is malformed")
    return value


def _optional_row_integer(
    row: Mapping[str, object],
    field: str,
    *,
    minimum: int = 0,
) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailableError(f"background task {field} is malformed")
    return value


def _row_integer_or_default(
    row: Mapping[str, object],
    field: str,
    *,
    default: int,
    minimum: int = 0,
) -> int:
    value = row.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PostgresFamilyStoreUnavailableError(f"background task {field} is malformed")
    return value


def stored_timestamp(value: object, *, label: str) -> datetime:
    """Decode one PostgreSQL timestamp, assigning UTC to driver-returned naive values."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    raise PostgresFamilyStoreUnavailableError(f"{label} record has no write timestamp")


def optional_timestamp(value: object) -> datetime | None:
    """Decode one optional PostgreSQL timestamp."""
    if value is None:
        return None
    return stored_timestamp(value, label="optional inventory observation")


def activity_correlation(
    row: Mapping[str, object],
    payload: Mapping[str, object],
) -> str | None:
    """Select one bounded activity correlation id from row or payload metadata."""
    for value in (row.get("correlation_id"), payload.get("correlation_id")):
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            return value.strip()
    return None


def instance_activity_facts(payload: Mapping[str, object]) -> dict[str, str]:
    """Project the bounded canonical activity facts exposed by the instance view."""
    facts: dict[str, str] = {}
    for key in (
        "action_type",
        "decision",
        "mode",
        "outcome",
        "reason",
        "risk_verdict",
        "state",
        "tier",
        "verdict",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and len(value) <= 256:
            facts[key] = value.strip()
    return facts


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PostgresFamilyStoreUnavailableError(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}

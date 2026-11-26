"""Read-only paginated projection of scheduler dispatch history."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

from fdai.core.scheduler.run_ledger import (
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
    ScheduleRunLedger,
)


@dataclass(frozen=True, slots=True)
class ScheduleRunHistoryItem:
    run_id: str
    task_id: str
    scheduled_for: str
    claimed_at: str
    status: str
    attempt: int
    completed_at: str | None
    error_kind: str | None


@dataclass(frozen=True, slots=True)
class ScheduleRunHistoryPage:
    items: tuple[ScheduleRunHistoryItem, ...]
    next_cursor: str | None


class ScheduleRunHistoryService:
    """Project dispatch attempts without exposing a mutation method."""

    def __init__(self, *, ledger: ScheduleRunLedger) -> None:
        self._ledger = ledger

    async def list(
        self,
        *,
        task_id: str,
        limit: int = 50,
        cursor: str | None = None,
        status: ScheduleDispatchStatus | None = None,
    ) -> ScheduleRunHistoryPage:
        if not task_id:
            raise ValueError("schedule history task_id MUST be non-empty")
        if not 1 <= limit <= 200:
            raise ValueError("schedule history limit MUST be in [1, 200]")
        boundary = _decode_cursor(cursor) if cursor is not None else None
        runs = sorted(
            await self._ledger.list_for_task(task_id),
            key=lambda run: (run.scheduled_for, run.run_id),
            reverse=True,
        )
        filtered = [
            run
            for run in runs
            if (status is None or run.status is status)
            and (boundary is None or (run.scheduled_for, run.run_id) < boundary)
        ]
        selected = filtered[:limit]
        next_cursor = None
        if len(filtered) > limit and selected:
            last = selected[-1]
            next_cursor = _encode_cursor(last.scheduled_for, last.run_id)
        return ScheduleRunHistoryPage(
            items=tuple(_item(run) for run in selected),
            next_cursor=next_cursor,
        )


def _item(run: ScheduleDispatchRun) -> ScheduleRunHistoryItem:
    return ScheduleRunHistoryItem(
        run_id=run.run_id,
        task_id=run.task_id,
        scheduled_for=run.scheduled_for.isoformat(),
        claimed_at=run.claimed_at.isoformat(),
        status=run.status.value,
        attempt=run.attempt,
        completed_at=run.completed_at.isoformat() if run.completed_at is not None else None,
        error_kind=run.error_kind,
    )


def _encode_cursor(scheduled_for: datetime, run_id: str) -> str:
    raw = json.dumps(
        {"scheduled_for": scheduled_for.isoformat(), "run_id": run_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded))
        scheduled_for = datetime.fromisoformat(parsed["scheduled_for"])
        run_id = parsed["run_id"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("schedule history cursor is invalid") from exc
    if not isinstance(run_id, str) or not run_id or scheduled_for.tzinfo is None:
        raise ValueError("schedule history cursor is invalid")
    return scheduled_for, run_id


__all__ = [
    "ScheduleRunHistoryItem",
    "ScheduleRunHistoryPage",
    "ScheduleRunHistoryService",
]

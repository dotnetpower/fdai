"""Read-only scheduler dispatch history panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.scheduler import ScheduleDispatchStatus, ScheduleRunHistoryService
from fdai.delivery.operator_api.routes.panels import PanelQueryError


class SchedulerRunsPanel:
    """Project task-scoped dispatch attempts without mutation authority."""

    path = "/scheduler-runs"
    name = "scheduler-runs"

    def __init__(
        self,
        *,
        service: ScheduleRunHistoryService,
        source: str,
        durable: bool,
    ) -> None:
        self._service = service
        self._source = source
        self._durable = durable

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        task_id = params.get("task_id", "").strip()
        if not task_id:
            raise PanelQueryError("task_id MUST be provided")
        try:
            limit = int(params.get("limit", "50"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        raw_status = params.get("status", "").strip()
        try:
            status = ScheduleDispatchStatus(raw_status) if raw_status else None
            page = await self._service.list(
                task_id=task_id,
                limit=limit,
                cursor=params.get("cursor") or None,
                status=status,
            )
        except ValueError as exc:
            raise PanelQueryError(str(exc)) from exc
        return {
            "task_id": task_id,
            "source": self._source,
            "durable": self._durable,
            "items": [
                {
                    "run_id": item.run_id,
                    "task_id": item.task_id,
                    "scheduled_for": item.scheduled_for,
                    "claimed_at": item.claimed_at,
                    "status": item.status,
                    "attempt": item.attempt,
                    "completed_at": item.completed_at,
                    "error_kind": item.error_kind,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
        }


__all__ = ["SchedulerRunsPanel"]

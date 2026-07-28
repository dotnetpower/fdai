"""Complete-window reader for audit-derived autonomy measurements."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.delivery.read_api.read_model import (
    MAX_LIMIT,
    AuditItem,
    AuditQueryFilters,
    ConsoleReadModel,
)
from fdai.delivery.read_api.routes.audit_measurement_projection import audit_payload

_AUTONOMY_ACTORS = (
    "fdai.core.control_loop",
    "fdai.core.executor.direct_api",
    "fdai.core.executor.shadow",
    "fdai.core.executor.tool_call",
)


class AuditAutonomyMeasurementPanel:
    """Project one sequence-stable autonomy snapshot from the durable audit window."""

    def __init__(
        self,
        read_model: ConsoleReadModel,
        *,
        active_rule_count: int = 0,
        window_days: int = 30,
    ) -> None:
        self._read_model = read_model
        self._active_rule_count = active_rule_count
        self._window_days = window_days

    @property
    def path(self) -> str:
        return "/kpi/autonomy"

    @property
    def name(self) -> str:
        return "autonomy"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        evidence_items = await _read_complete_window(
            self._read_model,
            window_days=self._window_days,
        )
        event_items = tuple(item for item in evidence_items if item.actor in _AUTONOMY_ACTORS)
        return audit_payload(
            event_items,
            window_days=self._window_days,
            active_rule_count=self._active_rule_count,
            supplemental_items=evidence_items,
        )


async def _read_complete_window(
    read_model: ConsoleReadModel,
    *,
    window_days: int,
) -> tuple[AuditItem, ...]:
    head = await read_model.list_audit(limit=1)
    if not head.items:
        return ()
    snapshot_seq = head.items[0].seq
    window_start = datetime.now(tz=UTC) - timedelta(days=window_days)
    filters = AuditQueryFilters(
        recorded_at_from=window_start,
        through_seq=snapshot_seq,
    )
    items: list[AuditItem] = []
    cursor: str | None = None
    while True:
        page = await read_model.list_audit(
            limit=MAX_LIMIT,
            cursor=cursor,
            filters=filters,
        )
        items.extend(page.items)
        if page.next_cursor is None:
            return tuple(items)
        if page.next_cursor == cursor:
            raise RuntimeError("audit pagination cursor did not advance")
        cursor = page.next_cursor


__all__ = ["AuditAutonomyMeasurementPanel"]

"""Delivery-side reference implementation of :class:`AuditTraceReader`.

Wraps any :class:`~fdai.delivery.read_api.read_model.ConsoleReadModel`
and adapts its paged :class:`AuditItem` output to the minimal
:class:`~fdai.core.audit.rule_fire_trace.AuditItemLike` Protocol the
core trace builder consumes.

Placement rationale: importing the delivery-side ``ConsoleReadModel``
here is legal (this module IS delivery), and it keeps ``core/`` clear
of any delivery dependency (see ``check-core-imports.sh`` gate).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from fdai.core.audit.rule_fire_trace import AuditItemLike
from fdai.delivery.read_api.read_model import AuditItem, ConsoleReadModel


class ConsoleReadModelTraceReader:
    """Reference :class:`~fdai.core.audit.rule_fire_trace.AuditTraceReader`.

    Scans the read-model's audit stream in pages and collects items
    that match the requested ``correlation_id``. Ordering is
    stable: newest-first pages are reversed so the returned sequence
    is oldest-first (matching the trace's natural narrative).
    """

    def __init__(self, read_model: ConsoleReadModel, *, page_size: int = 500) -> None:
        self._read_model = read_model
        self._page_size = page_size

    async def read_items(self, correlation_id: str) -> Sequence[AuditItemLike]:
        matches: list[AuditItem] = []
        cursor: str | None = None
        while True:
            page = await self._read_model.list_audit(
                limit=self._page_size,
                cursor=cursor,
                correlation_id=correlation_id,
            )
            matches.extend(page.items)
            if not page.next_cursor or not page.items:
                break
            cursor = page.next_cursor
        matches.sort(key=lambda item: item.seq)
        # AuditItem is structurally an AuditItemLike (has correlation_id
        # and seq); the return type is a Sequence, so widen the concrete
        # list to satisfy the protocol.
        return cast("list[AuditItemLike]", matches)


__all__ = ["ConsoleReadModelTraceReader"]

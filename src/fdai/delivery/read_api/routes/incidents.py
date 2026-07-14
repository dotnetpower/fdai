"""First-class read-only incident roster panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.read_model import (
    DEFAULT_LIMIT,
    ConsoleReadModel,
    clamp_limit,
)
from fdai.delivery.read_api.routes.panels import PanelQueryError

_VALID_STATUSES: frozenset[str] = frozenset({"active", "resolved", "all"})


class IncidentsPanel:
    """Project the audit ledger into an incident-centric roster."""

    def __init__(self, read_model: ConsoleReadModel) -> None:
        self._read_model = read_model

    @property
    def path(self) -> str:
        return "/incidents"

    @property
    def name(self) -> str:
        return "incidents"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        requested_status = params.get("status", "active")
        if requested_status not in _VALID_STATUSES:
            raise PanelQueryError("status MUST be one of: active, resolved, all")
        raw_limit = params.get("limit")
        try:
            limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        cursor = params.get("cursor") or None
        try:
            page = await self._read_model.list_incidents(
                status=requested_status,  # type: ignore[arg-type]
                limit=clamp_limit(limit),
                cursor=cursor,
            )
        except ValueError as exc:
            raise PanelQueryError(str(exc)) from exc
        return page.to_dict()


__all__ = ["IncidentsPanel"]

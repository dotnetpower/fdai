"""Read-only operator-memory governance review panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.operator_memory import (
    MemoryCompactionRepository,
    OperatorMemoryReviewService,
    ScopeKind,
)
from fdai.delivery.operator_api.routes.panels import PanelQueryError


class OperatorMemoryPanel:
    path = "/operator-memory"
    name = "operator-memory"

    def __init__(
        self,
        *,
        service: OperatorMemoryReviewService,
        compactions: MemoryCompactionRepository | None = None,
    ) -> None:
        self._service = service
        self._compactions = compactions

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            limit = int(params.get("limit", "100"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        raw_scope_kind = params.get("scope_kind", "").strip()
        try:
            scope_kind = ScopeKind(raw_scope_kind) if raw_scope_kind else None
        except ValueError as exc:
            raise PanelQueryError("scope_kind MUST be resource-group or resource") from exc
        scope_ref = params.get("scope_ref", "").strip() or None
        try:
            items = await self._service.list(
                limit=limit,
                scope_kind=scope_kind,
                scope_ref=scope_ref,
            )
        except ValueError as exc:
            raise PanelQueryError(str(exc)) from exc
        candidates = (
            await self._compactions.list(limit=limit) if self._compactions is not None else ()
        )
        return {
            "items": [item.to_dict() for item in items],
            "compactions": [
                {
                    "candidate_id": candidate.candidate_id,
                    "scope_kind": candidate.scope_kind,
                    "scope_ref": candidate.scope_ref,
                    "category": candidate.category,
                    "body": candidate.body,
                    "source_entry_ids": [str(value) for value in candidate.source_entry_ids],
                    "source_refs": list(candidate.source_refs),
                    "proposed_by_agent": candidate.proposed_by_agent,
                    "state": candidate.state.value,
                    "reviewed_by": candidate.reviewed_by,
                    "review_reason": candidate.review_reason,
                    "promoted_entry_id": (
                        str(candidate.promoted_entry_id)
                        if candidate.promoted_entry_id is not None
                        else None
                    ),
                }
                for candidate in candidates
            ],
        }


__all__ = ["OperatorMemoryPanel"]

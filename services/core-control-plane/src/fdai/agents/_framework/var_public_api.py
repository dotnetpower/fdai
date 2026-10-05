"""Small public helper methods for Var kept outside the pantheon file."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.introspection import IntrospectionResult
from fdai.agents._framework.var_admin import deliver_admin_card as _deliver_admin_card
from fdai.agents._framework.var_health import health as _var_health
from fdai.agents._framework.var_introspection import evidence_available as _evidence_available
from fdai.agents._framework.var_introspection import introspect_var as _introspect_var
from fdai.agents._framework.var_shadow_review import decide_shadow_review_once
from fdai.agents._framework.var_ticket_identity import (
    PendingHilTicket,
    PendingShadowReview,
)
from fdai.agents._framework.var_ticket_identity import (
    record_blocked_attempt as _record_blocked_attempt_once,
)


class VarPublicApiMixin:
    """Expose Var's helper API without growing the pantheon member file."""

    async def decide_shadow_review(
        self,
        correlation_id: str,
        *,
        reviewer: str,
        agreed: bool,
    ) -> dict[str, Any] | None:
        """Publish one real human review without manufacturing another sample."""

        return await decide_shadow_review_once(
            pending=self._pending_shadow_reviews,  # type: ignore[attr-defined]
            locks=self._shadow_review_locks,  # type: ignore[attr-defined]
            state_store=self._state_store,  # type: ignore[attr-defined]
            bus=self.bus,  # type: ignore[attr-defined]
            record_behavior=self.record_behavior,  # type: ignore[attr-defined]
            record_blocked_attempt=self._record_blocked_attempt,
            correlation_id=correlation_id,
            reviewer=reviewer,
            agreed=agreed,
        )

    def pending_tickets(self) -> tuple[PendingHilTicket, ...]:
        return tuple(self._pending.values())  # type: ignore[attr-defined]

    def pending_shadow_reviews(self) -> tuple[PendingShadowReview, ...]:
        return tuple(self._pending_shadow_reviews.values())  # type: ignore[attr-defined]

    def _record_blocked_attempt(self, key: str, correlation_id: str, approver: str) -> None:
        _record_blocked_attempt_once(self, key, correlation_id, approver)  # type: ignore[arg-type]

    deliver_admin_card = _deliver_admin_card
    health = _var_health

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        return _evidence_available(self)  # type: ignore[arg-type]

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        return await _introspect_var(self, question, context)  # type: ignore[arg-type]


__all__ = ["VarPublicApiMixin"]

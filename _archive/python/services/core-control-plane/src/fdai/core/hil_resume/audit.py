"""Canonical audit persistence for HIL approval lifecycle events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore


class HilAuditMixin:
    """Build and append canonical HIL audit entries."""

    _actor: str
    _state_store: StateStore

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> None:
        await self._state_store.append_audit_entry(
            self._audit_entry(
                action_kind=action_kind,
                idempotency_key=idempotency_key,
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail=detail,
            )
        )

    def _audit_entry(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "actor": self._actor,
            "action_kind": action_kind,
            "mode": Mode.SHADOW.value,
            "idempotency_key": idempotency_key,
            "approval_id": approval_id,
            "correlation_id": correlation_id,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            **dict(detail),
        }


__all__ = ["HilAuditMixin"]

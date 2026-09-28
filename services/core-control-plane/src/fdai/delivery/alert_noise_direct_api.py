"""Fail-closed alert direct-API route until a provider adapter is explicitly bound."""

from __future__ import annotations

from typing import Protocol

from fdai.core.detection.alert_noise.action_types import ALERT_ACTIONS
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.shared.contracts.models import Action
from fdai.shared.providers.direct_api import (
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
)


class UnavailableAlertDirectApiExecutor:
    """Prevent generic direct-API fallbacks from receiving alert mutations."""

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name not in ALERT_ACTIONS:
            raise DirectApiPreconditionError("request is not an alert-noise action")
        raise DirectApiPreconditionError("alert provider mutation adapter is not configured")


class _DirectApiExecutionPort(Protocol):
    async def execute(self, *, action: Action) -> DirectApiExecutionResult: ...


class AlertUnavailableDirectApiExecutionPort:
    """Route alert actions to an audited hold before any generic direct-API fallback."""

    def __init__(
        self,
        *,
        unavailable: _DirectApiExecutionPort,
        fallback: _DirectApiExecutionPort | None,
    ) -> None:
        self._unavailable = unavailable
        self._fallback = fallback

    async def execute(self, *, action: Action) -> DirectApiExecutionResult:
        if action.action_type in ALERT_ACTIONS or self._fallback is None:
            return await self._unavailable.execute(action=action)
        return await self._fallback.execute(action=action)


__all__ = ["AlertUnavailableDirectApiExecutionPort", "UnavailableAlertDirectApiExecutor"]

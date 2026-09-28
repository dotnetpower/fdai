"""Fail-closed alert direct-API route until a provider adapter is explicitly bound."""

from __future__ import annotations

import logging
from typing import Protocol

from fdai.core.detection.alert_noise.action_types import ALERT_ACTIONS
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.shared.contracts.execution_outcomes import DirectApiExecutionOutcome
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.direct_api import (
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
)

_LOGGER = logging.getLogger(__name__)


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
        if action.action_type in ALERT_ACTIONS:
            return await self._unavailable.execute(action=action)
        if self._fallback is None:
            # Other ActionTypes keep the control loop's unwired-executor rejection.
            reason = f"execution_path {ExecutionPath.DIRECT_API.value!r} has no wired executor"
            _LOGGER.warning(
                "action_dispatch_executor_unavailable",
                extra={
                    "action_type": action.action_type,
                    "execution_path": ExecutionPath.DIRECT_API.value,
                    "idempotency_key": action.idempotency_key,
                },
            )
            return DirectApiExecutionResult(
                action_id=str(action.action_id),
                outcome=DirectApiExecutionOutcome.REJECTED_INVARIANT,
                mode=action.mode,
                reason=reason,
            )
        return await self._fallback.execute(action=action)


__all__ = ["AlertUnavailableDirectApiExecutionPort", "UnavailableAlertDirectApiExecutor"]

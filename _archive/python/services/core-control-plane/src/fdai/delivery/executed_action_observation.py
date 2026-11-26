"""Mechanical Heimdall handler for terminal executed-action observations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.ontology_platform import (
    EffectReconciliationRequestSink,
    ExecutedActionObservation,
    ExecutedActionObservationCollector,
    ReconciliationRequestProductionStatus,
    ResolvedReconciliationArtifacts,
)
from fdai.delivery.reconciliation_artifacts import StateStoreExecutedActionArtifactStore
from fdai.delivery.reconciliation_observations import StateStoreExecutedActionObservationStore
from fdai.shared.contracts.models import Action, Mode

_TERMINAL_STATES = frozenset({"succeeded", "rolled_back", "rollback_failed"})


class ActionRoutedExecutedActionObservationCollector:
    """Route exact ActionTypes to independent observation collectors."""

    def __init__(
        self,
        collectors: Mapping[str, ExecutedActionObservationCollector],
    ) -> None:
        if not collectors or any(not action_type.strip() for action_type in collectors):
            raise ValueError("executed Action observation routes MUST be non-empty")
        self._collectors = dict(collectors)

    async def collect(
        self,
        *,
        action: Action,
        artifacts: ResolvedReconciliationArtifacts,
        execution_outcome: str,
        execution_completed_at: datetime,
        execution_receipt_ref: str | None,
        correlation_id: str,
    ) -> ExecutedActionObservation | None:
        """Collect through the exact ActionType route or report not applicable."""

        collector = self._collectors.get(action.action_type)
        if collector is None:
            return None
        return await collector.collect(
            action=action,
            artifacts=artifacts,
            execution_outcome=execution_outcome,
            execution_completed_at=execution_completed_at,
            execution_receipt_ref=execution_receipt_ref,
            correlation_id=correlation_id,
        )


class HeimdallExecutedActionObservationHandler:
    """Collect and seal one exact terminal observation without judging it."""

    def __init__(
        self,
        *,
        artifacts: StateStoreExecutedActionArtifactStore,
        collector: ExecutedActionObservationCollector,
        observations: StateStoreExecutedActionObservationStore,
        reconciliation_requests: EffectReconciliationRequestSink | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._collector = collector
        self._observations = observations
        self._reconciliation_requests = reconciliation_requests

    async def handle(self, payload: Mapping[str, Any]) -> bool:
        if payload.get("producer_principal") != "Thor":
            raise ValueError("executed ActionRun observation trigger MUST be produced by Thor")
        state = str(payload.get("state") or "")
        if state not in _TERMINAL_STATES:
            return False
        terminal_at_raw = payload.get("terminal_at")
        if not isinstance(terminal_at_raw, str):
            raise ValueError("executed ActionRun terminal timestamp MUST be text")
        try:
            terminal_at = datetime.fromisoformat(terminal_at_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("executed ActionRun terminal timestamp is invalid") from exc
        if terminal_at.tzinfo is None or terminal_at.utcoffset() is None:
            raise ValueError("executed ActionRun terminal timestamp MUST be timezone-aware")
        terminal_at = terminal_at.astimezone(UTC)
        correlation_id = str(payload.get("correlation_id") or "")
        if not correlation_id or len(correlation_id) > 512:
            raise ValueError("executed ActionRun observation correlation MUST be bounded")
        restored = await self._artifacts.resolve_by_correlation(correlation_id)
        if restored is None:
            return False
        action, artifacts = restored
        if (
            payload.get("action_type") != action.action_type
            or payload.get("resource_id") != action.target_resource_ref
            or payload.get("action_idempotency_key") != action.idempotency_key
        ):
            raise ValueError("executed ActionRun observation trigger changed exact Action identity")
        shadow_mode = payload.get("shadow_mode")
        if not isinstance(shadow_mode, bool):
            raise ValueError("executed ActionRun shadow mode MUST be boolean")
        if shadow_mode:
            return False
        if action.mode is not Mode.ENFORCE:
            raise ValueError("executed ActionRun cannot raise a shadow Action to enforce")
        receipt_ref = payload.get("execution_audit_receipt")
        if receipt_ref is not None and not isinstance(receipt_ref, str):
            raise ValueError("executed ActionRun receipt reference MUST be text or null")
        if receipt_ref is None or not receipt_ref.strip() or len(receipt_ref) > 512:
            raise ValueError("enforced ActionRun observation requires an execution audit receipt")
        observation = await self._observations.observe(
            action=action,
            artifacts=artifacts,
            execution_outcome=state,
            execution_receipt_ref=receipt_ref,
            correlation_id=correlation_id,
        )
        if observation is None:
            observation = await self._collector.collect(
                action=action,
                artifacts=artifacts,
                execution_outcome=state,
                execution_completed_at=terminal_at,
                execution_receipt_ref=receipt_ref,
                correlation_id=correlation_id,
            )
            if observation is None:
                return False
            await self._observations.record(
                producer_principal="Heimdall",
                action=action,
                artifacts=artifacts,
                execution_outcome=state,
                execution_receipt_ref=receipt_ref,
                correlation_id=correlation_id,
                observation=observation,
                execution_mode=action.mode.value,
                execution_completed_at=terminal_at,
            )
        if self._reconciliation_requests is not None:
            production = await self._reconciliation_requests(
                action,
                state,
                receipt_ref,
                correlation_id=correlation_id,
            )
            if production.status is ReconciliationRequestProductionStatus.NOT_APPLICABLE:
                raise RuntimeError(
                    "recorded executed Action observation did not produce reconciliation"
                )
            if (
                production.status is ReconciliationRequestProductionStatus.HELD
                and production.reason_code != "durably_queued"
            ):
                raise RuntimeError(
                    "recorded executed Action observation reconciliation is not durable"
                )
        return True


__all__ = [
    "ActionRoutedExecutedActionObservationCollector",
    "HeimdallExecutedActionObservationHandler",
]

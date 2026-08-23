"""Mechanical Heimdall handler for terminal executed-action observations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.ontology_platform import ExecutedActionObservationCollector
from fdai.delivery.reconciliation_artifacts import StateStoreExecutedActionArtifactStore
from fdai.delivery.reconciliation_observations import StateStoreExecutedActionObservationStore

_TERMINAL_STATES = frozenset({"succeeded", "rolled_back", "rollback_failed"})


class HeimdallExecutedActionObservationHandler:
    """Collect and seal one exact terminal observation without judging it."""

    def __init__(
        self,
        *,
        artifacts: StateStoreExecutedActionArtifactStore,
        collector: ExecutedActionObservationCollector,
        observations: StateStoreExecutedActionObservationStore,
    ) -> None:
        self._artifacts = artifacts
        self._collector = collector
        self._observations = observations

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
        receipt_ref = payload.get("execution_receipt_ref")
        if receipt_ref is not None and not isinstance(receipt_ref, str):
            raise ValueError("executed ActionRun receipt reference MUST be text or null")
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
        )
        return True


__all__ = ["HeimdallExecutedActionObservationHandler"]

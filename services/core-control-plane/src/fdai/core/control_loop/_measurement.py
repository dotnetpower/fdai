"""Persist terminal classifications independently of execution outcome evidence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fdai_service_contracts.control_loop_measurement import (
    CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    CONTROL_LOOP_MEASUREMENT_ACTOR,
    ControlLoopMeasurement,
    control_loop_measurement_id,
)
from pydantic import ValidationError

from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.shared.contracts.models import Event
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "measurement:control-loop:v1:"


def build_control_loop_measurement(
    event: Event, result: ControlLoopResult, *, recorded_at: datetime
) -> ControlLoopMeasurement:
    """Capture only source identity and the terminal classification, never success."""
    return ControlLoopMeasurement.model_validate(
        _terminal_fields(event, result, recorded_at=recorded_at)
    )


def _terminal_fields(
    event: Event, result: ControlLoopResult, *, recorded_at: datetime
) -> dict[str, object]:
    synthetic = event.payload.get("synthetic")
    return {
        "measurement_id": control_loop_measurement_id(event.idempotency_key),
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "correlation_id": event.correlation_id,
        "source": event.source,
        "event_type": event.event_type,
        "mode": event.mode.value,
        "synthetic": synthetic if isinstance(synthetic, bool) else None,
        "occurred_at": event.detected_at,
        "ingested_at": event.ingested_at,
        "recorded_at": recorded_at,
        "tier": result.tier if result.tier in {"t0", "t1", "t2"} else None,
        "terminal_outcome": result.outcome.value,
        "gate_route": result.decision,
        "resource_type": result.resource_type,
        "action_ids": tuple(execution.action_id for execution in result.execution_results),
    }


def control_loop_measurement_audit_entry(
    measurement: ControlLoopMeasurement,
) -> dict[str, object]:
    """Flatten the versioned measurement into its canonical audit envelope."""
    return {
        "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
        "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
        **measurement.model_dump(mode="json"),
    }


class TerminalMeasurementRecorder:
    """Atomically persist each terminal once and retain failed writes for retry.

    Pending fields are captured before validation or any persistence await. The owning loop
    retries storage failures before ingest can discard a redelivery. Invalid captures
    are retained as explicit rejection evidence and removed from pending memory so
    one malformed record cannot poison unrelated events. Errors propagate; valid
    retries preserve the original classification and capture time.
    Durable uniqueness survives a new loop instance. Pending memory does not:
    after process loss an unpersisted event requires source redelivery through
    a fresh ingest instance, just like the control loop's other audit writes.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._pending: dict[UUID, dict[str, object]] = {}

    async def record(
        self, event: Event, result: ControlLoopResult, *, recorded_at: datetime
    ) -> None:
        """Retain a terminal before writing; a duplicate result is not an event."""
        if result.outcome is ControlLoopOutcome.DEDUPED:
            return
        identity = control_loop_measurement_id(event.idempotency_key)
        fields = _terminal_fields(event, result, recorded_at=recorded_at)
        retained = self._pending.setdefault(identity, fields)
        await self._persist(identity, retained)

    async def retry_pending(self) -> None:
        """Repair failed writes before another event enters the ingest dedupe cache."""
        for identity, fields in tuple(self._pending.items()):
            await self._persist(identity, fields)

    async def _persist(self, identity: UUID, fields: dict[str, object]) -> None:
        try:
            measurement = ControlLoopMeasurement.model_validate(fields)
        except ValidationError:
            rejected = {
                "measurement_id": str(identity),
                "event_id": str(fields["event_id"]),
                "reason": "invalid_terminal_measurement",
                "synthetic": fields["synthetic"],
            }
            await self._store.write_state_with_audit_if_absent(
                f"measurement:control-loop:rejected:{identity}",
                rejected,
                {
                    **rejected,
                    "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
                    "action_kind": "measurement.control_loop.rejected.v1",
                    "mode": fields["mode"],
                    "occurred_at": _audit_time(fields["occurred_at"]),
                    "recorded_at": _audit_time(fields["recorded_at"]),
                },
            )
            self._pending.pop(identity, None)
            raise ValueError(
                "terminal measurement rejected; classification evidence is incomplete"
            ) from None
        payload = measurement.model_dump(mode="json")
        key = f"{_STATE_PREFIX}{measurement.measurement_id}"
        created = await self._store.write_state_with_audit_if_absent(
            key,
            payload,
            control_loop_measurement_audit_entry(measurement),
        )
        if not created:
            existing = await self._store.read_state(key)
            if existing is None:
                raise ValueError("terminal measurement disappeared after duplicate detection")
            previous = ControlLoopMeasurement.model_validate(existing)
            comparable = previous.model_copy(
                update={
                    "ingested_at": measurement.ingested_at,
                    "recorded_at": measurement.recorded_at,
                }
            )
            if comparable != measurement:
                raise ValueError("terminal measurement identity conflicts with retained evidence")
        self._pending.pop(measurement.measurement_id, None)


def _audit_time(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None

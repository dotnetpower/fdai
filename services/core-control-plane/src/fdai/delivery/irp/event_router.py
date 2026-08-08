"""Bridge alert investigations back into the governed typed pipeline."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.irp import Alert, IrpCoordinator, IrpResult, MitigationProposal
from fdai.core.report_feed import signal_from_irp, signals_from_investigation
from fdai.core.report_feed.models import ReportSignal
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.event_bus import EventBus

_ALERT_EVENT_TYPES = frozenset({"azure.monitor.alert", "monitor.alert"})


class ReportSignalWriter(Protocol):
    async def record(self, signal: ReportSignal) -> None: ...

    async def record_many(self, signals: tuple[ReportSignal, ...] | list[ReportSignal]) -> None: ...


class EventBusIrpProposalRouter:
    """Publish an IRP recommendation as a normal operator-request envelope."""

    def __init__(self, *, bus: EventBus, topic: str) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        self._bus = bus
        self._topic = topic

    async def route(self, proposal: MitigationProposal) -> None:
        target = proposal.target_resource_ref or proposal.alert_id
        raw_key = f"{proposal.alert_id}:{proposal.remediation_ref}:{target}"
        idempotency_key = f"irp:{hashlib.sha256(raw_key.encode()).hexdigest()[:32]}"
        payload: dict[str, object] = {
            "idempotency_key": idempotency_key,
            "correlation_id": f"irp:{proposal.alert_id}",
            "initiator_principal": "IrpCoordinator",
            "operator_initiated": True,
            "action_type": "tool.file-irp-followup",
            "resource_id": target,
            "event_type": "operator_request",
            "params": {
                "alert_id": proposal.alert_id,
                "remediation_ref": proposal.remediation_ref,
                "resource_ref": target,
                "priority": proposal.priority.value,
                "detail": proposal.detail,
            },
        }
        await self._bus.publish(self._topic, target, payload)


class IrpEventHandler:
    """Run IRP only for alert-shaped events and persist its report signals."""

    def __init__(
        self,
        *,
        coordinator: IrpCoordinator,
        signal_writer: ReportSignalWriter | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._signal_writer = signal_writer

    async def handle(self, payload: Mapping[str, Any]) -> IrpResult | None:
        event_type = str(payload.get("event_type") or "")
        if not (event_type.startswith("analyzer.") or event_type in _ALERT_EVENT_TYPES):
            return None
        alert = _to_alert(payload, event_type=event_type)
        result = await self._coordinator.respond(alert)
        if self._signal_writer is not None:
            await self._signal_writer.record_many(signals_from_investigation(result.report))
            await self._signal_writer.record(signal_from_irp(result))
        return result


class RuntimeSettingsIrpEventHandler:
    """Resolve enablement and budget from durable settings per alert."""

    def __init__(
        self,
        *,
        settings: RuntimeSettingsService,
        handler_factory: Callable[[float], IrpEventHandler],
    ) -> None:
        self._settings = settings
        self._handler_factory = handler_factory

    async def handle(self, payload: Mapping[str, Any]) -> IrpResult | None:
        event_type = str(payload.get("event_type") or "")
        if not (event_type.startswith("analyzer.") or event_type in _ALERT_EVENT_TYPES):
            return None
        effective = await self._settings.effective_values()
        if effective["irp.enabled"] is not True:
            return None
        budget_seconds = effective["irp.budget_seconds"]
        if not isinstance(budget_seconds, (int, float)) or isinstance(budget_seconds, bool):
            raise RuntimeError("effective IRP budget is invalid")
        return await self._handler_factory(float(budget_seconds)).handle(payload)


def _to_alert(payload: Mapping[str, Any], *, event_type: str) -> Alert:
    nested_payload = payload.get("payload")
    body = nested_payload if isinstance(nested_payload, Mapping) else payload
    resource = body.get("resource")
    resource_mapping = resource if isinstance(resource, Mapping) else {}
    resource_ref = str(
        payload.get("resource_ref")
        or resource_mapping.get("resource_id")
        or resource_mapping.get("resource_ref")
        or ""
    )
    resource_kind = str(
        resource_mapping.get("type") or resource_mapping.get("resource_type") or "unknown"
    )
    if not resource_ref:
        raise ValueError("alert event resource_ref MUST be non-empty")
    finding = body.get("finding")
    finding_mapping = finding if isinstance(finding, Mapping) else {}
    signal = str(finding_mapping.get("signal") or event_type)
    alert_id = str(
        payload.get("event_id") or payload.get("id") or payload.get("idempotency_key") or ""
    )
    if not alert_id:
        raise ValueError("alert event id MUST be non-empty")
    fired_at = _timestamp(payload.get("detected_at") or payload.get("fired_at"))
    return Alert(
        alert_id=alert_id,
        signal=signal,
        resources=((resource_ref, resource_kind),),
        fired_at=fired_at,
    )


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.now(tz=UTC)


__all__ = [
    "EventBusIrpProposalRouter",
    "IrpEventHandler",
    "ReportSignalWriter",
    "RuntimeSettingsIrpEventHandler",
]

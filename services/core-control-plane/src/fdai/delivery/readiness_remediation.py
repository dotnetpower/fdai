"""EventBus publication of authority-free Operational Readiness remediations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.readiness_remediation import (
    READINESS_REMEDIATION_EVENT_SOURCE,
    READINESS_REMEDIATION_EVENT_TYPE,
    READINESS_REMEDIATION_REQUEST_TOPIC,
    ReadinessRemediationRequest,
)

from fdai.shared.contracts.models import Event, Mode, Rule
from fdai.shared.providers.event_bus import EventBus


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class EventBusReadinessRemediationPublisher:
    """Convert one grounded proposal into the typed shadow ingress contract."""

    event_bus: EventBus
    target_revision: str
    rules_by_id: Mapping[str, Rule]
    clock: Callable[[], datetime] = _utc_now
    topic: str = READINESS_REMEDIATION_REQUEST_TOPIC

    async def publish_remediation_proposal(self, proposal: Mapping[str, Any]) -> None:
        if proposal.get("kind") != "operational_readiness.remediation_proposal":
            raise ValueError("readiness remediation proposal kind is invalid")
        if not isinstance(proposal.get("blocking"), bool):
            raise ValueError("readiness remediation proposal blocking MUST be boolean")
        if (
            not self.target_revision.startswith("sha256:")
            or len(self.target_revision) != 71
            or any(character not in "0123456789abcdef" for character in self.target_revision[7:])
        ):
            raise ValueError("readiness remediation target revision MUST be a SHA-256 digest")
        action_type = _exact_text(proposal, "action_type")
        resource_ref = _exact_text(proposal, "resource_ref")
        rule_id = _exact_text(proposal, "evidence")
        transfer_id = _exact_text(proposal, "transfer_id")
        submitter = _exact_text(proposal, "submitter")
        approver = _exact_text(proposal, "approver")
        idempotency_key = _exact_text(proposal, "idempotency_key")
        approved_at = _timestamp(proposal, "approved_at")
        severity = _exact_text(proposal, "severity")
        if proposal.get("mode") != Mode.SHADOW.value:
            raise ValueError("readiness remediation proposal MUST remain shadow")
        rule = self.rules_by_id.get(rule_id)
        if rule is None:
            raise ValueError(f"readiness remediation proposal cites unknown rule {rule_id!r}")
        if rule.remediates != action_type:
            raise ValueError(
                f"readiness remediation rule {rule_id!r} does not remediate {action_type!r}"
            )
        requested_at = self.clock()
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("readiness remediation publisher clock MUST include a timezone")
        request = ReadinessRemediationRequest.create(
            idempotency_key=idempotency_key,
            action_type=action_type,
            target_resource_ref=resource_ref,
            target_revision=self.target_revision,
            params=dict(rule.parameters),
            citing_rule_ids=(rule.id,),
            evidence_refs=(f"operational-readiness-report:{transfer_id}",),
            submitter=submitter,
            approver=approver,
            approved_at=approved_at,
            requested_at=requested_at,
            severity=severity,  # type: ignore[arg-type]
        )
        event = Event(
            schema_version="1.0.0",
            event_id=uuid5(NAMESPACE_URL, f"fdai://{request.request_id}"),
            idempotency_key=request.idempotency_key,
            correlation_id=request.request_id,
            source=READINESS_REMEDIATION_EVENT_SOURCE,
            event_type=READINESS_REMEDIATION_EVENT_TYPE,
            resource_ref=request.target_resource_ref,
            payload={
                "readiness_remediation_request": request.model_dump(mode="json"),
                "resource": {"resource_type": rule.resource_type},
            },
            detected_at=requested_at,
            ingested_at=requested_at,
            mode=Mode.SHADOW,
        )
        await self.event_bus.publish(
            self.topic,
            request.target_resource_ref,
            event.model_dump(mode="json"),
        )


def _exact_text(proposal: Mapping[str, Any], field_name: str) -> str:
    value = proposal.get(field_name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"readiness remediation proposal {field_name} MUST be exact text")
    return value


def _timestamp(proposal: Mapping[str, Any], field_name: str) -> datetime:
    raw = _exact_text(proposal, field_name)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"readiness remediation proposal {field_name} MUST be a timestamp"
        ) from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"readiness remediation proposal {field_name} MUST include a timezone")
    return value.astimezone(UTC)


__all__ = ["EventBusReadinessRemediationPublisher"]

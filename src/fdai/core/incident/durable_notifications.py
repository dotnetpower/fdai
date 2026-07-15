"""Durable checkpoint and replay for incident lifecycle notifications."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fdai.shared.contracts.models import IncidentSeverity, IncidentState

from .lifecycle import (
    IncidentLifecycleNotice,
    IncidentLifecycleNotifier,
    IncidentNoticeKind,
)
from .notification_delivery import (
    IncidentNotificationDeliveryStore,
    NotificationClaimStatus,
)
from .notifications import incident_notice_audit_id


@dataclass(frozen=True, slots=True)
class DurableNotificationResult:
    """Whether a notice was delivered now or had a durable checkpoint."""

    status: str
    delivery_result: object | None = None


class DurableIncidentLifecycleNotifier:
    """Wrap a notifier with durable sent checkpoints and audit replay."""

    def __init__(
        self,
        *,
        delegate: IncidentLifecycleNotifier,
        delivery_store: IncidentNotificationDeliveryStore,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("incident notification lease_seconds MUST be >= 1")
        self._delegate = delegate
        self._delivery_store = delivery_store
        self._lease_seconds = lease_seconds

    async def notify(self, notice: IncidentLifecycleNotice) -> DurableNotificationResult:
        audit_id = incident_notice_audit_id(notice)
        now = datetime.now(tz=UTC)
        claim = await self._delivery_store.claim(
            audit_id=audit_id,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        if claim.status is NotificationClaimStatus.SENT:
            return DurableNotificationResult(status="already_delivered")
        if claim.status is NotificationClaimStatus.IN_PROGRESS:
            return DurableNotificationResult(status="in_progress")
        token = claim.token
        if token is None:
            raise RuntimeError("claimed incident notification has no token")

        try:
            delivery = await self._delegate.notify(notice)
        except Exception:
            await self._delivery_store.release(audit_id=audit_id, token=token)
            raise
        await self._delivery_store.complete(
            audit_id=audit_id,
            token=token,
            at=datetime.now(tz=UTC),
        )
        return DurableNotificationResult(status="delivered", delivery_result=delivery)

    async def replay(self, entries: Iterable[Mapping[str, Any]]) -> int:
        """Deliver every lifecycle row without a sent checkpoint."""
        delivered = 0
        severities: dict[UUID, IncidentSeverity] = {}
        for entry in entries:
            if entry.get("kind") in {
                "incident.members",
                "incident.ticket",
            }:
                continue
            incident_id = UUID(_required_string(entry, "incident_id"))
            kind = _required_string(entry, "kind")
            fallback_severity = severities.get(incident_id)
            notice = notice_from_lifecycle_entry(
                entry,
                fallback_severity=fallback_severity,
            )
            notice_severity = notice.incident_severity
            if notice_severity is None:
                raise ValueError("lifecycle notification replay produced no severity")
            if kind in {"incident.open", "incident.transition"}:
                severities[incident_id] = notice_severity
            result = await self.notify(notice)
            if result.status == "delivered":
                delivered += 1
        return delivered


def notice_from_lifecycle_entry(
    entry: Mapping[str, Any],
    *,
    fallback_severity: IncidentSeverity | None = None,
) -> IncidentLifecycleNotice:
    """Reconstruct a strict notification notice from one lifecycle audit row."""
    try:
        kind = _required_string(entry, "kind")
        incident_id = UUID(_required_string(entry, "incident_id"))
        actor_oid = _required_string(entry, "actor_oid")
        if kind == "incident.open":
            open_severity = IncidentSeverity(_required_string(entry, "severity"))
            return IncidentLifecycleNotice(
                kind=IncidentNoticeKind.OPENED,
                actor_oid=actor_oid,
                occurred_at=_aware_datetime(entry, "opened_at"),
                incident_id=incident_id,
                incident_state=IncidentState(_required_string(entry, "state")),
                incident_severity=open_severity,
            )
        if kind == "incident.transition":
            severity_value = _optional_string(entry, "severity")
            transition_severity = (
                IncidentSeverity(severity_value)
                if severity_value is not None
                else fallback_severity
            )
            if transition_severity is None:
                raise ValueError("transition severity is missing and has no prior open")
            return IncidentLifecycleNotice(
                kind=IncidentNoticeKind.STATE_CHANGED,
                actor_oid=actor_oid,
                occurred_at=_aware_datetime(entry, "at"),
                incident_id=incident_id,
                incident_state=IncidentState(_required_string(entry, "to_state")),
                incident_severity=transition_severity,
                previous_state=IncidentState(_required_string(entry, "from_state")),
                reason=_optional_string(entry, "reason"),
            )
        if kind == "incident.assigned":
            return IncidentLifecycleNotice(
                kind=IncidentNoticeKind.ASSIGNED,
                actor_oid=actor_oid,
                occurred_at=_aware_datetime(entry, "at"),
                incident_id=incident_id,
                incident_state=IncidentState(_required_string(entry, "state")),
                incident_severity=IncidentSeverity(_required_string(entry, "severity")),
                reason=("assigned" if _optional_string(entry, "assignee_oid") else "unassigned"),
            )
        raise ValueError(f"unsupported lifecycle kind: {kind}")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid incident notification audit: {exc}") from exc


def _required_string(entry: Mapping[str, Any], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} MUST be a non-empty string")
    return value


def _optional_string(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} MUST be a string or null")
    return value or None


def _aware_datetime(entry: Mapping[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_required_string(entry, key))
    if value.tzinfo is None:
        raise ValueError(f"{key} MUST be timezone-aware")
    return value


__all__ = [
    "DurableIncidentLifecycleNotifier",
    "DurableNotificationResult",
    "notice_from_lifecycle_entry",
]

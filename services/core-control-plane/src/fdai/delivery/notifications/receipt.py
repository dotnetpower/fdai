"""Apply one authenticated notification publication observation to durable state.

The Operator Service owns the public callback ingress and authenticates the
provider report with a deployment-owned shared secret
(:mod:`fdai_service_contracts.notification_receipt`). Core owns the durable
per-channel delivery state and consumes the already-authenticated observation
from the broker.

A provider ``2xx`` proves only that a request was accepted, so this module is
the only path that promotes an ``accepted`` delivery to ``delivered``. It never
creates a delivery, never widens a target set, and never grants execution
authority; an observation that does not match an accepted delivery is rejected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai_service_contracts.notification_receipt import NotificationDeliveryReceipt

from fdai.core.notifications.delivery import (
    ChannelDeliveryRecord,
    NotificationDeliveryStore,
)
from fdai.shared.providers.state_store import StateStore

_ACTOR = "fdai.delivery.notifications.publication-receipt"
_ACTION_KIND = "notification.delivery.observed"


class NotificationReceiptRejectedError(RuntimeError):
    """The observation did not match an accepted delivery and was not applied."""


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class NotificationDeliveryReceiptApplier:
    """Convert one authenticated observation into a durable delivery transition.

    ``apply`` is idempotent for a repeated identical observation because the
    delivery store returns the current record unchanged once the delivery is
    already terminal in the requested state. A conflicting observation for a
    delivery that is not ``accepted`` raises
    :class:`NotificationReceiptRejectedError` so the caller can dead-letter it
    instead of silently rewriting a prior routing decision.
    """

    delivery_store: NotificationDeliveryStore
    audit_store: StateStore
    clock: Callable[[], datetime] = field(default=_utc_now)

    async def apply(self, receipt: NotificationDeliveryReceipt) -> ChannelDeliveryRecord:
        """Append a prepared phase, transition the delivery, then audit completion."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("notification receipt clock MUST be timezone-aware")
        recorded_at = now.astimezone(UTC)
        audit_base: dict[str, object] = {
            "actor": _ACTOR,
            "action_kind": _ACTION_KIND,
            "audit_id": receipt.audit_id,
            "channel_id": receipt.channel_id,
            "receipt_id": receipt.idempotency_key,
            "publication_result": receipt.publication_result,
            "provider_message_id": receipt.provider_message_id,
            "observed_at": receipt.observed_at.astimezone(UTC).isoformat(),
            "recorded_at": recorded_at.isoformat(),
        }
        await self.audit_store.append_audit_entry(
            {
                **audit_base,
                "phase": "prepared",
                "intended_delivery_state": (
                    "delivered" if receipt.published else "retryable_failed"
                ),
            }
        )
        try:
            record = await self._transition(receipt, at=recorded_at)
        except (KeyError, RuntimeError) as exc:
            await self.audit_store.append_audit_entry(
                {
                    **audit_base,
                    "phase": "completed",
                    "delivery_state": "unchanged",
                    "rejection_reason": "delivery_is_not_accepted",
                }
            )
            raise NotificationReceiptRejectedError(
                "notification receipt does not match an accepted delivery"
            ) from exc
        await self.audit_store.append_audit_entry(
            {
                **audit_base,
                "phase": "completed",
                "delivery_state": record.state.value,
                "provider_message_id": record.provider_message_id,
            }
        )
        return record

    async def _transition(
        self,
        receipt: NotificationDeliveryReceipt,
        *,
        at: datetime,
    ) -> ChannelDeliveryRecord:
        if receipt.published:
            return await self.delivery_store.confirm_delivered(
                audit_id=receipt.audit_id,
                channel_id=receipt.channel_id,
                at=at,
                provider_message_id=receipt.provider_message_id,
            )
        return await self.delivery_store.record_publication_failure(
            audit_id=receipt.audit_id,
            channel_id=receipt.channel_id,
            at=at,
            error="notification provider reported a publication failure",
        )


__all__ = [
    "NotificationDeliveryReceiptApplier",
    "NotificationReceiptRejectedError",
]

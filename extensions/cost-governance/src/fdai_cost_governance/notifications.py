"""Activation- and disclosure-gated Cost Governance notification producer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from fdai.shared.providers.cost_governance import CostPackageActivationReader
from fdai.shared.providers.notifications import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai_service_contracts import (
    CostAmountPrecision,
    CostDisclosurePolicy,
    CostProjectionRecord,
    disclose_cost_records,
)

PACKAGE_ID = "fdai-cost-governance"
CATEGORY = "cost_governance"
PRODUCER = "fdai-cost-governance"


class CostNotificationDisclosureReader(Protocol):
    """Return access-safe notification disclosure for one destination scope."""

    async def read_notification_disclosure(
        self,
        destination_scope: str,
        *,
        now: datetime,
    ) -> CostDisclosurePolicy | None: ...


class CostNotificationDispatcher(Protocol):
    """Dispatch one already transformed vendor-neutral notification."""

    async def dispatch(self, message: NotificationMessage) -> object: ...


class CostGovernanceNotificationProducer:
    """Produce package notifications only while enabled and safely disclosed."""

    def __init__(
        self,
        *,
        activation: CostPackageActivationReader,
        disclosure: CostNotificationDisclosureReader,
        dispatcher: CostNotificationDispatcher,
        pseudonym_key: bytes | None = None,
    ) -> None:
        self._activation = activation
        self._disclosure = disclosure
        self._dispatcher = dispatcher
        self._pseudonym_key = pseudonym_key

    async def dispatch(
        self,
        *,
        destination_scope: str,
        correlation_id: str,
        records: Sequence[CostProjectionRecord],
        now: datetime,
    ) -> bool:
        """Return true only after the package notification reaches the router."""

        activation = await self._activation.read_cost_activation(PACKAGE_ID)
        if activation is None or not activation.available or not activation.enabled:
            return False
        policy = await self._disclosure.read_notification_disclosure(
            destination_scope,
            now=now,
        )
        if policy is None or policy.amount_precision is CostAmountPrecision.NONE:
            return False
        try:
            items = disclose_cost_records(
                records,
                policy,
                pseudonym_key=self._pseudonym_key,
            )
        except ValueError:
            return False
        body = json.dumps(
            {"items": items},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        await self._dispatcher.dispatch(
            NotificationMessage(
                category=CATEGORY,
                trust_tier=TrustTier.A4_DIGEST,
                correlation_id=correlation_id,
                title="Cost Governance update",
                body_markdown=body,
                severity=Severity.INFO,
                metadata={
                    "producer": PRODUCER,
                    "activation_revision": str(activation.revision),
                    "disclosure": policy.amount_precision.value,
                },
            )
        )
        return True


__all__ = [
    "CATEGORY",
    "PRODUCER",
    "CostGovernanceNotificationProducer",
    "CostNotificationDisclosureReader",
]

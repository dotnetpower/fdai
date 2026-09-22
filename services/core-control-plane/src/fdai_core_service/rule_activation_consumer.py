"""Consume content-free Rule activation notices and apply verified receipts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.rule_activation import RuleActivationCoordinator
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.rule_activation_transport import (
    RULE_ACTIVATION_CONSUMER_GROUP,
    RULE_ACTIVATION_REQUEST_TOPIC,
    RuleActivationRequestNotice,
)


class RuleActivationReceiptReader(Protocol):
    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class RuleActivationConsumer:
    receipts: RuleActivationReceiptReader
    coordinator: RuleActivationCoordinator
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        async with subscription(
            bus,
            RULE_ACTIVATION_REQUEST_TOPIC,
            RULE_ACTIVATION_CONSUMER_GROUP,
        ) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                try:
                    notice = RuleActivationRequestNotice.model_validate(envelope.payload)
                    if envelope.key != notice.request_id:
                        raise ValueError("Rule activation partition identity mismatch")
                    record = await self.receipts.read_state(notice.proposal_ref)
                    if record is None or not _matches_notice(record, notice):
                        raise ValueError("Rule activation source receipt does not match notice")
                    if notice.operation == "rule.activation-request":
                        await self.coordinator.accept_request(
                            record,
                            source_ref=notice.proposal_ref,
                            at=self.clock(),
                        )
                    else:
                        await self.coordinator.approve(
                            record,
                            source_ref=notice.proposal_ref,
                            at=self.clock(),
                        )
                except ValueError:
                    await bus.dead_letter(
                        RULE_ACTIVATION_REQUEST_TOPIC,
                        "invalid-rule-activation-notice",
                        {"reason": "invalid_rule_activation_notice", "execution_authority": False},
                        "invalid_rule_activation_notice",
                    )


def _matches_notice(
    record: Mapping[str, Any],
    notice: RuleActivationRequestNotice,
) -> bool:
    accepted_at = record.get("accepted_at")
    try:
        recorded_at = datetime.fromisoformat(accepted_at) if isinstance(accepted_at, str) else None
    except ValueError:
        return False
    return (
        record.get("proposal_id") == notice.proposal_id
        and record.get("request_digest") == notice.proposal_digest
        and record.get("operation") == notice.operation
        and recorded_at is not None
        and recorded_at.astimezone(UTC) == notice.accepted_at.astimezone(UTC)
    )


__all__ = ["RuleActivationConsumer", "RuleActivationReceiptReader"]

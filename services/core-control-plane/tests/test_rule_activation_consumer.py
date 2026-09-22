from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fdai.core.rule_activation import RuleActivationCoordinator
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai_core_service.rule_activation_consumer import RuleActivationConsumer
from fdai_service_contracts.rule_activation_transport import (
    RULE_ACTIVATION_REQUEST_TOPIC,
    RuleActivationRequestNotice,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class ReceiptReader:
    def __init__(self, record: Mapping[str, object] | None) -> None:
        self.record = record

    async def read_state(self, key: str) -> Mapping[str, object] | None:
        del key
        return self.record


class Coordinator:
    def __init__(self) -> None:
        self.accepted: list[tuple[Mapping[str, object], str]] = []
        self.approved: list[tuple[Mapping[str, object], str]] = []

    async def accept_request(
        self,
        record: Mapping[str, object],
        *,
        source_ref: str,
        at: datetime,
    ) -> object:
        assert at == NOW
        self.accepted.append((record, source_ref))
        return object()

    async def approve(
        self,
        record: Mapping[str, object],
        *,
        source_ref: str,
        at: datetime,
    ) -> object:
        assert at == NOW
        self.approved.append((record, source_ref))
        return object()


class Bus:
    def __init__(self, envelope: EventEnvelope) -> None:
        self.envelope = envelope
        self.dead_letters: list[tuple[object, ...]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> PublishReceipt:
        del payload
        return PublishReceipt(topic, 0, 0)

    async def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        del group_id
        if self.envelope.topic == topic:
            yield self.envelope

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
        reason: str,
    ) -> None:
        self.dead_letters.append((topic, key, payload, reason))


def _notice(
    operation: Literal[
        "rule.activation-request",
        "rule.activation-approve",
    ] = "rule.activation-request",
) -> RuleActivationRequestNotice:
    return RuleActivationRequestNotice(
        proposal_ref="operator-proposal:workflow:" + "b" * 64,
        proposal_id="operator-" + "a" * 32,
        request_id="operator-" + "a" * 32,
        proposal_digest="a" * 64,
        operation=operation,
        accepted_at=NOW,
    )


async def test_consumer_reads_exact_receipt_before_accepting_request() -> None:
    notice = _notice()
    record = {
        "proposal_id": notice.proposal_id,
        "request_digest": notice.proposal_digest,
        "operation": notice.operation,
        "accepted_at": NOW.isoformat(),
    }
    coordinator = Coordinator()
    bus = Bus(
        EventEnvelope(
            RULE_ACTIVATION_REQUEST_TOPIC,
            notice.request_id,
            notice.model_dump(mode="json"),
            0,
        )
    )
    consumer = RuleActivationConsumer(
        receipts=ReceiptReader(record),
        coordinator=cast(RuleActivationCoordinator, coordinator),
        clock=lambda: NOW,
    )

    await consumer.run(bus=cast(Any, bus), stop=asyncio.Event())

    assert coordinator.accepted == [(record, notice.proposal_ref)]
    assert coordinator.approved == []
    assert bus.dead_letters == []


async def test_consumer_redacts_a_mismatched_receipt() -> None:
    notice = _notice()
    coordinator = Coordinator()
    bus = Bus(
        EventEnvelope(
            RULE_ACTIVATION_REQUEST_TOPIC,
            notice.request_id,
            notice.model_dump(mode="json"),
            0,
        )
    )
    consumer = RuleActivationConsumer(
        receipts=ReceiptReader({"proposal_id": "operator-" + "c" * 32}),
        coordinator=cast(RuleActivationCoordinator, coordinator),
        clock=lambda: NOW,
    )

    await consumer.run(bus=cast(Any, bus), stop=asyncio.Event())

    assert coordinator.accepted == []
    assert bus.dead_letters == [
        (
            RULE_ACTIVATION_REQUEST_TOPIC,
            "invalid-rule-activation-notice",
            {"reason": "invalid_rule_activation_notice", "execution_authority": False},
            "invalid_rule_activation_notice",
        )
    ]

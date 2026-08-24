"""Operational-readiness ownership-transfer ingest integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fdai.composition.readiness import (
    OperationalReadinessEventHandler,
    OperationalReadinessService,
)
from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.event_ingest import EventIngest
from fdai.runtime.bootstrap_task_hooks import default_runtime_task_hooks
from fdai.runtime.consumers import _consume_operational_readiness
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.projection import Finding
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _EventValidator:
    def validate(self, payload: Mapping[str, Any]) -> None:
        Event.model_validate(payload)


class _Posture:
    async def findings_for_scope(self, scope: str) -> Sequence[Finding]:
        assert scope == "rg-example"
        return ()


class _ReportPublisher:
    def __init__(self) -> None:
        self.reports: list[Mapping[str, Any]] = []

    async def publish_readiness_report(self, report: Mapping[str, Any]) -> None:
        self.reports.append(report)


class _ProposalPublisher:
    def __init__(self) -> None:
        self.proposals: list[Mapping[str, Any]] = []

    async def publish_remediation_proposal(self, proposal: Mapping[str, Any]) -> None:
        self.proposals.append(proposal)


class _RedeliveringBus:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload
        self.dead_letters: list[str] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        raise AssertionError("the ORR consumer MUST NOT publish directly")

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        assert topic == "fdai.events"
        assert group_id == "fdai-operational-readiness"

        async def stream() -> AsyncIterator[EventEnvelope]:
            for offset in range(2):
                yield EventEnvelope(
                    topic=topic,
                    key="rg-example",
                    payload=self._payload,
                    offset=offset,
                )

        return stream()

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        self.dead_letters.append(reason)


def _ownership_transfer_event() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000000",
        "idempotency_key": "ownership-transfer:corr-orr-runtime-1",
        "correlation_id": "corr-orr-runtime-1",
        "source": "handoff_gateway",
        "event_type": "ownership_transfer",
        "resource_ref": "rg-example",
        "payload": {
            "scope": "rg-example",
            "submitter": "submitter@example.com",
            "target_environment": "prod",
        },
        "detected_at": "2026-08-24T00:00:00+00:00",
        "ingested_at": "2026-08-24T00:00:01+00:00",
        "mode": "shadow",
    }


async def test_redelivery_publishes_one_report_and_no_remediation() -> None:
    store = InMemoryStateStore()
    report_publisher = _ReportPublisher()
    proposal_publisher = _ProposalPublisher()
    service = OperationalReadinessService(
        posture=_Posture(),
        preflight=PreflightAnalyzer((), mode=Mode.SHADOW, clock=lambda: "ignored"),
        publisher=report_publisher,
        state_store=store,
        mode=Mode.SHADOW,
        clock=lambda: "2026-08-24T00:00:02+00:00",
        remediation_publisher=proposal_publisher,
    )
    handler = OperationalReadinessEventHandler(
        event_ingest=EventIngest(validator=_EventValidator()),
        service=service,
    )
    bus = _RedeliveringBus(_ownership_transfer_event())

    await _consume_operational_readiness(
        bus=bus,
        topic="fdai.events",
        group_id="fdai-operational-readiness",
        handler=handler,
        stop=asyncio.Event(),
    )

    assert len(report_publisher.reports) == 1
    assert proposal_publisher.proposals == []
    assert bus.dead_letters == []
    audit = store.audit_entries[0]["entry"]
    assert audit["workflow_id"] == "operational-readiness-handoff"
    assert audit["accountable_agent"] == "Forseti"


async def test_invalid_ownership_transfer_is_dead_lettered_without_review() -> None:
    store = InMemoryStateStore()
    report_publisher = _ReportPublisher()
    service = OperationalReadinessService(
        posture=_Posture(),
        preflight=PreflightAnalyzer((), mode=Mode.SHADOW, clock=lambda: "ignored"),
        publisher=report_publisher,
        state_store=store,
        mode=Mode.SHADOW,
    )
    handler = OperationalReadinessEventHandler(
        event_ingest=EventIngest(validator=_EventValidator()),
        service=service,
    )
    payload = _ownership_transfer_event()
    payload["payload"] = {
        "scope": "rg-example",
        "submitter": 42,
        "target_environment": "prod",
    }
    bus = _RedeliveringBus(payload)

    await _consume_operational_readiness(
        bus=bus,
        topic="fdai.events",
        group_id="fdai-operational-readiness",
        handler=handler,
        stop=asyncio.Event(),
    )

    assert report_publisher.reports == []
    assert bus.dead_letters == ["operational_readiness_consume_error:ValueError"]


def test_default_runtime_hooks_register_operational_readiness_consumer() -> None:
    hooks = default_runtime_task_hooks()

    assert hooks.consume_operational_readiness is _consume_operational_readiness

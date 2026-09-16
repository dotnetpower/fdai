"""Focused Core consumption checks for confirmed Incident creation requests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.incident_creation_consumer import consume_incident_creations
from fdai_service_contracts.incident_creation import (
    INCIDENT_CREATION_CONSUMER_GROUP,
    INCIDENT_CREATION_REQUEST_TOPIC,
    IncidentCreationArguments,
    build_incident_creation_request,
)
from fdai_service_contracts.operator import OperatorRole

NOW = datetime(2026, 9, 16, 2, 5, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
SOURCE_REQUEST_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request"))
SOURCE_PROJECTION_ID = str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection"))


class _Stream:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> EventEnvelope:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _Bus:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self.stream = _Stream(events)
        self.dead_letters: list[tuple[str, str]] = []

    def subscribe(self, topic: str, group_id: str) -> _Stream:
        assert topic == INCIDENT_CREATION_REQUEST_TOPIC
        assert group_id == INCIDENT_CREATION_CONSUMER_GROUP
        return self.stream

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: object,
        reason: str,
    ) -> None:
        del topic, payload
        self.dead_letters.append((key, reason))


def _request_payload(
    *,
    source_request_id: str = SOURCE_REQUEST_ID,
    source_projection_id: str = SOURCE_PROJECTION_ID,
    idempotency_key: str = "draft-one",
) -> dict[str, object]:
    return build_incident_creation_request(
        request_id=source_request_id,
        source_request_id=source_request_id,
        source_projection_id=source_projection_id,
        principal_id="operator-one",
        principal_roles=(OperatorRole.CONTRIBUTOR,),
        idempotency_key=idempotency_key,
        session_id="session-one",
        arguments=IncidentCreationArguments(severity="sev2", target="service-api"),
        source_input_digest=DIGEST,
        draft_digest="sha256:" + "b" * 64,
        draft_expires_at=datetime(2026, 9, 16, 2, 10, tzinfo=UTC),
        confirmed_at=NOW,
    ).model_dump(mode="json")


async def test_consumer_opens_one_incident_for_redelivered_request() -> None:
    payload = _request_payload()
    target_ref = str(payload["target_ref"])
    envelope = EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, payload, 1)
    bus = _Bus([envelope, envelope])
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        stop=asyncio.Event(),
    )

    incidents = tuple(registry.snapshot().values())
    assert len(incidents) == 1
    assert incidents[0].severity.value == "sev2"
    assert bus.dead_letters == []
    assert bus.stream.closed is True
    opens = [
        item for item in state_store.audit_entries if item["entry"].get("kind") == "incident.open"
    ]
    assert len(opens) == 1


async def test_consumer_dead_letters_a_partition_mismatch() -> None:
    payload = _request_payload()
    bus = _Bus(
        [
            EventEnvelope(
                INCIDENT_CREATION_REQUEST_TOPIC,
                "sha256:" + "0" * 64,
                payload,
                1,
            )
        ]
    )
    registry = IncidentRegistry(state_store=InMemoryStateStore())

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        stop=asyncio.Event(),
    )

    assert registry.snapshot() == {}
    assert bus.dead_letters == [("sha256:" + "0" * 64, "incident_creation_request_rejected")]


async def test_distinct_confirmed_requests_for_one_target_open_distinct_incidents() -> None:
    first = _request_payload()
    second = _request_payload(
        source_request_id=str(uuid5(NAMESPACE_URL, "fdai.test.incident-creation.request.second")),
        source_projection_id=str(
            uuid5(NAMESPACE_URL, "fdai.test.incident-creation.projection.second")
        ),
        idempotency_key="draft-two",
    )
    target_ref = str(first["target_ref"])
    bus = _Bus(
        [
            EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, first, 1),
            EventEnvelope(INCIDENT_CREATION_REQUEST_TOPIC, target_ref, second, 2),
        ]
    )
    registry = IncidentRegistry(state_store=InMemoryStateStore())

    await consume_incident_creations(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_CREATION_REQUEST_TOPIC,
        group_id=INCIDENT_CREATION_CONSUMER_GROUP,
        workflow=IncidentLifecycleWorkflow(registry=registry),
        stop=asyncio.Event(),
    )

    assert len(registry.snapshot()) == 2
    assert bus.dead_letters == []

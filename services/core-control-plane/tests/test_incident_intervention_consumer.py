"""Focused Core consumption checks for versioned Incident interventions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.shared.providers.event_bus import EventEnvelope
from fdai_core_service.incident_intervention_consumer import consume_incident_interventions
from fdai_service_contracts.incident_intervention import (
    INCIDENT_INTERVENTION_REQUEST_TOPIC,
    IncidentInterventionAction,
    IncidentInterventionProposalBody,
    IncidentInterventionRequest,
    build_incident_intervention_request,
    incident_target_ref,
)
from fdai_service_contracts.operator import OperatorRole

INCIDENT_ID = "00000000-0000-0000-0000-000000000123"
NOW = datetime(2026, 8, 24, tzinfo=UTC)


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
        assert topic == INCIDENT_INTERVENTION_REQUEST_TOPIC
        assert group_id == "core-incident-intervention-v1"
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


class _Service:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.requests: list[IncidentInterventionRequest] = []

    async def apply(self, request: IncidentInterventionRequest) -> None:
        if self.failure is not None:
            raise self.failure
        self.requests.append(request)


def _payload() -> dict[str, object]:
    body = IncidentInterventionProposalBody(
        action=IncidentInterventionAction.GUIDANCE,
        incident_id=INCIDENT_ID,
        correlation_id="correlation-one",
        expected_state="triaging",
        comment="Preserve this operator context.",
    )
    return build_incident_intervention_request(
        request_id="request-one",
        principal_id="principal-one",
        principal_roles=(OperatorRole.CONTRIBUTOR,),
        idempotency_key="idempotency-one",
        target_ref=incident_target_ref("service:checkout-api"),
        body=body,
        requested_at=NOW,
    ).model_dump(mode="json")


async def _consume(bus: _Bus, service: _Service) -> None:
    await consume_incident_interventions(
        bus=bus,  # type: ignore[arg-type]
        topic=INCIDENT_INTERVENTION_REQUEST_TOPIC,
        group_id="core-incident-intervention-v1",
        service=service,  # type: ignore[arg-type]
        stop=asyncio.Event(),
    )


async def test_consumer_validates_and_applies_redelivery() -> None:
    envelope = EventEnvelope(INCIDENT_INTERVENTION_REQUEST_TOPIC, INCIDENT_ID, _payload(), 1)
    bus = _Bus([envelope, envelope])
    service = _Service()

    await _consume(bus, service)

    assert len(service.requests) == 2
    assert service.requests[0].execution_authority is False
    assert bus.dead_letters == []
    assert bus.stream.closed is True


async def test_consumer_dead_letters_invalid_partition_without_apply() -> None:
    bus = _Bus([EventEnvelope(INCIDENT_INTERVENTION_REQUEST_TOPIC, "different", _payload(), 1)])
    service = _Service()

    await _consume(bus, service)

    assert service.requests == []
    assert bus.dead_letters == [("different", "incident_intervention_request_rejected")]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (KeyError("missing incident"), "incident_intervention_not_found"),
        (PermissionError("role floor"), "incident_intervention_unauthorized"),
        (ValueError("stale request"), "incident_intervention_state_rejected"),
    ],
)
async def test_consumer_dead_letters_domain_rejection_with_stable_reason(
    failure: Exception,
    reason: str,
) -> None:
    bus = _Bus([EventEnvelope(INCIDENT_INTERVENTION_REQUEST_TOPIC, INCIDENT_ID, _payload(), 1)])

    await _consume(bus, _Service(failure))

    assert bus.dead_letters == [(INCIDENT_ID, reason)]


async def test_consumer_propagates_transient_store_failure() -> None:
    bus = _Bus([EventEnvelope(INCIDENT_INTERVENTION_REQUEST_TOPIC, INCIDENT_ID, _payload(), 1)])

    with pytest.raises(RuntimeError, match="store unavailable"):
        await _consume(bus, _Service(RuntimeError("store unavailable")))

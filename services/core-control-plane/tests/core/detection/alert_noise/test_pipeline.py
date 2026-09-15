"""Signed ingress to owned agent pub/sub and retained results, without network or execution."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fdai.agents import Forseti, Heimdall, Huginn, InMemoryBus, load_pantheon
from fdai.delivery.alert_noise_handler import AlertNoiseAgentHandler
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    AlertNoiseResult,
    SignedAlertCommand,
    sign_alert_record,
)

_KEY = b"synthetic-unit-transport-key-not-a-credential"


@pytest.mark.parametrize(
    ("agent_type", "binder", "topic", "payload"),
    [
        (Forseti, "bind_alert_noise_planner", "object.drift", {"kind": "alert_noise"}),
        (Forseti, "bind_alert_effect_planner", "object.drift", {"kind": "alert_noise_effect"}),
        (
            Heimdall,
            "bind_alert_noise_observer",
            "object.event",
            {"event_type": "alert_noise.assess"},
        ),
        (
            Heimdall,
            "bind_alert_effect_observer",
            "object.action-run",
            {"kind": "alert_noise_publication"},
        ),
    ],
)
async def test_alert_callback_binding_is_single_owner_and_instance_local(
    agent_type: type[Forseti] | type[Heimdall],
    binder: str,
    topic: str,
    payload: dict[str, Any],
) -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    bound, unbound = agent_type(bus=bus), agent_type(bus=bus)
    calls: list[dict[str, Any]] = []

    async def callback(value: dict[str, Any]) -> dict[str, Any]:
        calls.append(value)
        return {"kind": "alert_noise"}

    getattr(bound, binder)(callback)
    with pytest.raises(RuntimeError, match="already bound"):
        getattr(bound, binder)(callback)
    with pytest.raises(RuntimeError, match="unavailable"):
        await unbound.on_typed_message(topic, payload)
    await bound.on_typed_message(topic, payload)
    assert calls == [payload]


@pytest.mark.parametrize("event_type", ["alert_noise.assess", "alert_noise.propose"])
async def test_raw_alert_event_waits_for_observation_before_forseti_planning(
    event_type: str,
) -> None:
    judge = Forseti()
    calls: list[dict[str, Any]] = []

    async def planner(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {}

    judge.bind_alert_noise_planner(planner)
    await judge.on_typed_message("object.event", {"event_type": event_type})
    assert calls == []
    await judge.on_typed_message("object.drift", {"kind": "alert_noise"})
    assert calls == [{"kind": "alert_noise"}]


@pytest.mark.parametrize("agent_type", [Forseti, Heimdall])
async def test_alert_callback_does_not_claim_unrelated_messages(
    agent_type: type[Forseti] | type[Heimdall],
) -> None:
    agent = agent_type()
    assert not await agent._alert_noise_message("object.drift", {"kind": "unrelated"})
    assert not await agent._alert_noise_message("object.rule", {})


def raw_command(now: datetime, *, request_ref: str = "request:example") -> dict[str, Any]:
    command = AlertNoiseCommand(
        operation="alert_noise.assess",
        request_ref=request_ref,
        requester_ref="principal:example",
        scope_ref="scope:example",
        requested_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    signed = SignedAlertCommand(command=command, signature=sign_alert_record(command, _KEY))
    return {
        "schema_version": "1.0.0",
        "event_id": str(uuid5(NAMESPACE_URL, request_ref)),
        "source": "operator-alert-noise",
        "event_type": command.operation,
        "idempotency_key": request_ref,
        "correlation_id": request_ref,
        "resource_ref": command.scope_ref,
        "mode": "shadow",
        "incident_correlation": "none",
        "payload": {"alert_noise": signed.model_dump(mode="json")},
    }


class Source:
    def __init__(self, evidence: AlertEvidence) -> None:
        self.evidence, self.calls = evidence, 0

    async def collect(self, *, now: datetime) -> AlertEvidence:
        self.calls += 1
        return self.evidence


def setup(
    evidence: AlertEvidence, now: datetime
) -> tuple[Huginn, InMemoryBus, AlertNoiseAgentHandler, Source]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store, source = InMemoryStateStore(), Source(evidence)
    handler = AlertNoiseAgentHandler(
        store=store,
        sources={"scope:example": source},
        principals={"principal:example": frozenset({"scope:example"})},
        policy=NoisePolicy(),
        transport_key=_KEY,
        clock=lambda: now,
    )
    huginn, observer, judge = Huginn(bus=bus), Heimdall(bus=bus), Forseti(bus=bus)
    huginn.bind_alert_noise_verifier(handler.verify_ingress)
    observer.bind_alert_noise_observer(handler.observe)
    judge.bind_alert_noise_planner(handler.plan)
    bus.subscribe("object.event", "Heimdall", observer.on_typed_message)
    bus.subscribe("object.drift", "Forseti", judge.on_typed_message)
    return huginn, bus, handler, source


async def test_signed_request_reaches_owned_agents_once(
    evidence: AlertEvidence, now: datetime
) -> None:
    # Non-synthetic wire flags exercise mechanics only;
    # this explicit fixture is never a runtime fallback.
    data = evidence.model_dump()
    data["stamp"]["synthetic"] = False
    observed = AlertEvidence.model_validate(data)
    huginn, bus, handler, source = setup(observed, now)
    raw = raw_command(now)
    assert await huginn.ingest(raw) is not None
    assert await huginn.ingest(raw) is None
    assert source.calls == 1
    stored = await handler.store.read_state("alert-noise:result:request:example")
    assert stored is not None
    result = AlertNoiseResult.model_validate(stored["result"])
    assert result.status == "assessment_ready" and result.plan is None
    assert result.assessment is not None and result.assessment.evidence_digest == digest_record(
        observed
    )
    assert result.execution_authority is False
    assert [row.topic for row in bus.published] == ["object.event", "object.drift"]
    assert not bus.dead_letters


@pytest.mark.parametrize(
    "field", ["signature", "resource_ref", "correlation_id", "event_id", "mode"]
)
async def test_invalid_ingress_cannot_poison_valid_dedup(
    evidence: AlertEvidence,
    now: datetime,
    field: str,
) -> None:
    huginn, _, handler, source = setup(evidence, now)
    valid = raw_command(now)
    forged = deepcopy(valid)
    if field == "signature":
        forged["payload"]["alert_noise"]["signature"] = "sha256:" + "0" * 64
    else:
        forged[field] = "forged"
    with pytest.raises(ValueError):
        await huginn.ingest(forged)
    assert source.calls == 0 and huginn.health()["dedup_size"] == 0
    assert await huginn.ingest(valid) is not None
    stored = await handler.store.read_state("alert-noise:result:request:example")
    assert stored is not None and stored["result"]["reason"] == "synthetic_live_evidence"


async def test_unbound_ingress_is_not_accepted(now: datetime) -> None:
    with pytest.raises(ValueError, match="unavailable"):
        await Huginn().ingest(raw_command(now))


async def test_denied_scope_never_calls_source(evidence: AlertEvidence, now: datetime) -> None:
    huginn, _, handler, source = setup(evidence, now)
    handler.principals.clear()
    await huginn.ingest(raw_command(now))
    assert source.calls == 0
    result = await handler.store.read_state("alert-noise:result:request:example")
    assert (
        result is not None
        and result["result"]["status"] == "held"
        and result["result"]["reason"] == "scope_denied"
    )

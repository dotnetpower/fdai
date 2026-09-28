"""Advisory arbitration holds observed signals on its correlation from automatic execution (#1541).

The default observation-first profile settles a prediction-fed cost and capacity arbitration as
ActionType-free evidence. It must never be less conservative than the governed path: every
settled outcome still marks the correlation unresolved, so a later observed signal on it is held
from automatic execution (Thor refuses it, and drops it only without a durable store) instead
of being judged ``auto``. The cases run the real
Forseti, Odin, and Thor code over the fixed pantheon registry with a recording executor and a
pinned clock.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.advisory_verdicts import GOVERNED_EXECUTION_UNSELECTED_REASON
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.thor import Thor

from tests.product_selection import governed_execution_selection

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
_OUTCOMES = ("escalated", "arbitration_owner_unavailable", "resolved")
_OBSERVED = {
    "producer_principal": "Huginn",
    "correlation_id": "corr-gate",
    "idempotency_key": "corr-gate:observed",
    "resource_id": "vm-gate",
    "event_type": "restart_needed",
}
_GATED = ("ops.restart-service", "hil", "arbitration_unresolved", "enforce_hil")


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, run: dict[str, Any]) -> bool:
        self.calls.append(dict(run))
        return True


def _forseti(bus: InMemoryBus, *, selected: bool, outcome: str) -> Forseti:
    """Wire Forseti and, unless the arbiter is unavailable, an Odin forced to ``outcome``."""

    unavailable = outcome == "arbitration_owner_unavailable"
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(selected),
        agent_availability=(lambda: {"Odin"}) if unavailable else None,
    )
    if not unavailable:
        # A margin band wider than any score gap forces escalation; zero resolves the tie.
        odin = Odin(bus=bus, hil_margin=10.0 if outcome == "escalated" else 0.0)
        bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    return forseti


async def _capacity_conflict(forseti: Forseti) -> None:
    for topic, recommendation, impact in (
        ("object.cost-anomaly", "scale_down", 0.5),
        ("object.capacity-forecast", "scale_up", 0.62),
    ):
        await forseti.on_typed_message(
            topic,
            {
                "correlation_id": "corr-gate",
                "resource_id": "vm-gate",
                "recommendation": recommendation,
                "impact": impact,
            },
        )


def _summary(verdict: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(verdict["action_type"]),
        str(verdict["risk_verdict"]),
        str(verdict["reason"]),
        str(verdict["resolved_autonomy_ceiling"]),
    )


@pytest.mark.parametrize("outcome", _OUTCOMES)
async def test_event_on_an_advisory_arbitration_correlation_never_judges_auto(
    outcome: str,
) -> None:
    baseline = await Forseti().judge(dict(_OBSERVED))
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    forseti = _forseti(bus, selected=False, outcome=outcome)
    executor = _RecordingExecutor()
    thor = Thor(bus=bus, executor=executor, clock=lambda: _NOW)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)

    await _capacity_conflict(forseti)
    (advisory,) = (message.payload for message in bus.messages_on("object.verdict"))
    await forseti.on_typed_message("object.event", dict(_OBSERVED))
    gated = bus.messages_on("object.verdict")[-1].payload

    assert baseline is not None and baseline["risk_verdict"] == "auto"
    assert advisory["reason"] == GOVERNED_EXECUTION_UNSELECTED_REASON
    assert advisory["arbitration"]["outcome"] == outcome
    assert _summary(gated) == _GATED
    # Thor's existing rule drops an arbitration-reason Verdict that carries no DecisionCase.
    assert thor.action_runs["corr-gate"].state.value == "deny_dropped"
    assert executor.calls == []


@pytest.mark.parametrize("outcome", _OUTCOMES)
async def test_default_gate_is_as_conservative_as_the_selected_profile(outcome: str) -> None:
    gated: dict[bool, tuple[str, str, str, str]] = {}
    for selected in (False, True):
        bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
        forseti = _forseti(bus, selected=selected, outcome=outcome)
        await _capacity_conflict(forseti)
        await forseti.on_typed_message("object.event", dict(_OBSERVED))
        gated[selected] = _summary(bus.messages_on("object.verdict")[-1].payload)

    assert gated[False] == gated[True] == _GATED


class _FailOnceBus(InMemoryBus):
    """Reject the first advisory Verdict publication, as a transient broker failure would."""

    def __init__(self) -> None:
        super().__init__(registry=load_pantheon(), isolate_handlers=False)
        self.rejected = 0

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        if (
            topic == "object.verdict"
            and payload.get("reason") == GOVERNED_EXECUTION_UNSELECTED_REASON
            and not self.rejected
        ):
            self.rejected += 1
            raise ConnectionError("transient broker failure")
        await super().publish(principal, topic, payload)


async def test_failed_advisory_publication_stays_retryable() -> None:
    bus = _FailOnceBus()
    # No arbiter is subscribed, so only the redelivered decisions below settle the conflict.
    forseti = Forseti(bus=bus, governed_execution_selected=governed_execution_selection(False))
    await _capacity_conflict(forseti)
    decision = {
        "producer_principal": "Odin",
        "correlation_id": "corr-gate",
        "winning_domain": "capacity",
        "losing_domains": ["cost"],
        "margin": 0.2,
        "escalate_hil": True,
    }

    with pytest.raises(ConnectionError):
        await forseti.on_typed_message("object.arbitration-decision", dict(decision))
    await forseti.on_typed_message("object.arbitration-decision", dict(decision))
    await forseti.on_typed_message("object.arbitration-decision", dict(decision))

    advisories = [
        message.payload
        for message in bus.messages_on("object.verdict")
        if message.payload["reason"] == GOVERNED_EXECUTION_UNSELECTED_REASON
    ]
    assert bus.rejected == 1
    assert len(advisories) == 1
    assert advisories[0]["arbitration"]["outcome"] == "escalated"
    assert forseti.behavior_snapshot()["learned_output_advisory:duplicate"] == 1
    gated = await forseti.judge(dict(_OBSERVED))
    assert gated is not None and _summary(gated) == _GATED


class _HeldVerdictBus(InMemoryBus):
    """Hold the first advisory Verdict publication open so a second settlement can race it."""

    def __init__(self) -> None:
        super().__init__(registry=load_pantheon(), isolate_handlers=False)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        advisory = payload.get("reason") == GOVERNED_EXECUTION_UNSELECTED_REASON
        if topic == "object.verdict" and advisory and not self.entered.is_set():
            self.entered.set()
            await self.release.wait()
        await super().publish(principal, topic, payload)


async def test_concurrent_decision_and_owner_closure_publish_one_advisory_verdict() -> None:
    bus = _HeldVerdictBus()
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(False),
        agent_availability=lambda: {"Odin"},
    )
    cost, capacity = (
        {
            "correlation_id": "corr-gate",
            "resource_id": "vm-gate",
            "recommendation": recommendation,
            "impact": impact,
        }
        for recommendation, impact in (("scale_down", 0.5), ("scale_up", 0.62))
    )
    await forseti.on_typed_message("object.cost-anomaly", cost)
    # The fail-closed owner closure starts publishing and is held inside the publication.
    closure = asyncio.create_task(forseti.on_typed_message("object.capacity-forecast", capacity))
    await bus.entered.wait()
    late = {"producer_principal": "Odin", "correlation_id": "corr-gate", "winning_domain": "cost"}
    decision = asyncio.create_task(forseti.on_typed_message("object.arbitration-decision", late))
    for _ in range(5):
        await asyncio.sleep(0)
    bus.release.set()
    await asyncio.gather(closure, decision)

    advisories = [
        message.payload
        for message in bus.messages_on("object.verdict")
        if message.payload["reason"] == GOVERNED_EXECUTION_UNSELECTED_REASON
    ]
    assert [item["arbitration"]["outcome"] for item in advisories] == [
        "arbitration_owner_unavailable"
    ]
    assert forseti.behavior_snapshot()["learned_output_advisory:duplicate"] == 1

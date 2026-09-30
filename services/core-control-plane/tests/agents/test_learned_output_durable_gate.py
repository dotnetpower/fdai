"""Advisory arbitration correlations stay held across a Core restart and gate eviction (#1541).

The governed path records an ActionRun for an arbitration Verdict, and Thor's durable correlation
claim for that record refuses every later Verdict on the correlation, including after a restart.
The default observation-first profile records no ActionRun, so Thor holds the correlation with a
terminal non-action claim in the same store. A fresh Forseti and Thor over that store therefore
refuse a later observed signal exactly as the governed path does, with zero executor calls, while
the advisory Verdict itself still creates no ActionRun. Clocks are pinned and every store is in
memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.thor import Thor
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_decision_case_e2e import AT, _context_store, _source_freshness_payload
from tests.product_selection import governed_execution_selection

_NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
_RESERVATION = "advisory_correlation_reservation"


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"ops.restart-service": False, "ops.scale-out": False},
        rollback_by_id={
            "ops.restart-service": "state_forward_only",
            "ops.scale-out": "state_forward_only",
        },
    )


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, run: dict[str, Any]) -> bool:
        self.calls.append(dict(run))
        return True


async def _forseti(
    bus: InMemoryBus,
    *,
    selected: bool,
    with_decision_case: bool,
) -> Forseti:
    context = (
        {"operational_context": OperationalContextMaterializer(store=await _context_store())}
        if with_decision_case
        else {}
    )
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(selected),
        action_semantics=_semantics(),
        **context,
    )
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    return forseti


def _thor(bus: InMemoryBus, store: StateStoreActionRunStore) -> tuple[Thor, _RecordingExecutor]:
    executor = _RecordingExecutor()
    thor = Thor(bus=bus, executor=executor, clock=lambda: _NOW, state_store=store)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    return thor, executor


async def _capacity_conflict(forseti: Forseti, correlation_id: str) -> None:
    for topic, recommendation, impact in (
        ("object.cost-anomaly", "scale_down", 0.2),
        ("object.capacity-forecast", "scale_up", 1.0),
    ):
        await forseti.on_typed_message(
            topic,
            {
                "correlation_id": correlation_id,
                "resource_id": "resource-example",
                "recommendation": recommendation,
                "impact": impact,
                "observed_at": AT,
                "source_freshness": _source_freshness_payload(),
                "action_arguments": {
                    "target_resource_ref": "resource-example",
                    "reason": "Reviewed scaling candidate.",
                },
            },
        )


def _observed(correlation_id: str) -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:observed",
        "resource_id": "resource-example",
        "event_type": "restart_needed",
    }


@pytest.mark.parametrize("with_decision_case", [False, True])
@pytest.mark.parametrize("outcome", ["escalated", "resolved"])
@pytest.mark.parametrize("selected", [False, True])
async def test_restart_keeps_the_arbitrated_correlation_refused(
    selected: bool,
    outcome: str,
    with_decision_case: bool,
) -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    before = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    forseti = await _forseti(before, selected=selected, with_decision_case=with_decision_case)
    odin = Odin(bus=before, hil_margin=10.0 if outcome == "escalated" else 0.0)
    before.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    thor, executor = _thor(before, store)

    await _capacity_conflict(forseti, "corr-x")

    row = await state.read_state("thor:run|corr-x")
    assert row is not None
    if not selected:
        # The advisory Verdict leaves only Thor's terminal non-action claim behind.
        assert row["kind"] == _RESERVATION and row["active"] == "false"
        assert thor.action_runs == {}
        assert before.messages_on("object.action-run") == []
    else:
        assert "kind" not in row
    # Restart: fresh agents over the same durable ActionRun store.
    after = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    restarted = await _forseti(after, selected=selected, with_decision_case=with_decision_case)
    fresh_thor, fresh_executor = _thor(after, store)
    await fresh_thor.rehydrate()

    if selected and with_decision_case:
        await restarted.on_typed_message("object.event", _observed("corr-x"))
    else:
        with pytest.raises(ValueError, match="ActionRun correlation"):
            await restarted.on_typed_message("object.event", _observed("corr-x"))

    assert executor.calls == [] and fresh_executor.calls == []
    assert fresh_thor.behavior_snapshot().get("dispatch:auto") is None
    if selected and with_decision_case:
        assert fresh_thor.behavior_snapshot()["dispatch:correlation_reuse_rejected"] == 1


async def test_gate_eviction_keeps_the_arbitrated_correlation_refused() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(state)
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    forseti = await _forseti(bus, selected=False, with_decision_case=False)
    # One newer arbitration evicts the in-memory gate, as 10,000 would at the production bound.
    forseti._unresolved_arbitrations = BoundedLruDict(1)  # noqa: SLF001
    odin = Odin(bus=bus, hil_margin=10.0)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    thor, executor = _thor(bus, store)

    await _capacity_conflict(forseti, "corr-evicted")
    await _capacity_conflict(forseti, "corr-newer")
    assert forseti._unresolved_arbitrations.get("corr-evicted") is None  # noqa: SLF001

    with pytest.raises(ValueError, match="cannot bind a different identity"):
        await forseti.on_typed_message("object.event", _observed("corr-evicted"))

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "auto"
    assert executor.calls == []
    assert thor.action_runs == {}
    assert thor.behavior_snapshot()["advisory_correlation:reserved"] == 2


async def test_forecast_advisory_leaves_no_durable_claim() -> None:
    state = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    forseti = await _forseti(bus, selected=False, with_decision_case=False)
    thor, executor = _thor(bus, StateStoreActionRunStore(state))

    await forseti.on_typed_message(
        "object.forecast",
        {
            "producer_principal": "Heimdall",
            "correlation_id": "forecast:1541",
            "idempotency_key": "forecast:1541",
            "resource_id": "resource-example",
            "event_type": "restart_needed",
            "mode": "enforce",
        },
    )

    (verdict,) = (message.payload for message in bus.messages_on("object.verdict"))
    assert verdict["action_type"] == "" and "arbitration" not in verdict
    assert await state.read_state("thor:run|forecast:1541") is None
    assert thor.action_runs == {} and executor.calls == []
    assert thor.behavior_snapshot().get("advisory_correlation:reserved") is None

from __future__ import annotations

from typing import Any, cast

import pytest
from fdai.agents import (
    InMemoryBus,
    MuninnInvestigationStrategyCohortSink,
    Norns,
    instantiate_pantheon,
    load_pantheon,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_learning.test_investigation_strategy import _comparison


class _FailOnceContextIndexBus(InMemoryBus):
    def __init__(self) -> None:
        super().__init__(registry=load_pantheon())
        self.failed = False

    async def publish(self, principal: str, topic: str, payload: dict[str, object]) -> None:
        if topic == "object.context-index" and not self.failed:
            self.failed = True
            raise RuntimeError("broker unavailable")
        await super().publish(principal, topic, payload)


async def test_muninn_sink_drives_one_norns_to_mimir_candidate_after_replay() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    state_store = InMemoryStateStore()
    sink = MuninnInvestigationStrategyCohortSink(
        state_store=state_store,
        bus=bus,
    )
    improvement = _comparison(improvement=True)
    control = _comparison(improvement=False)

    await sink.record(improvement)
    assert bus.messages_on("object.context-index") == []
    await sink.record(control)
    context_messages = bus.messages_on("object.context-index")
    assert len(context_messages) == 1

    norns = Norns()
    norns.bind_bus(bus)
    await norns.on_typed_message(
        "object.context-index",
        dict(context_messages[0].payload),
    )
    candidate_messages = bus.messages_on("object.rule-candidate")
    assert len(candidate_messages) == 1

    mimir = cast(Any, instantiate_pantheon()["Mimir"])
    await mimir.on_typed_message(
        "object.rule-candidate",
        dict(candidate_messages[0].payload),
    )
    assert len(mimir.pending_candidates()) == 1

    await sink.record(improvement)
    await sink.record(control)
    assert len(bus.messages_on("object.context-index")) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 1


async def test_muninn_recover_pending_investigation_strategy_cohort_publication() -> None:
    store = InMemoryStateStore()
    first = MuninnInvestigationStrategyCohortSink(
        state_store=store,
        bus=_FailOnceContextIndexBus(),
    )

    await first.record(_comparison(improvement=True))
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await first.record(_comparison(improvement=False))

    bus = InMemoryBus(registry=load_pantheon())
    restarted = MuninnInvestigationStrategyCohortSink(state_store=store, bus=bus)

    assert await restarted.recover_pending_publications() == 1
    messages = bus.messages_on("object.context-index")
    assert len(messages) == 1
    original_key = messages[0].payload["idempotency_key"]
    assert await restarted.recover_pending_publications() == 0
    assert len(bus.messages_on("object.context-index")) == 1
    assert messages[0].payload["idempotency_key"] == original_key


async def test_muninn_record_redrives_pending_cohort_before_new_comparison() -> None:
    store = InMemoryStateStore()
    bus = _FailOnceContextIndexBus()
    sink = MuninnInvestigationStrategyCohortSink(state_store=store, bus=bus)

    await sink.record(_comparison(improvement=True))
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await sink.record(_comparison(improvement=False))
    rows, _total = await store.read_state_page(
        "operational-learning:investigation-strategy:",
        limit=1,
        field="state",
        value="pending",
    )
    original_key = rows[0]["payload"]["idempotency_key"]

    await sink.record(
        _comparison(
            improvement=True,
            active_digest="sha256:" + "4" * 64,
            challenger_digest="sha256:" + "5" * 64,
        )
    )

    messages = bus.messages_on("object.context-index")
    assert len(messages) == 1
    assert messages[0].payload["idempotency_key"] == original_key
    assert await sink.recover_pending_publications() == 0


async def test_mimir_accepts_rolling_strategy_cohorts_and_deduplicates_replay() -> None:
    mimir = cast(Any, instantiate_pantheon()["Mimir"])
    payloads = []
    for index in range(4):
        candidate_digest = f"sha256:{index + 1:064x}"
        payload = {
            "producer_principal": "Norns",
            "correlation_id": f"norns:cohort-{index}",
            "idempotency_key": f"rule-candidate:cohort-{index}",
            "source_signal": "investigation_strategy_comparison_cohort",
            "evidence": {
                "candidate_digest": candidate_digest,
                "sample_size": 2,
            },
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "suggested_change": "review_investigation_strategy",
            "target_rule_id": "investigation.selector.aaaaaaaaaaaaaaaa",
            "enforcement_mode": "shadow",
            "auto_promote": False,
        }
        payloads.append(payload)
        await mimir.on_typed_message("object.rule-candidate", payload)

    await mimir.on_typed_message("object.rule-candidate", payloads[-1])

    assert len(mimir.pending_candidates()) == 4
    assert mimir.quarantined_candidates() == ()

from __future__ import annotations

from typing import Any, cast

from fdai.agents import (
    InMemoryBus,
    MuninnInvestigationStrategyCohortSink,
    Norns,
    instantiate_pantheon,
    load_pantheon,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_learning.test_investigation_strategy import _comparison


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

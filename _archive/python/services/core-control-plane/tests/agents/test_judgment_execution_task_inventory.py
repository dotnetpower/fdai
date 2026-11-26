"""Round 9 task-inventory regressions for Thor, Forseti, and Vidar."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_judgment import JudgmentTable
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.vidar import Vidar
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"test.auto": False},
        rollback_by_id={"test.auto": "state_forward_only"},
    )


def _verdict() -> dict[str, object]:
    return {
        "producer_principal": "Forseti",
        "correlation_id": "task-inventory-corr",
        "idempotency_key": "task-inventory-verdict",
        "action_type": "test.auto",
        "resource_id": "resource-a",
        "risk_verdict": "auto",
        "rollback_contract": "state_forward_only",
        "quorum_required": 1,
        "initiator_principal": "operator@example.com",
    }


def test_thor_shadow_terminal_closure_is_audited_by_saga_publication() -> None:
    bus = _bus()
    saga = Saga()
    saga.bind_bus(bus)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    thor = Thor(bus=bus, shadow_by_default=True, action_semantics_catalog=_semantics())

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    action_runs = [
        message.payload
        for message in bus.messages_on("object.action-run")
        if message.payload["correlation_id"] == run.correlation_id
        and message.payload["state"] == "succeeded"
    ]
    assert action_runs
    assert action_runs[-1]["idempotency_key"]
    assert action_runs[-1]["correlation_id"]
    audit_entries = bus.messages_on("object.audit-entry")
    assert audit_entries[-1].payload["audited_topic"] == "object.action-run"
    assert audit_entries[-1].payload["result"] == "shadow_success"
    assert audit_entries[-1].payload["correlation_id"] == run.correlation_id


def test_thor_maintenance_warms_retry_strategy_capability_cache() -> None:
    thor = Thor(action_semantics_catalog=_semantics())

    asyncio.run(thor.maintenance_tick())

    cache = thor.health()["retry_strategy_cache"]
    assert cache["action_semantics_bound"] is True
    assert cache["saga_available"] is True
    assert cache["vidar_available"] is True
    assert cache["recorded_at"]
    assert thor.behavior_snapshot()["retry_strategy_cache:warmed"] == 1


def test_forseti_maintenance_reports_verdict_coherence_and_novelty_drift() -> None:
    table = JudgmentTable(
        rule_match={"event.a": "test.auto"},
        risk_verdict={"test.auto": "auto"},
        source="test",
    )
    forseti = Forseti(judgment_table=table, action_semantics=_semantics())

    for index in range(10):
        asyncio.run(
            forseti.judge(
                {
                    "event_type": "event.a",
                    "resource_id": f"resource-{index}",
                    "correlation_id": f"corr-{index}",
                    "judgment_tier": "T2" if index == 0 else "T0",
                }
            )
        )
    forseti._judgment_table = JudgmentTable(  # noqa: SLF001 - regression pins retained replay.
        rule_match={"event.a": "test.auto"},
        risk_verdict={"test.auto": "hil"},
        source="test-updated",
    )

    asyncio.run(forseti.maintenance_tick())

    health = forseti.health()
    assert health["verdict_coherence_self_test"]["sample_size"] == 10
    assert health["verdict_coherence_self_test"]["disagreements"] == 10
    assert health["novelty_drift_signal"]["tier_mix"] == {"T0": 9, "T1": 0, "T2": 1}
    assert health["novelty_drift_signal"]["t2_ratio"] == 0.1
    assert forseti.behavior_snapshot()["verdict_coherence:disagreement"] == 10


def test_vidar_maintenance_reports_rollback_path_and_dr_readiness() -> None:
    async def _executor(_payload: dict[str, object]) -> str:
        return "rollback:test"

    vidar = Vidar(
        executors={"snapshot_restore": _executor},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={
            "ops.restore-snapshot": "snapshot_restore",
            "ops.point-in-time-restore": "pitr",
        },
    )

    asyncio.run(vidar.maintenance_tick())

    health = vidar.health()
    assert health["rollback_path_validation"]["evidence_state"] == "measured"
    assert health["dr_readiness_score"]["coverage_ratio"] == 0.5
    assert health["dr_readiness_score"]["validated_action_types"] == 1
    assert health["dr_readiness_score"]["missing_action_types"] == 1
    assert (
        health["rollback_path_validation"]["paths"]["ops.point-in-time-restore"]["executor_bound"]
        is False
    )
    assert vidar.behavior_snapshot()["rollback_path_validation:failed"] == 1

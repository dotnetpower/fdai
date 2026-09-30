"""Focused hardening regressions for Odin, Var, Vidar, and Bragi."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fdai.agents._framework.bragi_proposal import build_action_proposal
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


def _draft_judgment() -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "operator_action",
            "secondary_intents": [],
            "targets": [
                {
                    "kind": "action_type",
                    "value": "ops.restart-service",
                    "canonical_value": "ops.restart-service",
                    "source_start": 0,
                    "source_end": 3,
                },
                {
                    "kind": "resource",
                    "value": "service-a",
                    "canonical_value": "service-a",
                    "source_start": 4,
                    "source_end": 13,
                },
            ],
            "requested_facets": [],
            "confidence": 0.99,
            "ambiguous": False,
            "alternatives": [],
            "unresolved_terms": [],
            "clarification": None,
            "action_posture": "draft_only",
            "action_subject": "ActionType",
            "execution_authority": False,
        }
    )


def test_odin_refuses_empty_correlation_without_publishing_decision() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    odin = Odin(bus=bus)

    decision = asyncio.run(odin.arbitrate({"domains_in_conflict": ["cost", "capacity"]}))

    assert decision.correlation_id == ""
    assert bus.messages_on("object.arbitration-decision") == []
    assert odin.behavior_snapshot()["arbitration:invalid_correlation"] == 1


def test_forseti_closes_unanswered_arbitration_when_odin_unavailable() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(bus=bus, agent_availability=lambda: ("Odin",))

    verdict = asyncio.run(
        forseti._close_unowned_arbitration(  # noqa: SLF001 - degradation seam
            "corr-odin-unavailable",
            domains=["cost", "capacity"],
        )
    )

    assert verdict is not None
    assert verdict["producer_principal"] == "Forseti"
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "arbitration_owner_unavailable"
    assert verdict["action_type"] == ""
    published = bus.messages_on("object.verdict")[0].payload
    assert {key: published[key] for key in verdict} == verdict


def test_var_durable_decision_audit_uses_injected_clock() -> None:
    store = InMemoryStateStore()
    var = Var(state_store=store, clock=lambda: NOW)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "corr-var-clock",
                "action_type": "ops.restart-service",
                "state": "hil_pending",
            },
        )
    )

    asyncio.run(
        var.decide(
            "corr-var-clock",
            approver="reviewer@example.com",
            decision="approve",
        )
    )

    recorded_at = [
        entry["entry"]["recorded_at"]
        for entry in store.audit_entries
        if entry["entry"].get("action_kind") == "approval.decision_recorded"
    ]
    assert recorded_at == [NOW.isoformat()]


def test_bragi_action_proposal_key_is_deterministic() -> None:
    judgment = _draft_judgment()

    first, first_status = build_action_proposal(
        session_id="session-1",
        user_id="operator@example.com",
        question="restart service-a",
        judgment=judgment,
        action_type_names=("ops.restart-service",),
        initiator_role="Contributor",
        pipeline_available=True,
    )
    second, second_status = build_action_proposal(
        session_id="session-1",
        user_id="operator@example.com",
        question="restart service-a",
        judgment=judgment,
        action_type_names=("ops.restart-service",),
        initiator_role="Contributor",
        pipeline_available=True,
    )

    assert first is not None and second is not None
    assert first["correlation_id"] == second["correlation_id"]
    assert first["idempotency_key"] == first["correlation_id"]
    assert first_status["correlation_id"] == second_status["correlation_id"]


async def test_bragi_serializes_first_conversation_and_turn_indexes() -> None:
    from fdai.agents.bragi import Bragi

    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi()
    bragi.bind_bus(bus)

    first, second = await asyncio.gather(
        bragi.ask(session_id="shared", user_id="operator", question="unknown one"),
        bragi.ask(session_id="shared", user_id="operator", question="unknown two"),
    )

    assert sorted((first.turn_index, second.turn_index)) == [0, 1]
    assert len(bus.messages_on("object.conversation")) == 1
    assert [message.payload["turn_index"] for message in bus.messages_on("object.turn")] == [0, 1]


async def test_bragi_counts_progress_without_correlation() -> None:
    from fdai.agents.bragi import Bragi

    bragi = Bragi()

    await bragi.on_typed_message("object.verdict", {"risk_verdict": "hil"})

    assert bragi.behavior_snapshot()["progress:missing_correlation"] == 1


def test_vidar_refuses_process_local_rollback_without_explicit_opt_in() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    calls: list[str] = []

    async def rollback(command: dict[str, object]) -> str:
        calls.append(str(command["correlation_id"]))
        return "rollback:should-not-run"

    vidar = Vidar(bus=bus, executors={"state_forward_only": rollback})

    record = asyncio.run(
        vidar.rollback(
            {
                "producer_principal": "Thor",
                "correlation_id": "corr-vidar-local",
                "action_type": "ops.restart-service",
                "resource_id": "vm-1",
                "state": "failed",
            }
        )
    )

    assert record is not None
    assert record.state == "failed"
    assert calls == []
    assert vidar.behavior_snapshot()["rollback:durability_unavailable"] == 1
    assert vidar.health()["rollback_durability"] == "process_local"
    assert vidar.health()["process_local_rollback_allowed"] is False
    assert bus.messages_on("object.rollback")[0].payload["state"] == "failed"

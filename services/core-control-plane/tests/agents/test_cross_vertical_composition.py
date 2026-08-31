"""Story #349 cross-vertical arbitration and fail-closed replay coverage."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.agents._framework.adapters import InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.vertical_precedence import InitialVerticalPrecedence
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.vidar import Vidar
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.shared.contracts.models import Autonomy

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIO_PATH = (
    REPO_ROOT
    / "services/core-control-plane/tests/scenarios/phase3"
    / "v2026.08-cross-vertical-shadow.json"
)


class _FrozenContext:
    async def materialize(self, **kwargs: Any) -> OperationalContextSnapshot:
        cutoff = kwargs["cutoff"]
        return OperationalContextSnapshot(
            snapshot_id="phase3-context-v2026.08",
            target_resource_id=kwargs["target_resource_id"],
            cutoff=cutoff,
            recorded_at=cutoff,
            catalog_versions=(),
            service_ids=("service.example",),
            workload_ids=("workload.example",),
            objective_ids=("objective.availability", "objective.cost"),
            service_objective_ids=("objective.availability",),
            recovery_objective_ids=(),
            cost_objective_ids=("objective.cost",),
            constraint_ids=(),
            ownership_ids=(),
            dependency_ids=(),
            source_freshness=tuple(kwargs.get("source_freshness") or ()),
            evidence_links=(),
            evidence_paths=(),
            temporal_exclusions=(),
            stale_sources=(),
            conflicts=(),
            autonomy_ceiling=Autonomy.ENFORCE_AUTO,
            graph_source_generation="phase3-frozen-generation",
            clock_identity="phase3-frozen-clock",
        )


def _scenario() -> dict[str, Any]:
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def _candidate_payload(scenario: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "cross_vertical_candidate",
        "correlation_id": scenario["correlation_id"],
        "idempotency_key": candidate["idempotency_key"],
        "resource_id": scenario["resource_id"],
        "observed_at": scenario["observed_at"],
        "action_type": candidate["action_type"],
        "effects": candidate["effects"],
        "evidence_refs": candidate["evidence_refs"],
    }


def _wire(
    *,
    timeout: float = 1.0,
    shadow: bool = True,
    executor: Any = None,
    execution_audit_recorder: Any = None,
    require_execution_audit: bool = False,
) -> tuple[InMemoryBus, InMemoryAuditChain, Thor]:
    bus = InMemoryBus(load_pantheon())
    audit = InMemoryAuditChain()
    forseti = Forseti(
        bus=bus,
        operational_context=_FrozenContext(),  # type: ignore[arg-type]
        cross_vertical_timeout_seconds=timeout,
    )
    odin = Odin(bus=bus, vertical_precedence=InitialVerticalPrecedence())
    saga = Saga(audit_chain=audit)
    thor = Thor(
        bus=bus,
        shadow_by_default=shadow,
        executor=executor,
        execution_audit_recorder=execution_audit_recorder,
        require_execution_audit=require_execution_audit,
    )

    for topic in ("object.resilience-score", "object.drift", "object.cost-anomaly"):
        bus.subscribe(topic, "Forseti", forseti.on_typed_message)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Saga", saga.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    return bus, audit, thor


async def _publish_candidates(
    bus: InMemoryBus,
    scenario: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    await asyncio.gather(
        *(
            bus.publish(
                candidate["principal"],
                candidate["topic"],
                _candidate_payload(scenario, candidate),
            )
            for candidate in candidates
        )
    )


async def test_frozen_shadow_scenario_composes_all_verticals_once() -> None:
    scenario = _scenario()
    mutations: list[str] = []

    async def _executor(_context: dict[str, Any]) -> bool:
        mutations.append("mutated")
        return True

    bus, audit, thor = _wire(executor=_executor)
    candidates = list(reversed(scenario["candidates"]))
    candidates.append(scenario["candidates"][2])

    await _publish_candidates(bus, scenario, candidates)

    assert {
        message.principal
        for message in bus.published
        if message.payload.get("kind") == "cross_vertical_candidate"
    } == {"Loki", "Heimdall", "Njord"}
    assert len(bus.messages_on("object.arbitration-request")) == 1
    (decision,) = bus.messages_on("object.arbitration-decision")
    assert decision.payload["winning_domain"] == scenario["expected"]["winning_domain"]
    assert decision.payload["dispositions"] == scenario["expected"]["dispositions"]
    (verdict,) = bus.messages_on("object.verdict")
    assert verdict.payload["initiator_principal"] == scenario["expected"]["initiator_principal"]

    action_runs = bus.messages_on("object.action-run")
    assert action_runs
    assert {message.principal for message in action_runs} == {
        scenario["expected"]["executor_principal"]
    }
    assert action_runs[-1].payload["outcome"] == scenario["expected"]["terminal_outcome"]
    assert thor.action_runs[scenario["correlation_id"]].shadow_mode is True
    assert mutations == []
    assert len(mutations) == scenario["expected"]["managed_resource_mutations"]

    audited_topics = [
        entry.topic for entry in audit.entries_for_correlation(scenario["correlation_id"])
    ]
    assert "object.arbitration-decision" in audited_topics
    assert "object.verdict" in audited_topics
    assert "object.action-run" in audited_topics
    audit.verify()
    assert bus.dead_letters == []


async def test_incomplete_candidate_set_times_out_to_audited_hil() -> None:
    scenario = _scenario()
    bus, audit, _ = _wire(timeout=0.01)

    await _publish_candidates(bus, scenario, scenario["candidates"][:2])
    await asyncio.sleep(0.03)

    assert bus.messages_on("object.arbitration-request") == []
    (verdict,) = bus.messages_on("object.verdict")
    assert verdict.payload["risk_verdict"] == "hil"
    assert verdict.payload["reason"] == "cross_vertical_candidate_timeout"
    assert verdict.payload["action_type"] == ""
    assert [
        entry.topic for entry in audit.entries_for_correlation(scenario["correlation_id"])
    ].count("object.verdict") == 1


async def test_conflicting_duplicate_candidate_closes_hil_without_arbitration() -> None:
    scenario = _scenario()
    bus, audit, _ = _wire()
    candidate = scenario["candidates"][0]
    first = _candidate_payload(scenario, candidate)
    conflict = {**first, "action_type": "ops.failover-primary"}

    await bus.publish(candidate["principal"], candidate["topic"], first)
    await bus.publish(candidate["principal"], candidate["topic"], conflict)

    assert bus.messages_on("object.arbitration-request") == []
    (verdict,) = bus.messages_on("object.verdict")
    assert verdict.payload["risk_verdict"] == "hil"
    assert verdict.payload["reason"] == "cross_vertical_candidate_replay_conflict"
    audit.verify()


async def test_candidate_ingress_rejects_unbounded_identity_before_accumulation() -> None:
    scenario = _scenario()
    bus, _audit, _thor = _wire()
    candidate = scenario["candidates"][0]
    payload = {
        **_candidate_payload(scenario, candidate),
        "correlation_id": "x" * 257,
    }

    await bus.publish(candidate["principal"], candidate["topic"], payload)

    assert bus.messages_on("object.arbitration-request") == []
    assert bus.messages_on("object.verdict") == []
    assert len(bus.dead_letters) == 1


async def test_candidate_ingress_rejects_whitespace_only_identity() -> None:
    scenario = _scenario()
    bus, _audit, _thor = _wire()
    candidate = scenario["candidates"][0]
    payload = {
        **_candidate_payload(scenario, candidate),
        "resource_id": "   ",
    }

    await bus.publish(candidate["principal"], candidate["topic"], payload)

    assert bus.messages_on("object.arbitration-request") == []
    assert bus.messages_on("object.verdict") == []
    assert len(bus.dead_letters) == 1


async def test_concurrent_sets_for_one_resource_close_both_to_hil() -> None:
    scenario = _scenario()
    bus, audit, _ = _wire()
    candidate = scenario["candidates"][0]
    first = _candidate_payload(scenario, candidate)
    second = {
        **first,
        "correlation_id": "phase3-cross-vertical-0002",
        "idempotency_key": "phase3-candidate-resilience-0002",
    }

    await asyncio.gather(
        bus.publish(candidate["principal"], candidate["topic"], first),
        bus.publish(candidate["principal"], candidate["topic"], second),
    )

    verdicts = bus.messages_on("object.verdict")
    assert {message.payload["correlation_id"] for message in verdicts} == {
        scenario["correlation_id"],
        second["correlation_id"],
    }
    assert {message.payload["reason"] for message in verdicts} == {"cross_vertical_concurrent_set"}
    audit.verify()


async def test_partial_arbitration_subscriber_failure_stays_shadow_and_replayable() -> None:
    scenario = _scenario()
    mutations: list[str] = []

    async def _executor(_context: dict[str, Any]) -> bool:
        mutations.append("mutated")
        return True

    async def _failed_subscriber(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("subscriber unavailable")

    bus, audit, _ = _wire(executor=_executor)
    bus.subscribers["object.arbitration-decision"].insert(
        0,
        ("partial-subscriber", _failed_subscriber),
    )

    await _publish_candidates(bus, scenario, scenario["candidates"])

    assert mutations == []
    assert bus.messages_on("object.action-run")[-1].payload["outcome"] == "shadow_success"
    assert bus.messages_on("object.rollback") == []
    assert len(bus.dead_letters) == 1
    assert bus.dead_letters[0].topic == "object.arbitration-decision"
    audit.verify()


async def test_failed_thor_execution_rolls_back_once_through_vidar() -> None:
    executor_calls: list[str] = []

    async def _executor(context: dict[str, Any]) -> bool:
        executor_calls.append(context["run"].correlation_id)
        return False

    async def _rollback(_payload: dict[str, Any]) -> str:
        return "rollback:phase3-0001"

    bus = InMemoryBus(load_pantheon())
    thor = Thor(bus=bus, executor=_executor)
    vidar = Vidar(bus=bus, executors={"state_forward_only": _rollback})
    saga = Saga(audit_chain=InMemoryAuditChain())
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)
    bus.subscribe("object.rollback", "Saga", saga.on_typed_message)

    await bus.publish(
        "Forseti",
        "object.verdict",
        {
            "correlation_id": "phase3-rollback-0001",
            "idempotency_key": "phase3-rollback-0001",
            "resource_id": "resource://example/shared-workload-1",
            "action_type": "ops.restart-service",
            "risk_verdict": "auto",
            "reason": "rule_match",
            "resolved_autonomy_ceiling": "enforce_auto",
            "rollback_contract": "state_forward_only",
        },
    )

    assert executor_calls == ["phase3-rollback-0001"]
    assert len(bus.messages_on("object.rollback")) == 1
    assert thor.action_runs["phase3-rollback-0001"].state.value == "rolled_back"
    assert {message.principal for message in bus.messages_on("object.action-run")} == {"Thor"}


def test_frozen_scenario_uses_one_release_and_exact_vertical_identities() -> None:
    scenario = _scenario()

    assert scenario["release"] == "v2026.08"
    assert [candidate["domain"] for candidate in scenario["candidates"]] == [
        "resilience",
        "change_safety",
        "cost",
    ]
    assert len({candidate["principal"] for candidate in scenario["candidates"]}) == 3
    assert scenario["expected"]["managed_resource_mutations"] == 0
    datetime.fromisoformat(scenario["observed_at"].replace("Z", "+00:00")).astimezone(UTC)

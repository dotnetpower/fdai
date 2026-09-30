"""Round 10 action lifecycle regressions across Thor, Vidar, and Heimdall."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_safeguards import (
    DRY_RUN_DECLARED_OBLIGATION,
    DRY_RUN_UPSTREAM_RECEIPT,
    execution_safeguards,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents._framework.thor_dispatch_validation import (
    dry_run_obligation_only,
    missing_wire_safeguards,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.vidar import Vidar
from fdai.core.executor.safeguards import SEVEN_SAFEGUARDS
from fdai.core.workflow.recovery_effect_ingress import RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.local.event_bus import LocalEventBus

_RAW_TOPIC = "fdai.events.r10j"
_EFFECT_REF = "sha256:" + "b" * 64
_CLOSURE_REF = "sha256:" + "c" * 64


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"test.auto": False},
        rollback_by_id={"test.auto": "state_forward_only"},
    )


def _safeguards(idempotency_key: str) -> dict[str, object]:
    return {
        "stop_condition": "stop when postcondition is false",
        "tested_rollback_contract": "state_forward_only:test-receipt",
        "blast_radius_limit": {"scope": "resource", "max_targets": 1},
        "dry_run_receipt": "sha256:" + "1" * 64,
        "logical_target_lock": "lock:resource:test",
        "stable_idempotency_key": idempotency_key,
        "two_phase_audit_intent": "audit-intent:test",
    }


def _verdict(**overrides: Any) -> dict[str, Any]:
    idempotency_key = str(overrides.get("idempotency_key") or "r10-key")
    verdict: dict[str, Any] = {
        "producer_principal": "Forseti",
        "correlation_id": "r10-correlation",
        "idempotency_key": idempotency_key,
        "action_idempotency_key": idempotency_key,
        "action_id": "action-r10",
        "action_type": "test.auto",
        "risk_verdict": "auto",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
        "resource_id": "resource-r10",
        "params": {"replicas": 2},
        "safeguards": _safeguards(idempotency_key),
    }
    verdict.update(overrides)
    return verdict


async def _run_until(
    runtime: PantheonRuntime,
    predicate: Callable[[], bool],
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _published_payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def test_non_shadow_verdict_without_safeguards_denies_before_executor_io() -> None:
    executor_called = False

    async def _executor(_context: dict[str, Any]) -> bool:
        nonlocal executor_called
        executor_called = True
        return True

    thor = Thor(bus=_bus(), executor=_executor, action_semantics_catalog=_semantics())

    run = asyncio.run(
        thor.dispatch_verdict(_verdict(correlation_id="missing-safeguards-object", safeguards=None))
    )

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "missing_safeguards"
    assert executor_called is False
    assert thor.behavior_snapshot()["dispatch:missing_safeguards"] == 1


def test_wire_verdict_without_safeguards_denies_regardless_of_key_shape() -> None:
    executor_called = False

    async def _executor(_context: dict[str, Any]) -> bool:
        nonlocal executor_called
        executor_called = True
        return True

    thor = Thor(bus=_bus(), executor=_executor, action_semantics_catalog=_semantics())
    verdict = _verdict(
        correlation_id="unprefixed-key",
        idempotency_key="legacy-shaped-key",
        safeguards=None,
    )
    verdict.pop("safeguards")
    verdict.pop("action_idempotency_key")

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "missing_safeguards"
    assert executor_called is False


def test_kinetic_proposal_does_not_substitute_for_wire_safeguards() -> None:
    verdict = _verdict(safeguards=None)
    verdict.pop("safeguards")
    verdict.pop("action_idempotency_key")
    verdict.pop("idempotency_key")
    verdict["kinetic_proposal"] = {"proposal_id": "kinetic-action-proposal:" + "0" * 64}

    assert missing_wire_safeguards(verdict) == SEVEN_SAFEGUARDS


def test_forseti_marks_dry_run_provenance_instead_of_claiming_a_receipt() -> None:
    declared = execution_safeguards(
        action_type="test.auto",
        action_idempotency_key="r10-key",
        resource_id="resource-r10",
        rollback_contract="state_forward_only",
        event={},
    )
    upstream = execution_safeguards(
        action_type="test.auto",
        action_idempotency_key="r10-key",
        resource_id="resource-r10",
        rollback_contract="state_forward_only",
        event={"what_if_receipt": "what-if:resource-r10:1"},
    )

    assert declared["dry_run_evidence"] == DRY_RUN_DECLARED_OBLIGATION
    assert str(declared["dry_run_receipt"]).startswith("forseti-dry-run-obligation:")
    assert dry_run_obligation_only({"safeguards": declared}) is True
    assert upstream["dry_run_evidence"] == DRY_RUN_UPSTREAM_RECEIPT
    assert upstream["dry_run_receipt"] == "what-if:resource-r10:1"
    assert dry_run_obligation_only({"safeguards": upstream}) is False


def test_thor_counts_non_shadow_dispatch_backed_only_by_dry_run_obligation() -> None:
    async def _executor(_context: dict[str, Any]) -> bool:
        return True

    thor = Thor(bus=_bus(), executor=_executor, action_semantics_catalog=_semantics())
    declared = execution_safeguards(
        action_type="test.auto",
        action_idempotency_key="obligation-key",
        resource_id="resource-r10",
        rollback_contract="state_forward_only",
        event={},
    )

    asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="obligation-only",
                idempotency_key="obligation-key",
                safeguards=declared,
            )
        )
    )
    upstream = asyncio.run(
        thor.dispatch_verdict(
            _verdict(correlation_id="upstream-receipt", resource_id="resource-r10-upstream")
        )
    )

    assert upstream.state is not ActionRunState.DENY_DROPPED
    assert thor.behavior_snapshot()["dispatch:dry_run_obligation_only"] == 1


def test_actionless_hil_verdict_closes_without_unapprovable_ticket() -> None:
    thor = Thor(bus=_bus(), action_semantics_catalog=_semantics())

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="no-rule-triage",
                action_type="",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY.value,
            )
        )
    )

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "triage_action_unavailable"
    assert ActionRunState.HIL_PENDING not in run.history


def test_hil_verdict_with_unavailable_var_is_visible_terminal_hold() -> None:
    thor = Thor(bus=_bus(), action_semantics_catalog=_semantics())
    thor.bind_agent_availability(lambda: frozenset({"Var"}))

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="var-down",
                idempotency_key="var-down-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
            )
        )
    )

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "hil_held_approver_unavailable"
    assert thor.behavior_snapshot()["dispatch:hil_approver_unavailable"] == 1


def test_executor_success_waits_for_independent_effect_observation() -> None:
    bus = _bus()
    thor = Thor(
        bus=bus,
        executor=lambda _context: asyncio.sleep(0, result=True),
        action_semantics_catalog=_semantics(),
    )

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(correlation_id="effect-pending", idempotency_key="effect-pending-key")
        )
    )

    assert run.state is ActionRunState.EFFECT_PENDING
    assert run.outcome == "command_accepted_verification_pending"
    assert bus.messages_on("object.action-run")[-1].payload["effect_verification_status"] == (
        "pending"
    )

    asyncio.run(
        thor.on_typed_message(
            "object.recovery-effect-observation",
            {
                "schema_version": "1.0.0",
                "event_type": "action.execution.effect_verified.v1",
                "producer_principal": "Heimdall",
                "correlation_id": run.correlation_id,
                "idempotency_key": "effect-observation",
                "resource_id": run.resource_id,
                "action_id": run.action_id,
                "action_type": run.action_type,
                "action_idempotency_key": run.idempotency_key,
                "params": run.params,
                "effect_verification_ref": _EFFECT_REF,
                "execution_closure_ref": _CLOSURE_REF,
                "observed_at": "2026-10-01T00:00:00+00:00",
            },
        )
    )

    assert run.state is ActionRunState.SUCCEEDED
    assert run.outcome == "independent_effect_verified"
    assert bus.messages_on("object.action-run")[-1].payload["operational_success"] is True


def test_effect_verification_deadline_expires_to_visible_unverified_failure() -> None:
    now = [datetime(2026, 9, 30, tzinfo=UTC)]
    bus = _bus()
    thor = Thor(
        bus=bus,
        executor=lambda _context: asyncio.sleep(0, result=True),
        action_semantics_catalog=_semantics(),
        clock=lambda: now[0],
        effect_verification_timeout_seconds=1,
    )

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(correlation_id="effect-expiry", idempotency_key="effect-expiry-key")
        )
    )
    now[0] = now[0] + timedelta(seconds=2)

    expired = asyncio.run(thor.expire_pending_approvals())

    assert expired == 1
    assert run.state is ActionRunState.FAILED
    assert run.outcome == "effect_verification_expired"
    assert thor.behavior_snapshot()["effect_verification:expired"] == 1
    assert bus.messages_on("object.action-run")[-1].payload["effect_verification_status"] == (
        "not_applicable"
    )


def test_runtime_relays_recovery_effect_identity_from_huginn_to_thor() -> None:
    provider = LocalEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)
    thor.action_runs["corr-runtime-effect"] = ActionRun(
        correlation_id="corr-runtime-effect",
        action_type="test.auto",
        resource_id="resource-runtime-effect",
        state=ActionRunState.EFFECT_PENDING,
        verdict="auto",
        action_id="action-runtime-effect",
        idempotency_key="runtime-effect-key",
        params={"replicas": 3},
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )

    async def _drive() -> None:
        await provider.publish(
            _RAW_TOPIC,
            "raw-effect-key",
            {
                "id": "raw-effect",
                "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
                "correlation_id": "corr-runtime-effect",
                "idempotency_key": "same-raw-key",
                "resource_id": "resource-runtime-effect",
                "occurred_at": "2026-09-30T00:00:00+00:00",
                "attributes": {
                    "action_id": "action-runtime-effect",
                    "action_type": "test.auto",
                    "action_idempotency_key": "runtime-effect-key",
                    "params": {"replicas": 3},
                    "effect_verification_ref": _EFFECT_REF,
                    "execution_closure_ref": _CLOSURE_REF,
                    "observed_at": "2026-09-30T00:00:00+00:00",
                    "evidence_digest": "sha256:" + "d" * 64,
                    "success": True,
                },
            },
        )
        await _run_until(
            runtime,
            lambda: thor.action_runs["corr-runtime-effect"].state is ActionRunState.SUCCEEDED,
        )

    asyncio.run(_drive())

    observations = _published_payloads(provider, "object.recovery-effect-observation")
    assert observations[-1]["action_id"] == "action-runtime-effect"
    assert observations[-1]["action_type"] == "test.auto"
    assert observations[-1]["action_idempotency_key"] == "runtime-effect-key"
    assert observations[-1]["params"] == {"replicas": 3}
    assert thor.action_runs["corr-runtime-effect"].effect_verification_ref == _EFFECT_REF


def test_recovery_effect_observations_use_distinct_idempotency_for_distinct_evidence() -> None:
    provider = LocalEventBus()
    runtime = PantheonRuntime.build(provider=provider, raw_event_topic=_RAW_TOPIC)

    async def _drive() -> None:
        for suffix in ("1", "2"):
            await runtime.bridge.publish(
                "Huginn",
                "object.event",
                {
                    "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
                    "correlation_id": "corr-distinct-effect",
                    "idempotency_key": "same-raw-key",
                    "resource_id": "resource-distinct-effect",
                    "attributes": {
                        "action_id": "action-distinct-effect",
                        "action_type": "test.auto",
                        "action_idempotency_key": "distinct-effect-key",
                        "params": {"suffix": suffix},
                        "effect_verification_ref": "sha256:" + suffix * 64,
                        "execution_closure_ref": _CLOSURE_REF,
                        "observed_at": f"2026-09-30T00:00:0{suffix}+00:00",
                        "evidence_digest": "sha256:" + suffix * 64,
                        "success": True,
                    },
                },
            )
        await _run_until(
            runtime,
            lambda: len(_published_payloads(provider, "object.recovery-effect-observation")) == 2,
        )

    asyncio.run(_drive())

    keys = {
        payload["idempotency_key"]
        for payload in _published_payloads(provider, "object.recovery-effect-observation")
    }
    assert len(keys) == 2


def _action_run_payload(state: ActionRunState = ActionRunState.EXECUTION_UNKNOWN) -> dict[str, Any]:
    run = ActionRun(
        correlation_id="rollback-ambiguous",
        action_type="test.auto",
        resource_id="resource-rollback",
        state=state,
        verdict="auto",
        action_id="action-rollback",
        idempotency_key="rollback-key",
        params={"replicas": 2},
        rollback_contract="state_forward_only",
    )
    return {
        **run.publication_identity_payload(),
        "producer_principal": "Thor",
        "idempotency_key": f"{run.correlation_id}:{run.state.value}",
        "state": run.state.value,
        "shadow_mode": run.shadow_mode,
        "resolved_autonomy_ceiling": run.resolved_autonomy_ceiling.value,
        "outcome": run.outcome,
        "action_run_identity": run.action_run_identity(),
    }


def test_vidar_treats_execution_unknown_as_recovery_decision_and_refuses_without_durability() -> (
    None
):
    bus = _bus()
    vidar = Vidar(bus=bus)

    asyncio.run(vidar.on_typed_message("object.action-run", _action_run_payload()))

    rollback = bus.messages_on("object.rollback")[-1].payload
    assert rollback["state"] == "refused"
    assert vidar.records[-1].state == "refused"
    assert vidar.behavior_snapshot()["rollback:durability_unavailable"] == 1


def test_thor_releases_resource_lock_after_failed_or_refused_rollback() -> None:
    bus = _bus()
    thor = Thor(bus=bus, action_semantics_catalog=_semantics())
    run = ActionRun(
        correlation_id="rollback-release",
        action_type="test.auto",
        resource_id="resource-release",
        state=ActionRunState.FAILED,
        verdict="auto",
        action_id="action-release",
        idempotency_key="release-key",
        params={},
    )
    thor.action_runs[run.correlation_id] = run
    thor._resource_locks.add("resource-release")

    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            {
                "producer_principal": "Vidar",
                "correlation_id": run.correlation_id,
                "idempotency_key": "rollback-refused",
                "action_run_identity": action_run_identity_digest(run.to_dict()),
                "action_type": run.action_type,
                "resource_id": run.resource_id,
                "contract": run.rollback_contract,
                "state": "refused",
                "rollback_ref": None,
            },
        )
    )

    assert run.state is ActionRunState.ROLLBACK_REFUSED
    assert run.outcome == "rollback_refused"
    assert "resource-release" not in thor._resource_locks


def test_duplicate_verdict_does_not_republish_lifecycle_messages() -> None:
    bus = _bus()
    thor = Thor(bus=bus, action_semantics_catalog=_semantics())
    verdict = _verdict(
        correlation_id="duplicate-verdict",
        idempotency_key="duplicate-verdict-key",
        risk_verdict="deny",
        resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY.value,
    )

    asyncio.run(thor.dispatch_verdict(dict(verdict)))
    first_count = len(bus.messages_on("object.action-run"))
    asyncio.run(thor.dispatch_verdict(dict(verdict)))

    assert len(bus.messages_on("object.action-run")) == first_count
    assert thor.behavior_snapshot()["dispatch:duplicate"] == 1


class _FailingPublishBus:
    async def publish(self, _principal: str, _topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("publish unavailable")


def test_initial_action_run_publish_failure_retains_retryable_run() -> None:
    thor = Thor(bus=_FailingPublishBus(), action_semantics_catalog=_semantics())

    with pytest.raises(RuntimeError, match="publish unavailable"):
        asyncio.run(
            thor.dispatch_verdict(
                _verdict(
                    correlation_id="publish-fails",
                    idempotency_key="publish-fails-key",
                    risk_verdict="deny",
                    resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY.value,
                )
            )
        )

    run = thor.action_runs["publish-fails"]
    assert run.state is ActionRunState.VERDICTED
    assert run.outcome == "action_run_publication_unavailable"
    assert thor._idempotency_runs["publish-fails-key"] is run


class _AcceptingBus:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, _principal: str, _topic: str, payload: dict[str, Any]) -> None:
        self.payloads.append(dict(payload))


class _CheckpointFailStore:
    def __init__(self) -> None:
        self.saved: dict[str, ActionRun] = {}
        self.save_calls = 0

    async def save(self, run: ActionRun) -> None:
        self.save_calls += 1
        if self.save_calls > 1 and run.state in {ActionRunState.SUCCEEDED}:
            raise RuntimeError("checkpoint failed")
        self.saved[run.correlation_id] = ActionRun.from_dict(deepcopy(run.to_dict()))

    async def load_active(self) -> list[ActionRun]:
        return [ActionRun.from_dict(deepcopy(run.to_dict())) for run in self.saved.values()]

    async def delete(self, correlation_id: str) -> None:
        self.saved.pop(correlation_id, None)


def test_terminal_publish_checkpoint_failure_does_not_republish_after_restart() -> None:
    store = _CheckpointFailStore()
    bus = _AcceptingBus()
    thor = Thor(bus=bus, state_store=store)
    run = ActionRun(
        correlation_id="checkpoint-terminal",
        action_type="test.auto",
        resource_id="resource-checkpoint",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        action_id="action-checkpoint",
        idempotency_key="checkpoint-key",
        params={},
        outcome="independent_effect_verified",
        effect_verification_ref=_EFFECT_REF,
        execution_closure_ref=_CLOSURE_REF,
        effect_verified_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    thor.action_runs[run.correlation_id] = run

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        asyncio.run(thor._emit_action_run(run))

    assert len(bus.payloads) == 1
    assert store.saved[run.correlation_id].terminal_published is True

    restarted = Thor(bus=bus, state_store=store)
    asyncio.run(restarted.rehydrate())

    assert len(bus.payloads) == 1


def test_stable_recovery_effect_key_helper_distinguishes_payload_identity() -> None:
    first = stable_idempotency_key(
        "recovery-effect-observation",
        "corr",
        "resource",
        "action",
        "type",
        "key",
        {"value": 1},
        _EFFECT_REF,
        _CLOSURE_REF,
        "sha256:" + "1" * 64,
        "2026-10-01T00:00:00+00:00",
    )
    second = stable_idempotency_key(
        "recovery-effect-observation",
        "corr",
        "resource",
        "action",
        "type",
        "key",
        {"value": 2},
        _EFFECT_REF,
        _CLOSURE_REF,
        "sha256:" + "2" * 64,
        "2026-10-01T00:00:00+00:00",
    )

    assert first != second

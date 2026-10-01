"""End-to-end Pantheon boundaries for development authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents import (
    DevelopmentRuntimeBindings,
    PantheonRuntime,
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.var_ticket_identity import approval_state_key
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.shared.contracts.models import Autonomy
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from jsonschema import Draft202012Validator

from tests.agents.preflight_helpers import PassingPreflightSimulator
from tests.contracts.test_development_authority import (
    NOW,
    _binding,
    _BindingSource,
    _confirmation,
    _profile,
    _verification,
)
from tests.core.risk_gate.test_development_authority import _action


def _verdict(*, evidence: dict[str, object] | None) -> dict[str, object]:
    action_key = "stable-action-one"
    return {
        "producer_principal": "Forseti",
        "correlation_id": "correlation:one",
        "idempotency_key": action_key,
        "action_idempotency_key": action_key,
        "action_id": "action:one",
        "action_type": "ops.restart-service",
        "resource_id": "resource:one",
        "risk_verdict": "hil",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_HIL.value,
        "quorum_required": 2,
        "initiator_principal": "human:owner",
        "rollback_contract": "scripted",
        "params": {"restart": True},
        "safeguards": {
            "stop_condition": "effect verified",
            "tested_rollback_contract": "scripted:test",
            "blast_radius_limit": {"scope": "resource", "max_targets": 1},
            "dry_run_receipt": "sha256:" + "1" * 64,
            "logical_target_lock": "resource:one",
            "stable_idempotency_key": action_key,
            "two_phase_audit_intent": "audit-intent:test",
        },
        **({"development_authority": evidence} if evidence is not None else {}),
    }


def _evidence() -> tuple[object, _BindingSource, dict[str, object]]:
    profile = _profile()
    binding = _binding(profile)
    confirmation = _confirmation(profile, binding)
    return (
        profile,
        _BindingSource(_verification(binding)),
        {
            "schema_version": "1.0.0",
            "confirmation": confirmation.model_dump(mode="json"),
        },
    )


def _action_run_payload(run) -> dict[str, object]:  # noqa: ANN001
    payload = {
        **run.to_dict(),
        "producer_principal": "Thor",
        "state": run.state.value,
        "action_idempotency_key": run.idempotency_key,
    }
    payload["action_run_identity"] = action_run_identity_digest(payload)
    return payload


def test_runtime_profile_selection_is_explicit_and_requires_safety_bindings() -> None:
    profile = _profile()
    source = _BindingSource(_verification(_binding(profile)))
    with pytest.raises(ValueError, match="executor"):
        DevelopmentRuntimeBindings(
            profile=profile,
            executor_principal="identity:other",
            owner_authorizer=lambda _principal: True,
            binding_source=source,
        )
    selected = DevelopmentRuntimeBindings(
        profile=profile,
        executor_principal=profile.executor_principal,
        owner_authorizer=lambda _principal: True,
        binding_source=source,
    )
    with pytest.raises(ValueError, match="durable safety bindings"):
        PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="fdai.events",
            development_authority=selected,
        )


async def _audit(_run: object) -> str:
    return "audit:development-execution-intent"


class _ActionRunStore:
    claim_lease_seconds = 600

    async def save(self, _run: object) -> None:
        return None

    async def load_active(self) -> list[object]:
        return []

    async def delete(self, _correlation_id: str) -> None:
        return None

    async def claim_resource(self, _run: object) -> str:
        return "acquired"

    async def release_resource(self, _resource_id: str, _correlation_id: str) -> bool:
        return True

    async def refresh_resource_claim(self, _run: object) -> bool:
        return True

    async def validate_resource_claim(self, _run: object) -> bool:
        return True


class _DistributedLock:
    distributed = True

    def __init__(self) -> None:
        self._lock = ResourceLockManager()

    def acquire(self, resource_id: str):  # type: ignore[no-untyped-def]
        return self._lock.acquire(resource_id)


async def test_composed_forseti_bus_path_carries_verified_authority_to_execution() -> None:
    action = _action()
    current_digest = "sha256:" + action_type_digest(action)
    now = datetime.now(tz=UTC)
    profile = _profile(
        now=now,
        resource_groups=(),
        action_type_digest=current_digest,
    )
    binding = _binding(profile, action_type_digest=current_digest)
    source = _BindingSource(_verification(binding, now=now))
    confirmation = _confirmation(
        profile,
        binding,
        authenticated_at=now - timedelta(minutes=1),
        confirmed_at=now - timedelta(seconds=30),
    )
    state = InMemoryStateStore()
    executed: list[str] = []

    async def executor(context: dict[str, object]) -> bool:
        executed.append(context["run"].correlation_id)  # type: ignore[union-attr]
        return True

    async def rollback(_payload: dict[str, object]) -> str:
        return "rollback:composed"

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        enforce=True,
        saga=Saga(audit_chain=StateStoreAuditChainAdapter(store=state)),
        thor_executor=executor,
        thor_state_store=StateStoreActionRunStore(store=state),
        rollback_executors={"scripted": rollback},
        vidar_state_store=state,
        var_state_store=state,
        forseti_state_store=state,
        approver_authorizer=lambda _principal, _action: True,
        operator_rbac={profile.owner_principal: frozenset({action.name})},
        execution_resource_lock=_DistributedLock(),
        action_types=(action,),
        thor_preflight_simulator=PassingPreflightSimulator(),
        development_authority=DevelopmentRuntimeBindings(
            profile=profile,
            executor_principal=profile.executor_principal,
            owner_authorizer=lambda principal: principal == profile.owner_principal,
            binding_source=source,
        ),
    )
    forseti = runtime.agents["Forseti"]
    thor = runtime.agents["Thor"]
    var = runtime.agents["Var"]
    assert isinstance(forseti, Forseti)
    assert isinstance(thor, Thor)
    assert isinstance(var, Var)

    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    for agent in (forseti, thor, var, runtime.agents["Vidar"]):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)
    bus.subscribe("object.action-run", "Vidar", runtime.agents["Vidar"].on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    await bus.publish(
        "Huginn",
        "object.event",
        {
            "correlation_id": "correlation:one",
            "idempotency_key": "stable-action-one",
            "event_type": "operator.requested",
            "resource_id": "resource:one",
            "action_type": action.name,
            "action_id": "action:one",
            "params": {"restart": True},
            "initiator_principal": profile.owner_principal,
            "operator_initiated": True,
            "development_authority_confirmation": confirmation.model_dump(mode="json"),
        },
    )
    run = thor.action_runs["correlation:one"]
    verdict_payload = bus.messages_on("object.verdict")[0].payload
    assert run.state is ActionRunState.HIL_PENDING, {
        key: verdict_payload.get(key)
        for key in (
            "risk_verdict",
            "reason",
            "development_authority",
            "action_id",
            "action_type",
            "resource_id",
            "params",
            "idempotency_key",
            "rollback_contract",
            "initiator_principal",
        )
    } | {"requests": source.requests}
    assert run.original_quorum_required == 1
    assert run.effective_quorum_required == 1
    assert run.development_authority is not None
    Draft202012Validator(
        PackageResourceSchemaRegistry().get("authority/full-authority-development"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(run.development_authority)

    approval = await var.decide(
        run.correlation_id,
        approver=profile.owner_principal,
        decision="approve",
    )
    assert approval is not None
    assert run.state is ActionRunState.EFFECT_PENDING
    assert executed == [run.correlation_id]


async def test_var_and_thor_preserve_original_quorum_without_fabricating_people() -> None:
    profile, source, evidence = _evidence()
    executed: list[str] = []

    async def executor(context: dict[str, object]) -> bool:
        executed.append(context["run"].correlation_id)  # type: ignore[union-attr]
        return True

    thor = Thor(
        executor=executor,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        execution_audit_recorder=_audit,
        execution_resource_lock=ResourceLockManager(),
        state_store=_ActionRunStore(),  # type: ignore[arg-type]
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    assert run.state is ActionRunState.HIL_PENDING
    assert run.original_quorum_required == 2
    assert run.effective_quorum_required == 1
    assert run.quorum_required == 1

    var = Var(
        approver_authorizer=lambda _principal, _action: True,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_owner_authorizer=lambda principal: principal == profile.owner_principal,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    approval = await var.decide(
        run.correlation_id,
        approver=profile.owner_principal,
        decision="approve",
    )
    assert approval is not None
    assert approval["approvers"] == [profile.owner_principal]
    assert approval["original_quorum_required"] == 2
    assert approval["effective_quorum_required"] == 1

    await thor.on_typed_message("object.approval", approval)
    assert run.state is ActionRunState.EFFECT_PENDING
    assert executed == [run.correlation_id]


async def test_non_owner_and_wrong_executor_fail_closed() -> None:
    profile, source, evidence = _evidence()
    wrong_executor = Thor(
        development_profile=profile,
        development_executor_principal="identity:other-executor",
        development_binding_source=source,
        clock=lambda: NOW,
    )
    denied = await wrong_executor.dispatch_verdict(_verdict(evidence=evidence))
    assert denied.state is ActionRunState.DENY_DROPPED
    substituted_idempotency = _verdict(evidence=evidence)
    substituted_idempotency["action_idempotency_key"] = "substituted-key"
    substituted_idempotency["safeguards"]["stable_idempotency_key"] = "substituted-key"  # type: ignore[index]
    denied_substitution = await Thor(
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
    ).dispatch_verdict(substituted_idempotency)
    assert denied_substitution.state is ActionRunState.DENY_DROPPED

    thor = Thor(
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        execution_audit_recorder=_audit,
        execution_resource_lock=ResourceLockManager(),
        state_store=_ActionRunStore(),  # type: ignore[arg-type]
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    var = Var(
        approver_authorizer=lambda _principal, _action: True,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_owner_authorizer=lambda _principal: False,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    with pytest.raises(PermissionError, match="authenticated development Owner"):
        await var.decide(
            run.correlation_id,
            approver=profile.owner_principal,
            decision="approve",
        )


async def test_var_durable_journal_records_original_and_effective_quorum() -> None:
    profile, source, evidence = _evidence()
    thor = Thor(
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        execution_audit_recorder=_audit,
        execution_resource_lock=ResourceLockManager(),
        state_store=_ActionRunStore(),  # type: ignore[arg-type]
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    store = InMemoryStateStore()
    var = Var(
        state_store=store,
        approver_authorizer=lambda _principal, _action: True,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_owner_authorizer=lambda _principal: True,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    approval = await var.decide(
        run.correlation_id,
        approver=profile.owner_principal,
        decision="approve",
    )
    assert approval is not None
    identity = action_run_identity_digest(_action_run_payload(run))
    decisions = await store.read_state(
        approval_state_key(run.correlation_id, "decisions", identity)
    )
    final = await store.read_state(approval_state_key(run.correlation_id, "final", identity))

    assert decisions is not None
    assert decisions["original_quorum_required"] == 2
    assert decisions["effective_quorum_required"] == 1
    assert final is not None
    assert final["approval"]["approvers"] == [profile.owner_principal]


async def test_missing_execution_audit_blocks_before_executor_io() -> None:
    profile, source, evidence = _evidence()
    executed = False

    async def executor(_context: dict[str, object]) -> bool:
        nonlocal executed
        executed = True
        return True

    thor = Thor(
        executor=executor,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        execution_resource_lock=ResourceLockManager(),
        state_store=_ActionRunStore(),  # type: ignore[arg-type]
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    var = Var(
        approver_authorizer=lambda _principal, _action: True,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_owner_authorizer=lambda _principal: True,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    approval = await var.decide(
        run.correlation_id,
        approver=profile.owner_principal,
        decision="approve",
    )
    assert approval is not None

    await thor.on_typed_message("object.approval", approval)

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "execution_audit_unavailable"
    assert executed is False


async def test_absent_profile_keeps_default_no_self_approval_and_quorum() -> None:
    thor = Thor(clock=lambda: NOW)
    run = await thor.dispatch_verdict(_verdict(evidence=None))
    assert run.quorum_required == 2
    assert run.original_quorum_required == 2
    assert run.development_authority is None

    var = Var(clock=lambda: NOW)
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    with pytest.raises(ValueError, match="no self-approval"):
        await var.decide(
            run.correlation_id,
            approver="human:owner",
            decision="approve",
        )


async def test_thor_restart_revalidation_rejects_authority_substitution() -> None:
    profile, source, evidence = _evidence()
    thor = Thor(
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    assert run.development_authority is not None
    tampered = deepcopy(run.development_authority)
    tampered["grant"]["confirmation_digest"] = "sha256:" + "f" * 64
    run.development_authority = tampered
    run.state = ActionRunState.APPROVED

    await thor._execute(run)

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "development_authority_revalidation_failed"


async def test_vidar_revalidates_same_action_identity_before_rollback() -> None:
    profile, source, evidence = _evidence()

    async def fail(_context: dict[str, object]) -> bool:
        return False

    thor = Thor(
        executor=fail,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        execution_audit_recorder=_audit,
        execution_resource_lock=ResourceLockManager(),
        state_store=_ActionRunStore(),  # type: ignore[arg-type]
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = await thor.dispatch_verdict(_verdict(evidence=evidence))
    var = Var(
        approver_authorizer=lambda _principal, _action: True,
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_owner_authorizer=lambda _principal: True,
        development_binding_source=source,
        clock=lambda: NOW,
    )
    await var.on_typed_message("object.action-run", _action_run_payload(run))
    approval = await var.decide(
        run.correlation_id,
        approver=profile.owner_principal,
        decision="approve",
    )
    assert approval is not None
    await thor.on_typed_message("object.approval", approval)
    assert run.state is ActionRunState.FAILED

    async def rollback(_payload: dict[str, object]) -> str:
        return "rollback:one"

    vidar = Vidar(
        executors={"scripted": rollback},
        development_profile=profile,
        development_executor_principal=profile.executor_principal,
        development_binding_source=source,
        clock=lambda: NOW,
        allow_process_local_rollback=True,
    )
    record = await vidar.rollback(_action_run_payload(run))
    assert record is not None
    assert record.state == "succeeded"

    substituted = run.to_dict()
    substituted["producer_principal"] = "Thor"
    substituted["params"] = {"restart": False}
    with pytest.raises(ValueError, match="malformed"):
        await vidar.rollback(substituted)

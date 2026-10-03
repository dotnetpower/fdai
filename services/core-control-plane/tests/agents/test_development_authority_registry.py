"""The Pantheon admits a development Owner through Core's recorded binding, not a test double."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.agents import (
    DevelopmentRuntimeBindings,
    PantheonRuntime,
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.delivery.development_bindings import (
    PreparedDevelopmentBindingRegistry,
    azure_scope_value_digest,
)
from fdai.shared.contracts.models import FullAuthorityDevelopmentProfile
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.preflight_helpers import PassingPreflightSimulator
from tests.agents.test_development_authority import _DistributedLock
from tests.contracts.test_development_authority import _confirmation, _profile
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.risk_gate.test_development_authority import _action as _action_type

SUBSCRIPTION = "00000000-0000-0000-0000-00000000de01"
GROUP = "rg-fdai-dev"
TARGET = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}"
    "/providers/Microsoft.Compute/virtualMachines/vm1"
)
PARAMS = {"restart": True}


def _scoped_profile(now: datetime, digest: str) -> FullAuthorityDevelopmentProfile:
    base = _profile(now=now, action_type_digest=digest)
    raw = base.model_dump(mode="json")
    raw["scope"] = {
        "tenant_digest": base.scope.tenant_digest,
        "subscription_digest": azure_scope_value_digest(SUBSCRIPTION),
        "resource_group_digests": [azure_scope_value_digest(GROUP)],
    }
    return FullAuthorityDevelopmentProfile.model_validate(raw)


async def test_core_recorded_binding_carries_one_owner_through_var_and_thor() -> None:
    now = datetime.now(tz=UTC)
    action_type = _action_type()
    profile = _scoped_profile(now, "sha256:" + action_type_digest(action_type))
    state = InMemoryStateStore()
    registry = PreparedDevelopmentBindingRegistry(profile=profile, store=state, clock=lambda: now)
    action = _direct_action(target=TARGET, params=dict(PARAMS))
    verification = await registry.prepare(
        action=action,
        action_type=action_type,
        target_revision="sha256:" + "1" * 64,
        dry_run_digest="sha256:" + "2" * 64,
    )
    confirmation = _confirmation(
        profile,
        verification.binding,
        authenticated_at=now - timedelta(minutes=1),
        confirmed_at=now - timedelta(seconds=30),
    )
    executed: list[str] = []

    async def executor(context: dict[str, object]) -> bool:
        executed.append(context["run"].correlation_id)  # type: ignore[union-attr]
        return True

    async def rollback(_payload: dict[str, object]) -> str:
        return "rollback:registry"

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
        operator_rbac={profile.owner_principal: frozenset({action_type.name})},
        execution_resource_lock=_DistributedLock(),
        action_types=(action_type,),
        thor_preflight_simulator=PassingPreflightSimulator(),
        development_authority=DevelopmentRuntimeBindings(
            profile=profile,
            executor_principal=profile.executor_principal,
            owner_authorizer=lambda principal: principal == profile.owner_principal,
            binding_source=registry,
        ),
    )
    forseti, thor, var = (runtime.agents[name] for name in ("Forseti", "Thor", "Var"))
    assert isinstance(forseti, Forseti) and isinstance(thor, Thor) and isinstance(var, Var)
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    for agent in (forseti, thor, var, runtime.agents["Vidar"]):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)

    event = {
        "correlation_id": "correlation:registry",
        "idempotency_key": action.idempotency_key,
        "event_type": "operator.requested",
        "resource_id": TARGET,
        "action_type": action_type.name,
        "action_id": str(action.action_id),
        "params": dict(PARAMS),
        "initiator_principal": profile.owner_principal,
        "operator_initiated": True,
        "development_authority_confirmation": confirmation.model_dump(mode="json"),
    }
    await bus.publish("Huginn", "object.event", event)

    run = thor.action_runs["correlation:registry"]
    assert run.state is ActionRunState.HIL_PENDING
    assert run.effective_quorum_required == 1
    assert run.development_authority is not None
    approval = await var.decide(
        run.correlation_id, approver=profile.owner_principal, decision="approve"
    )
    assert approval is not None
    assert approval["approvers"] == [profile.owner_principal]
    assert run.state is ActionRunState.EFFECT_PENDING
    assert executed == [run.correlation_id]

    # An operation Core never prepared has no trusted binding, so the path fails closed.
    await bus.publish(
        "Huginn",
        "object.event",
        {**event, "correlation_id": "correlation:unprepared", "params": {"restart": False}},
    )
    unprepared = thor.action_runs.get("correlation:unprepared")
    assert unprepared is None or unprepared.state is not ActionRunState.EFFECT_PENDING
    assert executed == [run.correlation_id]

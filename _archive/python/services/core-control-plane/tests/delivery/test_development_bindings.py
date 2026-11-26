"""Server-prepared development bindings are the only trusted source for development authority."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.delivery.development_bindings import (
    BINDING_PREFIX,
    DEFAULT_BINDING_TTL,
    PreparedDevelopmentBindingRegistry,
    azure_scope_value_digest,
    direct_api_dry_run_digest,
    target_scope,
)
from fdai.shared.contracts.development_authority import evaluate_development_authority
from fdai.shared.contracts.models import (
    Action,
    ActionBlastRadius,
    BlastRadiusComputation,
    BlastRadiusScope,
    ExecutionPath,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    resolve_development_binding,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.contracts.test_development_authority import NOW, _confirmation, _profile
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.risk_gate.test_development_authority import _action as _action_type

SUBSCRIPTION = "00000000-0000-0000-0000-00000000de01"
GROUP = "rg-fdai-dev"
TARGET = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}"
    "/providers/Microsoft.Compute/virtualMachines/vm1"
)


def _profile_for(action_type: OntologyActionType) -> FullAuthorityDevelopmentProfile:
    base = _profile(action_type_digest="sha256:" + action_type_digest(action_type))
    raw = base.model_dump(mode="json")
    raw["scope"] = {
        "tenant_digest": base.scope.tenant_digest,
        "subscription_digest": azure_scope_value_digest(SUBSCRIPTION),
        "resource_group_digests": [azure_scope_value_digest(GROUP)],
    }
    return FullAuthorityDevelopmentProfile.model_validate(raw)


def _operation(target: str = TARGET) -> Action:
    return _direct_action(target=target)


def _registry(
    profile: FullAuthorityDevelopmentProfile,
    store: InMemoryStateStore,
    clock: list,  # type: ignore[type-arg]
) -> PreparedDevelopmentBindingRegistry:
    return PreparedDevelopmentBindingRegistry(profile=profile, store=store, clock=lambda: clock[0])


def _request(
    profile: FullAuthorityDevelopmentProfile,
    action: Action,
    *,
    params: dict[str, object] | None = None,
) -> DevelopmentAuthorityBindingRequest:
    return DevelopmentAuthorityBindingRequest.from_action(
        action_type=action.action_type,
        action_id=str(action.action_id),
        target_ref=action.target_resource_ref,
        params=action.params if params is None else params,
        requester_principal=profile.owner_principal,
        executor_principal=profile.executor_principal,
        idempotency_key=action.idempotency_key,
        rollback_contract=action.rollback_ref.kind.value,
    )


async def _prepare(registry: PreparedDevelopmentBindingRegistry, action: Action, action_type):  # type: ignore[no-untyped-def]
    return await registry.prepare(
        action=action,
        action_type=action_type,
        target_revision="provider-revision@1",
        dry_run_digest=direct_api_dry_run_digest(action),
    )


async def test_prepared_binding_verifies_only_the_exact_current_operation() -> None:
    action_type = _action_type()
    profile = _profile_for(action_type)
    clock = [NOW]
    registry = _registry(profile, InMemoryStateStore(), clock)
    action = _operation()

    verification = await _prepare(registry, action, action_type)

    assert resolve_development_binding(registry, _request(profile, action), now=NOW) == verification
    with pytest.raises(ValueError, match="does not match"):
        resolve_development_binding(
            registry, _request(profile, action, params={"cooldown_seconds": 31}), now=NOW
        )
    other = _direct_action(target=TARGET, idempotency_key="other-idem").model_copy(
        update={
            "action_id": _direct_action(action_id="00000000-0000-0000-0000-000000000099").action_id
        }
    )
    with pytest.raises(ValueError, match="unavailable"):
        resolve_development_binding(registry, _request(profile, other), now=NOW)
    clock[0] = NOW + DEFAULT_BINDING_TTL + timedelta(minutes=1)
    assert registry.verify(_request(profile, action), now=clock[0]) is None


async def test_owner_confirmation_of_the_prepared_binding_admits_quorum_one() -> None:
    action_type = _action_type()
    profile = _profile_for(action_type)
    registry = _registry(profile, InMemoryStateStore(), [NOW])
    verification = await _prepare(registry, _operation(), action_type)

    decision = evaluate_development_authority(
        profile,
        _confirmation(profile, verification.binding),
        verification,
        now=NOW,
        original_quorum=2,
    )

    assert decision.eligible and decision.grant is not None
    assert (decision.grant.original_quorum, decision.grant.effective_quorum) == (2, 1)
    assert verification.binding.requester_principal == profile.owner_principal
    assert verification.binding.executor_principal == profile.executor_principal


@pytest.mark.parametrize(
    "target",
    [
        TARGET.replace(SUBSCRIPTION, "00000000-0000-0000-0000-00000000de02"),
        TARGET.replace(GROUP, "rg-shared"),
        "resource:example/rg/vm1",
    ],
)
async def test_preparation_refuses_targets_outside_the_profile_scope(target: str) -> None:
    action_type = _action_type()
    registry = _registry(_profile_for(action_type), InMemoryStateStore(), [NOW])

    with pytest.raises(ValueError, match="scope|Azure resource ID"):
        await _prepare(registry, _operation(target), action_type)


def _subscription_bound(
    profile: FullAuthorityDevelopmentProfile,
) -> FullAuthorityDevelopmentProfile:
    raw = profile.model_dump(mode="json")
    raw["scope"] = {**raw["scope"], "resource_group_digests": []}
    return FullAuthorityDevelopmentProfile.model_validate(raw)


@pytest.mark.parametrize("declared_on", ["action_type", "action"])
async def test_a_subscription_blast_radius_needs_a_subscription_bound_profile(
    declared_on: str,
) -> None:
    subscription_wide = declared_on == "action_type"
    action_type = _action_type(
        scope=BlastRadiusScope.SUBSCRIPTION if subscription_wide else BlastRadiusScope.RESOURCE
    )
    action = _operation()
    if not subscription_wide:
        action = action.model_copy(
            update={
                "blast_radius": action.blast_radius.model_copy(
                    update={"scope": BlastRadiusScope.SUBSCRIPTION}
                )
            }
        )
    store = InMemoryStateStore()
    group_bound = _registry(_profile_for(action_type), store, [NOW])

    with pytest.raises(ValueError, match="blast radius is outside the profile scope"):
        await _prepare(group_bound, action, action_type)
    assert await group_bound.read_verification(str(action.action_id)) is None

    registry = _registry(_subscription_bound(_profile_for(action_type)), store, [NOW])
    verification = await _prepare(registry, action, action_type)
    assert verification.binding.scope.resource_group_digests == ()
    assert registry.required_scope(action=action, action_type=action_type) == (
        verification.binding.scope
    )


@pytest.mark.parametrize("bucket", [BlastRadiusScope.RESOURCE, BlastRadiusScope.RESOURCE_GROUP])
async def test_a_declared_resource_or_group_blast_radius_keeps_the_target_resource_group(
    bucket: BlastRadiusScope,
) -> None:
    action_type = _action_type(scope=bucket)
    profile = _profile_for(action_type)
    registry = _registry(profile, InMemoryStateStore(), [NOW])

    verification = await _prepare(registry, _operation(), action_type)

    assert verification.binding.scope == target_scope(profile, TARGET)
    assert registry.required_scope(action=_operation(), action_type=action_type) == (
        verification.binding.scope
    )


def _unbounded(case: str) -> OntologyActionType:
    """Return an ActionType whose blast radius the target location cannot bound."""
    if case == "undeclared":
        return _action_type().model_copy(update={"blast_radius": None})
    if case == "graph_derived":
        return _action_type(graph_derived=True)
    blast_radius = ActionBlastRadius(
        computation=(
            BlastRadiusComputation.GRAPH_DERIVED
            if case == "graph_derived_with_bucket"
            else BlastRadiusComputation.STATIC_ENUM
        ),
        static_bucket=BlastRadiusScope.RESOURCE if case == "graph_derived_with_bucket" else None,
    )
    return _action_type().model_copy(update={"blast_radius": blast_radius})


@pytest.mark.parametrize(
    "case",
    ["undeclared", "graph_derived", "graph_derived_with_bucket", "static_without_bucket"],
)
async def test_an_unbounded_blast_radius_needs_the_whole_subscription(case: str) -> None:
    action_type = _unbounded(case)
    action = _operation()
    store = InMemoryStateStore()
    group_bound = _registry(_profile_for(action_type), store, [NOW])

    # The Action itself still reads resource-scoped, so only the ActionType reveals the reach.
    assert action.blast_radius.scope is BlastRadiusScope.RESOURCE
    with pytest.raises(ValueError, match="blast radius is outside the profile scope"):
        await _prepare(group_bound, action, action_type)
    assert await group_bound.read_verification(str(action.action_id)) is None

    registry = _registry(_subscription_bound(_profile_for(action_type)), store, [NOW])
    verification = await _prepare(registry, action, action_type)
    assert verification.binding.scope.resource_group_digests == ()
    assert registry.required_scope(action=action, action_type=action_type) == (
        verification.binding.scope
    )


async def test_preparation_refuses_an_unregistered_action_type() -> None:
    registered = _action_type()
    registry = _registry(_profile_for(registered), InMemoryStateStore(), [NOW])

    with pytest.raises(ValueError, match="not registered"):
        await _prepare(registry, _operation(), _action_type(irreversible=True))


async def test_preparation_is_write_once_audited_and_rejects_a_changed_binding() -> None:
    action_type = _action_type()
    store = InMemoryStateStore()
    registry = _registry(_profile_for(action_type), store, [NOW])
    action = _operation()

    first = await _prepare(registry, action, action_type)
    assert await _prepare(registry, action, action_type) == first
    with pytest.raises(ValueError, match="different development binding"):
        await registry.prepare(
            action=action,
            action_type=action_type,
            target_revision="provider-revision@2",
            dry_run_digest=direct_api_dry_run_digest(action),
        )

    audits = [
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("action_kind") == "development_authority.binding_prepared"
    ]
    assert len(audits) == 1 and audits[0]["execution_authority"] is False
    assert await store.read_state(BINDING_PREFIX + str(action.action_id)) == first.model_dump(
        mode="json"
    )


async def test_restart_warms_only_current_bindings_of_the_same_profile() -> None:
    action_type = _action_type()
    profile = _profile_for(action_type)
    store = InMemoryStateStore()
    action = _operation()
    verification = await _prepare(_registry(profile, store, [NOW]), action, action_type)
    restarted = _registry(profile, store, [NOW + timedelta(minutes=1)])

    assert restarted.verify(_request(profile, action), now=NOW) is None
    assert await restarted.load() == 1
    assert restarted.verify(_request(profile, action), now=NOW + timedelta(minutes=1)) == (
        verification
    )
    expired = _registry(profile, store, [NOW + DEFAULT_BINDING_TTL + timedelta(minutes=1)])
    assert await expired.load() == 0


def test_target_scope_is_case_insensitive_and_keeps_the_profile_tenant() -> None:
    profile = _profile_for(_action_type())

    scope = target_scope(profile, TARGET.upper().replace("/SUBSCRIPTIONS/", "/subscriptions/"))

    assert scope.tenant_digest == profile.scope.tenant_digest
    assert scope.subscription_digest == azure_scope_value_digest(SUBSCRIPTION)
    assert scope.resource_group_digests == (azure_scope_value_digest(GROUP),)
    assert profile.scope.covers(scope)


async def test_park_binding_requires_a_direct_api_action_and_reads_durable_state() -> None:
    action_type = _action_type().model_copy(update={"execution_path": ExecutionPath.DIRECT_API})
    profile = _profile_for(action_type)
    store = InMemoryStateStore()
    registry = _registry(profile, store, [NOW])
    action = _operation()

    with pytest.raises(ValueError, match="direct-API"):
        await registry.prepare_park_binding(
            action=action,
            action_type=action_type.model_copy(update={"execution_path": ExecutionPath.PR_NATIVE}),
            target_revision="sha256:" + "1" * 64,
        )
    prepared = await registry.prepare_park_binding(
        action=action, action_type=action_type, target_revision="sha256:" + "1" * 64
    )
    restarted = _registry(profile, store, [NOW])

    assert prepared.binding.dry_run_digest == direct_api_dry_run_digest(action)
    assert await restarted.read_verification(str(action.action_id)) == prepared
    assert await restarted.read_verification("00000000-0000-0000-0000-00000000ffff") is None
    other_source = FullAuthorityDevelopmentProfile.model_validate(
        {**profile.model_dump(mode="json"), "source_revision": "b" * 40}
    )
    assert (
        await _registry(other_source, store, [NOW]).read_verification(str(action.action_id)) is None
    )

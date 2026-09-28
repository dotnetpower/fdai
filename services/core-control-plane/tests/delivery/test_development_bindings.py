"""Server-prepared development bindings are the only trusted source for development authority."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.delivery.development_bindings import (
    BINDING_PREFIX,
    PreparedDevelopmentBindingRegistry,
    azure_scope_value_digest,
    direct_api_dry_run_digest,
    target_scope,
)
from fdai.shared.contracts.development_authority import evaluate_development_authority
from fdai.shared.contracts.models import (
    Action,
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
    clock[0] = NOW + timedelta(minutes=16)
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
    expired = _registry(profile, store, [NOW + timedelta(minutes=16)])
    assert await expired.load() == 0


def test_target_scope_is_case_insensitive_and_keeps_the_profile_tenant() -> None:
    profile = _profile_for(_action_type())

    scope = target_scope(profile, TARGET.upper().replace("/SUBSCRIPTIONS/", "/subscriptions/"))

    assert scope.tenant_digest == profile.scope.tenant_digest
    assert scope.subscription_digest == azure_scope_value_digest(SUBSCRIPTION)
    assert scope.resource_group_digests == (azure_scope_value_digest(GROUP),)
    assert profile.scope.covers(scope)

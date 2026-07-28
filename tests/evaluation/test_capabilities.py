"""Evaluation capability attenuation cannot raise adapter authority."""

from __future__ import annotations

import itertools

from fdai_evaluation_sdk import AuthorityCeiling, Capability, SideEffectClass

from fdai.evaluation.capabilities import (
    AuthorityAxes,
    CapabilityAxes,
    attenuate_authority,
    attenuate_capabilities,
)


def _capability(capability_id: str, effect: SideEffectClass) -> Capability:
    return Capability(capability_id=capability_id, side_effect_class=effect)


def test_capabilities_require_every_server_owned_axis() -> None:
    capability_id = "observe.metrics.query"
    field_names = tuple(CapabilityAxes.__dataclass_fields__)
    for missing_field in field_names:
        values = {field_name: frozenset({capability_id}) for field_name in field_names}
        values[missing_field] = frozenset()
        result = attenuate_capabilities(
            requested=(_capability(capability_id, SideEffectClass.OBSERVE),),
            catalog={capability_id: SideEffectClass.OBSERVE},
            axes=CapabilityAxes(**values),
        )
        assert not result.allowed
        assert result.denied == (capability_id,)


def test_adapter_cannot_misclassify_substrate_capability_as_workspace() -> None:
    capability_id = "action.kubernetes.patch"
    allowed = frozenset({capability_id})
    result = attenuate_capabilities(
        requested=(_capability(capability_id, SideEffectClass.WORKSPACE),),
        catalog={capability_id: SideEffectClass.SUBSTRATE},
        axes=CapabilityAxes(
            host_allowlist=allowed,
            session_scope=allowed,
            rbac_allowed=allowed,
            promotion_allowed=allowed,
            risk_allowed=allowed,
            approval_allowed=allowed,
        ),
    )

    assert not result.allowed
    assert result.denied == (capability_id,)


def test_workspace_and_substrate_capabilities_remain_independent() -> None:
    workspace_id = "workspace.edit"
    substrate_id = "action.kubernetes.patch"
    workspace_only = frozenset({workspace_id})
    result = attenuate_capabilities(
        requested=(
            _capability(workspace_id, SideEffectClass.WORKSPACE),
            _capability(substrate_id, SideEffectClass.SUBSTRATE),
        ),
        catalog={
            workspace_id: SideEffectClass.WORKSPACE,
            substrate_id: SideEffectClass.SUBSTRATE,
        },
        axes=CapabilityAxes(
            host_allowlist=frozenset({workspace_id, substrate_id}),
            session_scope=frozenset({workspace_id, substrate_id}),
            rbac_allowed=frozenset({workspace_id, substrate_id}),
            promotion_allowed=workspace_only,
            risk_allowed=workspace_only,
            approval_allowed=workspace_only,
        ),
    )

    assert result.allowed_ids == workspace_only
    assert result.denied == (substrate_id,)


def test_authority_is_never_higher_than_any_axis() -> None:
    ceilings = tuple(AuthorityCeiling)
    rank = {
        AuthorityCeiling.SHADOW: 0,
        AuthorityCeiling.HIL: 1,
        AuthorityCeiling.ENFORCE: 2,
    }
    for values in itertools.product(ceilings, repeat=7):
        requested, *axis_values = values
        effective = attenuate_authority(
            requested,
            axes=AuthorityAxes(*axis_values),
        )
        assert rank[effective] == min(rank[value] for value in values)

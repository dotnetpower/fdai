"""Composition-root coverage for context-selection policy authority."""

from __future__ import annotations

import pytest

from fdai.composition import Container, install_capability_bundle
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.working_context import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    ContextPolicyGovernanceError,
    ContextSelectionInput,
    ContextSelectionOutput,
)


class _CandidatePolicy:
    policy_id = "composed-policy-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


def test_default_container_exposes_authoritative_baseline(container: Container) -> None:
    authority = container.context_selection_policy_authority

    assert authority is not None
    assert authority.active_policy().policy_id == "deterministic-tiered-v1"


def test_bundle_install_refreshes_policy_authority_without_mutating_input(
    container: Container,
) -> None:
    authority = container.context_selection_policy_authority
    assert authority is not None
    capability_id = "context.selection.composed-policy-v1"
    policy_ref = "composed-policy-v1@1.0.0"
    bundle = CapabilityBundle(
        capabilities=(
            Capability(
                capability_id=capability_id,
                name="Composed policy",
                category=CapabilityCategory.INVESTIGATION,
                summary="Composition test policy.",
                side_effect_class=SideEffectClass.READ,
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id=capability_id,
                kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                target_ref=policy_ref,
            ),
        ),
    )

    updated = install_capability_bundle(
        container,
        bundle,
        context_selection_policies=(policy_ref,),
    )

    updated_authority = updated.context_selection_policy_authority
    assert updated_authority is not None
    installed = updated_authority.install(
        _CandidatePolicy(),
        capability_id=capability_id,
        expected_revision=0,
    )
    assert installed.records
    with pytest.raises(ContextPolicyGovernanceError, match="not active"):
        authority.install(
            _CandidatePolicy(),
            capability_id=capability_id,
            expected_revision=0,
        )

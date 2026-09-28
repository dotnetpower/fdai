"""Observation-first product profile contract tests."""

from __future__ import annotations

import pytest
from fdai_service_contracts.product_profile import (
    AzureObservationRole,
    ObservationDataSource,
    ObservationReadPermissions,
    ProductAddOn,
    ProductProfile,
)
from pydantic import ValidationError


def test_default_profile_has_no_optional_surface_or_authority() -> None:
    profile = ProductProfile()

    assert profile.name == "observation-first"
    assert profile.add_ons == ()
    assert profile.authority_granted is False
    assert profile.observation_permissions.base_role is AzureObservationRole.READER
    assert profile.observation_permissions.selected_sources == ()
    assert profile.observation_permissions.optional_roles == ()
    assert profile.graph_bindings_selected is False
    assert profile.approval_bindings_selected is False
    assert profile.enforcement_bindings_selected is False
    assert profile.rollback_bindings_selected is False
    assert profile.privileged_executor_bindings_selected is False


def test_explicit_add_ons_select_surfaces_without_granting_authority() -> None:
    profile = ProductProfile(
        add_ons=(
            ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE,
            ProductAddOn.GOVERNED_EXECUTION,
            ProductAddOn.NOTIFICATIONS,
            ProductAddOn.READ_ONLY_CONSOLE,
        ),
        observation_permissions=ObservationReadPermissions(
            selected_sources=(
                ObservationDataSource.AKS,
                ObservationDataSource.AZURE_MONITOR,
                ObservationDataSource.COST_MANAGEMENT,
                ObservationDataSource.EVIDENCE_STORE,
                ObservationDataSource.LOG_ANALYTICS,
            )
        ),
    )

    assert all(profile.selects(add_on) for add_on in ProductAddOn)
    assert profile.authority_granted is False
    assert all(profile.observation_permissions.selects(role) for role in AzureObservationRole)


def test_profile_rejects_noncanonical_or_write_capable_values() -> None:
    with pytest.raises(ValidationError, match="canonical order"):
        ProductProfile(
            add_ons=(
                ProductAddOn.READ_ONLY_CONSOLE,
                ProductAddOn.NOTIFICATIONS,
            )
        )
    with pytest.raises(ValidationError):
        ProductProfile.model_validate(
            {
                "add_ons": ["governed-execution"],
                "authority_granted": True,
            }
        )
    with pytest.raises(ValidationError):
        ProductProfile.model_validate(
            {
                "observation_permissions": {
                    "selected_sources": ["unsupported"],
                }
            }
        )

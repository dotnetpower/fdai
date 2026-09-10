"""Tests for the bounded deploy-identity migration plan guard."""

from __future__ import annotations

import copy

import pytest
from scripts.deployment.azure import guard_deploy_identity_plan as guard

_PRINCIPAL = "00000000-0000-0000-0000-000000000001"
_OLD_PRINCIPAL = "00000000-0000-0000-0000-000000000002"


def _role_change(address: str, role_name: str) -> dict[str, object]:
    return {
        "address": address,
        "type": "azurerm_role_assignment",
        "change": {
            "actions": ["delete", "create"],
            "before": {
                "scope": "same-scope",
                "role_definition_name": role_name,
                "principal_id": _OLD_PRINCIPAL,
            },
            "after": {
                "scope": "same-scope",
                "role_definition_name": role_name,
                "principal_id": _PRINCIPAL,
            },
            "replace_paths": [["principal_id"]],
        },
    }


def _plan() -> dict[str, object]:
    primary = "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner"
    return {
        "resource_changes": [
            {
                "address": guard._FENCE,  # noqa: SLF001 - exact reviewed address
                "type": "terraform_data",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"input": _PRINCIPAL},
                },
            },
            _role_change(primary, "Storage Blob Data Owner"),
            {
                "address": guard._REDUNDANT_ROLE,  # noqa: SLF001
                "type": "azurerm_role_assignment",
                "change": {
                    "actions": ["delete"],
                    "before": {
                        "scope": "same-scope",
                        "role_definition_name": "Storage Blob Data Owner",
                        "principal_id": _PRINCIPAL,
                    },
                    "after": None,
                },
            },
        ]
    }


def test_accepts_only_fenced_stable_principal_role_changes() -> None:
    changed = guard.validate_plan(_plan(), expected_principal_id=_PRINCIPAL)

    assert changed == tuple(
        sorted(
            (
                guard._FENCE,  # noqa: SLF001
                guard._REDUNDANT_ROLE,  # noqa: SLF001
                "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner",
            )
        )
    )


def test_target_arguments_cover_only_the_reviewed_addresses() -> None:
    arguments = guard.target_cli_args()

    assert arguments.count("-target=") == len(guard._TARGETS)  # noqa: SLF001
    for address in guard._TARGETS:  # noqa: SLF001
        assert address in arguments


def test_state_features_preserve_only_present_role_owners() -> None:
    state = [
        "azurerm_role_assignment.dev_gateway_storage_deployer[0]",
        "module.document_storage[0].azurerm_role_assignment.deployer_data_owner",
        "unrelated.resource",
    ]

    assert guard.state_feature_environment(state) == (
        "TF_VAR_enable_dev_operations_gateway=true",
        "TF_VAR_enable_document_ingestion=true",
    )


@pytest.mark.parametrize(
    "mutation",
    ("unexpected-address", "wrong-principal", "changed-scope", "unpaired-delete"),
)
def test_rejects_identity_plan_scope_or_authority_drift(mutation: str) -> None:
    plan = copy.deepcopy(_plan())
    changes = plan["resource_changes"]
    assert isinstance(changes, list)
    role = changes[1]
    assert isinstance(role, dict)
    details = role["change"]
    assert isinstance(details, dict)
    after = details["after"]
    assert isinstance(after, dict)

    if mutation == "unexpected-address":
        role["address"] = "azurerm_role_assignment.unreviewed"
    elif mutation == "wrong-principal":
        after["principal_id"] = "00000000-0000-0000-0000-000000000003"
    elif mutation == "changed-scope":
        after["scope"] = "different-scope"
    else:
        changes.pop(1)

    with pytest.raises(ValueError, match="deploy identity plan"):
        guard.validate_plan(plan, expected_principal_id=_PRINCIPAL)

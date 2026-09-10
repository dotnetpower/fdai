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


def _storage_hardening(address: str, *, retention_days: int = 30) -> dict[str, object]:
    common = {
        "name": "storage",
        "blob_properties": [
            {
                "versioning_enabled": True,
                "delete_retention_policy": [],
                "container_delete_retention_policy": [],
            }
        ],
    }
    after = copy.deepcopy(common)
    after["local_user_enabled"] = False
    after["primary_blob_endpoint"] = None
    after_blob = after["blob_properties"]
    assert isinstance(after_blob, list)
    after_blob[0]["delete_retention_policy"] = [
        {"days": retention_days, "permanent_delete_enabled": False}
    ]
    after_blob[0]["container_delete_retention_policy"] = [{"days": retention_days}]
    before = copy.deepcopy(common)
    before["local_user_enabled"] = True
    before["primary_blob_endpoint"] = "https://storage.blob.core.windows.net/"
    return {
        "address": address,
        "type": "azurerm_storage_account",
        "change": {
            "actions": ["update"],
            "before": before,
            "after": after,
            "after_unknown": {"primary_blob_endpoint": True},
        },
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


def test_target_arguments_cover_only_reviewed_addresses_owned_by_state() -> None:
    present_role = "module.document_storage[0].azurerm_role_assignment.deployer_data_owner"
    arguments = guard.target_cli_args([present_role, guard._REDUNDANT_ROLE])  # noqa: SLF001

    assert arguments.count("-target=") == 3
    for address in (guard._FENCE, present_role, guard._REDUNDANT_ROLE):  # noqa: SLF001
        assert address in arguments
    assert "module.llm_foundry_partner" not in arguments


def test_target_arguments_require_active_foundry_owner_configuration() -> None:
    with pytest.raises(ValueError, match="Foundry deploy role configuration is inactive"):
        guard.target_cli_args(  # noqa: SLF001
            [guard._PARTNER_ROLE],
            environment={"TF_VAR_enable_llm": "true"},
        )

    arguments = guard.target_cli_args(  # noqa: SLF001
        [guard._PARTNER_ROLE],
        environment={
            "TF_VAR_enable_llm": "true",
            "TF_VAR_resolved_capabilities": '[{"publisher":"MistralAI"}]',
        },
    )

    assert guard._PARTNER_ROLE in arguments  # noqa: SLF001


def test_state_features_preserve_only_present_role_owners() -> None:
    state = [
        "azurerm_role_assignment.dev_gateway_storage_deployer[0]",
        "module.document_storage[0].azurerm_role_assignment.deployer_data_owner",
        "module.operator_api_identity[0].azurerm_user_assigned_identity.primary",
        "unrelated.resource",
    ]

    assert guard.state_feature_environment(state) == (
        "TF_VAR_enable_dev_operations_gateway=true",
        "TF_VAR_enable_document_ingestion=true",
        "TF_VAR_enable_operator_api=true",
    )


def test_accepts_paired_storage_security_prerequisite() -> None:
    address = "module.document_storage[0].azurerm_storage_account.documents"
    role = "module.document_storage[0].azurerm_role_assignment.deployer_data_owner"
    plan = _plan()
    changes = plan["resource_changes"]
    assert isinstance(changes, list)
    changes.extend(
        (
            _role_change(role, "Storage Blob Data Owner"),
            _storage_hardening(address),
        )
    )

    changed = guard.validate_plan(plan, expected_principal_id=_PRINCIPAL)

    assert address in changed
    assert role in changed


def test_accepts_gateway_specific_seven_day_retention() -> None:
    address = "azurerm_storage_account.dev_gateway[0]"
    role = "azurerm_role_assignment.dev_gateway_storage_deployer[0]"
    plan = _plan()
    changes = plan["resource_changes"]
    assert isinstance(changes, list)
    changes.extend(
        (
            _role_change(role, "Storage Blob Data Contributor"),
            _storage_hardening(address, retention_days=7),
        )
    )

    changed = guard.validate_plan(plan, expected_principal_id=_PRINCIPAL)

    assert address in changed
    assert role in changed


@pytest.mark.parametrize(
    "mutation",
    (
        "unpaired",
        "weaken-local-user",
        "incomplete-local-user",
        "incomplete-retention",
        "other-field",
        "unknown-security-field",
    ),
)
def test_rejects_invalid_storage_prerequisite(mutation: str) -> None:
    address = "module.document_storage[0].azurerm_storage_account.documents"
    role = "module.document_storage[0].azurerm_role_assignment.deployer_data_owner"
    plan = _plan()
    changes = plan["resource_changes"]
    assert isinstance(changes, list)
    storage = _storage_hardening(address)
    changes.append(storage)
    if mutation != "unpaired":
        changes.append(_role_change(role, "Storage Blob Data Owner"))
    details = storage["change"]
    assert isinstance(details, dict)
    after = details["after"]
    assert isinstance(after, dict)
    if mutation == "weaken-local-user":
        before = details["before"]
        assert isinstance(before, dict)
        before["local_user_enabled"] = False
        after["local_user_enabled"] = True
    elif mutation == "incomplete-local-user":
        after["local_user_enabled"] = True
    elif mutation == "incomplete-retention":
        after_blob = after["blob_properties"]
        assert isinstance(after_blob, list)
        after_blob[0]["container_delete_retention_policy"] = []
    elif mutation == "other-field":
        after["name"] = "different-storage"
    elif mutation == "unknown-security-field":
        before = details["before"]
        assert isinstance(before, dict)
        before["public_network_access_enabled"] = False
        after["public_network_access_enabled"] = None
        details["after_unknown"] = {"public_network_access_enabled": True}

    with pytest.raises(ValueError, match="invalid storage prerequisite"):
        guard.validate_plan(plan, expected_principal_id=_PRINCIPAL)


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

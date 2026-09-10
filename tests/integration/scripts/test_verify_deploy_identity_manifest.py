"""Tests for stable deploy identity role-manifest verification."""

from __future__ import annotations

import copy

import pytest
from scripts.deployment.azure import verify_deploy_identity_manifest as manifest

_PRINCIPAL = "00000000-0000-0000-0000-000000000001"


def _state() -> dict[str, object]:
    return {
        "values": {
            "root_module": {
                "resources": [],
                "child_modules": [
                    {
                        "resources": [
                            {
                                "type": "azurerm_role_assignment",
                                "values": {
                                    "scope": "/subscriptions/example/resourceGroups/app",
                                    "role_definition_id": (
                                        "/subscriptions/example/providers/"
                                        "Microsoft.Authorization/roleDefinitions/reader"
                                    ),
                                    "principal_id": _PRINCIPAL,
                                    "condition": None,
                                    "condition_version": None,
                                },
                            }
                        ]
                    }
                ],
            }
        }
    }


def _assignments() -> list[dict[str, object]]:
    return [
        {
            "scope": "/subscriptions/example/resourceGroups/app",
            "roleDefinitionId": (
                "/subscriptions/example/providers/Microsoft.Authorization/roleDefinitions/reader"
            ),
            "condition": None,
            "conditionVersion": None,
        }
    ]


def test_manifest_requires_exact_terraform_and_azure_role_sets() -> None:
    receipt = manifest.verify_manifest(
        [_state()],
        principal_id=_PRINCIPAL,
        assignments=_assignments(),
    )

    assert receipt["manifest_verified"] is True
    assert receipt["role_count"] == 1


@pytest.mark.parametrize("drift", ("missing", "extra", "condition"))
def test_manifest_rejects_missing_extra_or_changed_roles(drift: str) -> None:
    assignments = copy.deepcopy(_assignments())
    if drift == "missing":
        assignments.clear()
    elif drift == "extra":
        assignments.append(
            {
                "scope": "/subscriptions/example",
                "roleDefinitionId": "owner",
                "condition": None,
                "conditionVersion": None,
            }
        )
    else:
        assignments[0]["condition"] = "@Resource[example] StringEquals 'other'"

    with pytest.raises(ValueError, match="manifest drift"):
        manifest.verify_manifest(
            [_state()],
            principal_id=_PRINCIPAL,
            assignments=assignments,
        )

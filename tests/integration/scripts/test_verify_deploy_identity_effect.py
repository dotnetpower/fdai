"""Tests for stable deploy identity effect verification."""

from __future__ import annotations

import copy

import pytest
from scripts.deployment.azure import guard_deploy_identity_plan as guard
from scripts.deployment.azure import verify_deploy_identity_effect as effect

_PRINCIPAL = "00000000-0000-0000-0000-000000000001"
_OLD_PRINCIPAL = "00000000-0000-0000-0000-000000000002"
_ADDRESS = "azurerm_role_assignment.kv_officer_self"


def _plan() -> dict[str, object]:
    return {
        "resource_changes": [
            {
                "address": _ADDRESS,
                "type": "azurerm_role_assignment",
                "change": {
                    "actions": ["delete", "create"],
                    "before": {
                        "scope": "same-scope",
                        "role_definition_name": guard._ROLE_TARGETS[_ADDRESS],  # noqa: SLF001
                        "principal_id": _OLD_PRINCIPAL,
                    },
                    "after": {
                        "scope": "same-scope",
                        "role_definition_name": guard._ROLE_TARGETS[_ADDRESS],  # noqa: SLF001
                        "principal_id": _PRINCIPAL,
                    },
                    "replace_paths": [["principal_id"]],
                },
            }
        ]
    }


def test_verifies_planned_roles_and_retired_principal_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignments = {
        _PRINCIPAL: [
            {
                "scope": "same-scope",
                "roleDefinitionName": "Key Vault Secrets Officer",
            }
        ],
        _OLD_PRINCIPAL: [],
    }
    monkeypatch.setattr(effect, "_role_assignments", lambda principal: assignments[principal])

    receipt = effect.verify_live_effect(_plan(), expected_principal_id=_PRINCIPAL)

    assert receipt["effect_verified"] is True
    assert receipt["expected_role_count"] == 1
    assert receipt["retired_assignment_count"] == 0


@pytest.mark.parametrize("failure", ("missing-role", "retired-role"))
def test_rejects_incomplete_or_stale_live_authority(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    assignments = {
        _PRINCIPAL: (
            []
            if failure == "missing-role"
            else [
                {
                    "scope": "same-scope",
                    "roleDefinitionName": "Key Vault Secrets Officer",
                }
            ]
        ),
        _OLD_PRINCIPAL: (
            [{"scope": "other", "roleDefinitionName": "Reader"}]
            if failure == "retired-role"
            else []
        ),
    }
    monkeypatch.setattr(effect, "_role_assignments", lambda principal: assignments[principal])

    with pytest.raises(ValueError):
        effect.verify_live_effect(copy.deepcopy(_plan()), expected_principal_id=_PRINCIPAL)

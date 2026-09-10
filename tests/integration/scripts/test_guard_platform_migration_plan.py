"""Regression tests for reviewed platform migration plan filtering."""

from __future__ import annotations

import copy

import pytest
from scripts.deployment.azure import guard_platform_migration_plan as guard

_DEPLOY_PRINCIPAL = "00000000-0000-0000-0000-000000000001"


def _role(
    address: str,
    *,
    replacement_field: str,
    role_name: str,
) -> dict[str, object]:
    before = {
        "scope": "old-scope" if replacement_field == "scope" else "same-scope",
        "role_definition_name": role_name,
        "principal_id": (
            "old-principal" if replacement_field == "principal_id" else "same-principal"
        ),
        "condition": None,
        "delegated_managed_identity_resource_id": None,
    }
    after = {
        **before,
        replacement_field: ("new-scope" if replacement_field == "scope" else _DEPLOY_PRINCIPAL),
    }
    return {
        "address": address,
        "change": {
            "actions": ["delete", "create"],
            "before": before,
            "after": after,
            "replace_paths": [[replacement_field]],
        },
    }


def _embedding() -> dict[str, object]:
    return {
        "address": guard._EMBEDDING_ADDRESS,  # noqa: SLF001 - exact migration fixture
        "change": {
            "actions": ["delete", "create"],
            "before": {
                "name": "t1.embedding",
                "cognitive_account_id": "same-account",
                "model": [{"format": "OpenAI", "name": "text-embedding-3-small", "version": "1"}],
                "sku": [{"name": "GlobalStandard", "capacity": 803}],
            },
            "after": {
                "name": "t1.embedding",
                "cognitive_account_id": "same-account",
                "model": [{"format": "OpenAI", "name": "text-embedding-3-large", "version": "1"}],
                "sku": [{"name": "Standard", "capacity": 200}],
            },
        },
    }


def _plan() -> dict[str, object]:
    changes: list[dict[str, object]] = [
        _role(address, replacement_field=field, role_name=role)
        for address, (field, role) in guard._ROLE_REPLACEMENTS.items()  # noqa: SLF001
    ]
    for retired, resource_name in guard._MEASUREMENT_RETIREMENTS.items():  # noqa: SLF001
        changes.append(
            {
                "address": retired,
                "mode": "managed",
                "type": "azurerm_container_app_job",
                "name": resource_name,
                "index": 0,
                "change": {
                    "actions": ["delete"],
                    "before": {"name": f"example-{resource_name}"},
                    "after": None,
                },
            }
        )
    changes.extend(
        [
            _embedding(),
            {
                "address": "unrelated.safe_update",
                "change": {"actions": ["update"], "before": {}, "after": {}},
            },
        ]
    )
    return {"resource_changes": changes}


def _change(plan: dict[str, object], address: str) -> dict[str, object]:
    changes = plan["resource_changes"]
    assert isinstance(changes, list)
    for change in changes:
        assert isinstance(change, dict)
        if change.get("address") == address:
            return change
    raise AssertionError(f"missing fixture address: {address}")


def test_filters_only_exact_reviewed_platform_migrations() -> None:
    plan = _plan()

    filtered, validated = guard.filter_reviewed_platform_migrations(
        plan,
        expected_deploy_principal_id=_DEPLOY_PRINCIPAL,
    )

    assert len(validated) == 12
    remaining = filtered["resource_changes"]
    assert isinstance(remaining, list)
    assert {change["address"] for change in remaining} == {"unrelated.safe_update"}


def test_role_guard_ignores_optional_provider_metadata() -> None:
    plan = _plan()
    first_role = next(iter(guard._ROLE_REPLACEMENTS))  # noqa: SLF001
    role_change = _change(plan, first_role)["change"]
    assert isinstance(role_change, dict)
    after = role_change["after"]
    assert isinstance(after, dict)
    after["condition"] = ""
    after["delegated_managed_identity_resource_id"] = "provider-computed"

    _filtered, validated = guard.filter_reviewed_platform_migrations(
        plan,
        expected_deploy_principal_id=_DEPLOY_PRINCIPAL,
    )

    assert first_role in validated


@pytest.mark.parametrize(
    "mutation",
    [
        "role-name",
        "role-path",
        "role-stable-field",
        "measurement-action",
        "measurement-mode",
        "measurement-type",
        "measurement-resource-name",
        "measurement-index",
        "measurement-before",
        "measurement-after",
        "measurement-replacement-path",
        "embedding-family",
        "embedding-capacity",
    ],
)
def test_rejects_platform_migration_shape_drift(mutation: str) -> None:
    plan = copy.deepcopy(_plan())
    first_role = next(iter(guard._ROLE_REPLACEMENTS))  # noqa: SLF001
    first_retired = next(iter(guard._MEASUREMENT_RETIREMENTS))  # noqa: SLF001

    if mutation.startswith("role-"):
        role_change = _change(plan, first_role)["change"]
        assert isinstance(role_change, dict)
        before = role_change["before"]
        after = role_change["after"]
        assert isinstance(before, dict)
        assert isinstance(after, dict)
        if mutation == "role-name":
            after["role_definition_name"] = "Owner"
        elif mutation == "role-path":
            role_change["replace_paths"] = [["scope"]]
        else:
            after["scope"] = "different-scope"
    elif mutation == "measurement-action":
        retirement = _change(plan, first_retired)["change"]
        assert isinstance(retirement, dict)
        retirement["actions"] = ["delete", "create"]
    elif mutation == "measurement-mode":
        _change(plan, first_retired)["mode"] = "data"
    elif mutation == "measurement-type":
        _change(plan, first_retired)["type"] = "azurerm_container_app"
    elif mutation == "measurement-resource-name":
        _change(plan, first_retired)["name"] = "other_job"
    elif mutation == "measurement-index":
        _change(plan, first_retired)["index"] = 1
    elif mutation in {"measurement-before", "measurement-after"}:
        retirement = _change(plan, first_retired)["change"]
        assert isinstance(retirement, dict)
        retirement[mutation.removeprefix("measurement-")] = (
            None if mutation.endswith("before") else {}
        )
    elif mutation == "measurement-replacement-path":
        retirement = _change(plan, first_retired)["change"]
        assert isinstance(retirement, dict)
        retirement["replace_paths"] = [["name"]]
    else:
        embedding = _change(plan, guard._EMBEDDING_ADDRESS)["change"]  # noqa: SLF001
        assert isinstance(embedding, dict)
        after = embedding["after"]
        assert isinstance(after, dict)
        if mutation == "embedding-family":
            after["model"] = [{"format": "OpenAI", "name": "other", "version": "1"}]
        else:
            after["sku"] = [{"name": "Standard", "capacity": 201}]

    with pytest.raises(ValueError, match="unapproved"):
        guard.filter_reviewed_platform_migrations(
            plan,
            expected_deploy_principal_id=_DEPLOY_PRINCIPAL,
        )


def test_rejects_role_replacement_to_another_principal() -> None:
    plan = _plan()
    principal_role = next(
        address
        for address, (field, _role) in guard._ROLE_REPLACEMENTS.items()  # noqa: SLF001
        if field == "principal_id"
    )
    details = _change(plan, principal_role)["change"]
    assert isinstance(details, dict)
    after = details["after"]
    assert isinstance(after, dict)
    after["principal_id"] = "00000000-0000-0000-0000-000000000002"

    with pytest.raises(ValueError, match="unapproved"):
        guard.filter_reviewed_platform_migrations(
            plan,
            expected_deploy_principal_id=_DEPLOY_PRINCIPAL,
        )

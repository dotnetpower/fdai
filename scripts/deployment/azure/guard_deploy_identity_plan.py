#!/usr/bin/env python3
"""Validate the bounded stable deploy-identity Terraform migration plan."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FENCE = "terraform_data.deploy_runner_identity_fence"
_PARTNER_ROLE = 'module.llm_foundry_partner[0].azurerm_role_assignment.project_user["deployer"]'
_WEB_SEARCH_ROLE = 'module.foundry_web_search[0].azurerm_role_assignment.project_user["deployer"]'
_ROLE_TARGETS = {
    "azurerm_role_assignment.dev_gateway_storage_deployer[0]": ("Storage Blob Data Contributor"),
    "azurerm_role_assignment.kv_officer_self": "Key Vault Secrets Officer",
    "module.case_history_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "Storage Blob Data Owner"
    ),
    "module.decision_evidence_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "Storage Blob Data Owner"
    ),
    "module.document_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "Storage Blob Data Owner"
    ),
    _PARTNER_ROLE: "Azure AI User",
    _WEB_SEARCH_ROLE: "Azure AI User",
    "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "Storage Blob Data Owner"
    ),
    "module.rule_catalog_snapshot_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "Storage Blob Data Owner"
    ),
}
_REDUNDANT_ROLE = (
    "module.operational_history_storage[0].azurerm_role_assignment.terraform_runner_data_owner[0]"
)
_TARGETS = (_FENCE, *_ROLE_TARGETS, _REDUNDANT_ROLE)
_STORAGE_PREREQUISITES = {
    "azurerm_storage_account.dev_gateway[0]": (
        "azurerm_role_assignment.dev_gateway_storage_deployer[0]",
        7,
    ),
    "module.case_history_storage[0].azurerm_storage_account.case_history": (
        "module.case_history_storage[0].azurerm_role_assignment.deployer_data_owner",
        30,
    ),
    "module.decision_evidence_storage[0].azurerm_storage_account.case_history": (
        "module.decision_evidence_storage[0].azurerm_role_assignment.deployer_data_owner",
        30,
    ),
    "module.document_storage[0].azurerm_storage_account.documents": (
        "module.document_storage[0].azurerm_role_assignment.deployer_data_owner",
        30,
    ),
    "module.operational_history_storage[0].azurerm_storage_account.case_history": (
        "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner",
        30,
    ),
    "module.rule_catalog_snapshot_storage[0].azurerm_storage_account.case_history": (
        "module.rule_catalog_snapshot_storage[0].azurerm_role_assignment.deployer_data_owner",
        30,
    ),
}
_STATE_FEATURES = {
    "azurerm_role_assignment.dev_gateway_storage_deployer[0]": (
        "TF_VAR_enable_dev_operations_gateway"
    ),
    "module.document_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_document_ingestion"
    ),
    _PARTNER_ROLE: "TF_VAR_enable_llm",
    _WEB_SEARCH_ROLE: "TF_VAR_enable_llm",
    "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_operational_history"
    ),
    "module.rule_catalog_snapshot_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_rule_catalog_snapshot_storage"
    ),
    "module.operator_api_identity[0].azurerm_user_assigned_identity.primary": (
        "TF_VAR_enable_operator_api"
    ),
}


def target_cli_args(
    state_addresses: list[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return only reviewed Terraform targets already owned by state."""

    addresses = set(state_addresses)
    values = os.environ if environment is None else environment
    inactive = sorted(
        address
        for address in (_PARTNER_ROLE, _WEB_SEARCH_ROLE)
        if address in addresses and not _foundry_target_is_active(address, values)
    )
    if inactive:
        raise ValueError(
            "state-owned Foundry deploy role configuration is inactive: " + ", ".join(inactive)
        )
    targets = (
        _FENCE,
        *(address for address in _ROLE_TARGETS if address in addresses),
        *(_REDUNDANT_ROLE for _ in range(_REDUNDANT_ROLE in addresses)),
    )
    return shlex.join(f"-target={address}" for address in targets)


def _foundry_target_is_active(
    address: str,
    environment: Mapping[str, str],
) -> bool:
    if environment.get("TF_VAR_enable_llm") != "true":
        return False
    try:
        capabilities = json.loads(environment.get("TF_VAR_resolved_capabilities", "[]"))
    except json.JSONDecodeError:
        return False
    if not isinstance(capabilities, list):
        return False
    if address == _PARTNER_ROLE:
        return any(
            isinstance(item, Mapping) and item.get("publisher") in {"Anthropic", "MistralAI"}
            for item in capabilities
        )
    return environment.get("TF_VAR_operator_api_web_search_enabled") == "true" and any(
        isinstance(item, Mapping) and item.get("name") == "t1.web_search" for item in capabilities
    )


def state_feature_environment(state_addresses: list[str]) -> tuple[str, ...]:
    """Return feature enablements required to preserve state-backed role targets."""

    addresses = set(state_addresses)
    return tuple(
        f"{name}=true"
        for name in sorted(
            {variable for address, variable in _STATE_FEATURES.items() if address in addresses}
        )
    )


def validate_plan(plan: object, *, expected_principal_id: str) -> tuple[str, ...]:
    """Accept only exact deployer-role convergence to the stable principal."""

    if _GUID.fullmatch(expected_principal_id) is None:
        raise ValueError("expected deploy principal id must be a GUID")
    if not isinstance(plan, Mapping):
        raise ValueError("deploy identity plan MUST be an object")
    raw_changes = plan.get("resource_changes")
    if not isinstance(raw_changes, list):
        raise ValueError("deploy identity plan resource_changes MUST be an array")

    changed: dict[str, Mapping[str, object]] = {}
    for raw_change in raw_changes:
        if not isinstance(raw_change, Mapping):
            raise ValueError("deploy identity resource changes MUST be objects")
        details = raw_change.get("change")
        if not isinstance(details, Mapping):
            raise ValueError("deploy identity resource change details are invalid")
        actions = tuple(details.get("actions", ()))
        if actions in {("no-op",), ("read",)}:
            continue
        address = raw_change.get("address")
        if not isinstance(address, str) or (
            address not in _TARGETS and address not in _STORAGE_PREREQUISITES
        ):
            raise ValueError(f"deploy identity plan changes an unapproved address: {address}")
        if address in changed:
            raise ValueError("deploy identity plan has duplicate resource addresses")
        changed[address] = raw_change

    if not changed:
        return ()
    fence = changed.get(_FENCE)
    if fence is not None and not _valid_fence(fence, expected_principal_id):
        raise ValueError("deploy identity plan has an invalid principal fence")

    for address, role_name in _ROLE_TARGETS.items():
        change = changed.get(address)
        if change is not None and not _valid_role_change(
            change,
            role_name=role_name,
            expected_principal_id=expected_principal_id,
        ):
            raise ValueError(f"deploy identity plan has an invalid role change: {address}")

    for address, (paired_role, retention_days) in _STORAGE_PREREQUISITES.items():
        change = changed.get(address)
        if change is not None and (
            paired_role not in changed
            or not _valid_storage_hardening(change, retention_days=retention_days)
        ):
            raise ValueError(f"deploy identity plan has an invalid storage prerequisite: {address}")

    redundant = changed.get(_REDUNDANT_ROLE)
    if redundant is not None:
        primary = changed.get(
            "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner"
        )
        if not _valid_redundant_role_delete(redundant, expected_principal_id) or primary is None:
            raise ValueError("deploy identity plan has an unpaired redundant role deletion")
    return tuple(sorted(changed))


def _valid_fence(change: Mapping[str, object], expected_principal_id: str) -> bool:
    details = _details(change)
    after = details.get("after")
    return (
        _actions(details) in {("create",), ("update",)}
        and isinstance(after, Mapping)
        and str(after.get("input", "")).casefold() == expected_principal_id.casefold()
    )


def _valid_role_change(
    change: Mapping[str, object],
    *,
    role_name: str,
    expected_principal_id: str,
) -> bool:
    details = _details(change)
    before = details.get("before")
    after = details.get("after")
    if not isinstance(after, Mapping):
        return False
    actions = _actions(details)
    common = (
        change.get("type") == "azurerm_role_assignment"
        and after.get("role_definition_name") == role_name
        and _nonempty(after.get("scope"))
        and str(after.get("principal_id", "")).casefold() == expected_principal_id.casefold()
    )
    if actions == ("create",):
        return common and before is None
    return (
        common
        and actions == ("delete", "create")
        and details.get("replace_paths") == [["principal_id"]]
        and isinstance(before, Mapping)
        and before.get("role_definition_name") == after.get("role_definition_name")
        and before.get("scope") == after.get("scope")
        and _nonempty(before.get("principal_id"))
        and str(before.get("principal_id", "")).casefold() != expected_principal_id.casefold()
    )


def _valid_redundant_role_delete(
    change: Mapping[str, object],
    expected_principal_id: str,
) -> bool:
    details = _details(change)
    before = details.get("before")
    return (
        change.get("type") == "azurerm_role_assignment"
        and _actions(details) == ("delete",)
        and isinstance(before, Mapping)
        and before.get("role_definition_name") == "Storage Blob Data Owner"
        and _nonempty(before.get("scope"))
        and str(before.get("principal_id", "")).casefold() == expected_principal_id.casefold()
        and details.get("after") is None
        and not details.get("replace_paths")
    )


def _valid_storage_hardening(
    change: Mapping[str, object],
    *,
    retention_days: int,
) -> bool:
    details = _details(change)
    before = details.get("before")
    after = details.get("after")
    if (
        change.get("type") != "azurerm_storage_account"
        or _actions(details) != ("update",)
        or details.get("replace_paths") not in (None, [])
        or not isinstance(before, Mapping)
        or not isinstance(after, Mapping)
    ):
        return False

    normalized_before = copy.deepcopy(dict(before))
    normalized_after = copy.deepcopy(dict(after))
    hardened = False
    if before.get("local_user_enabled") != after.get("local_user_enabled"):
        if (
            before.get("local_user_enabled") is not True
            or after.get("local_user_enabled") is not False
        ):
            return False
        normalized_before["local_user_enabled"] = False
        hardened = True

    before_blob = _single_block(before.get("blob_properties"))
    after_blob = _single_block(after.get("blob_properties"))
    normalized_before_blob = _single_block(normalized_before.get("blob_properties"))
    normalized_after_blob = _single_block(normalized_after.get("blob_properties"))
    if (
        before_blob is None
        or after_blob is None
        or normalized_before_blob is None
        or normalized_after_blob is None
        or after.get("local_user_enabled") is not False
        or not all(
            _valid_retention_policy(after_blob.get(policy), days=retention_days)
            for policy in ("delete_retention_policy", "container_delete_retention_policy")
        )
    ):
        return False
    for policy in ("delete_retention_policy", "container_delete_retention_policy"):
        if before_blob.get(policy) == after_blob.get(policy):
            continue
        if not _valid_retention_addition(
            before_blob.get(policy),
            after_blob.get(policy),
            days=retention_days,
        ):
            return False
        normalized_before_blob[policy] = normalized_after_blob[policy]
        hardened = True

    after_unknown = details.get("after_unknown")
    return (
        hardened
        and _unknown_values_allowed(after_unknown)
        and _known_values_equal(
            normalized_before,
            normalized_after,
            after_unknown,
        )
    )


def _single_block(value: object) -> dict[str, object] | None:
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], Mapping):
        return value[0] if isinstance(value[0], dict) else dict(value[0])
    return None


def _valid_retention_addition(before: object, after: object, *, days: int) -> bool:
    if before not in (None, []):
        return False
    return _valid_retention_policy(after, days=days)


def _valid_retention_policy(after: object, *, days: int) -> bool:
    if not isinstance(after, list) or len(after) != 1 or not isinstance(after[0], Mapping):
        return False
    allowed = {"days": days, "permanent_delete_enabled": False}
    return after[0].get("days") == days and all(
        key in allowed and allowed[key] == value for key, value in after[0].items()
    )


def _unknown_values_allowed(
    unknown: object,
    path: tuple[str | int, ...] = (),
) -> bool:
    if unknown in (None, False):
        return True
    if unknown is True:
        return (
            len(path) == 1
            and isinstance(path[0], str)
            and path[0].startswith(("primary_", "secondary_"))
        )
    if isinstance(unknown, Mapping):
        return all(_unknown_values_allowed(value, (*path, key)) for key, value in unknown.items())
    if isinstance(unknown, list):
        return all(
            _unknown_values_allowed(value, (*path, index)) for index, value in enumerate(unknown)
        )
    return False


def _known_values_equal(
    before: object,
    after: object,
    unknown: object,
    path: tuple[str | int, ...] = (),
) -> bool:
    if unknown is True:
        return (
            len(path) == 1
            and isinstance(path[0], str)
            and path[0].startswith(("primary_", "secondary_"))
        )
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        unknown_map = unknown if isinstance(unknown, Mapping) else {}
        return set(before) == set(after) and all(
            _known_values_equal(
                before[key],
                after[key],
                unknown_map.get(key),
                (*path, key),
            )
            for key in before
        )
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return False
        unknown_items = unknown if isinstance(unknown, list) else []
        return all(
            _known_values_equal(
                before[index],
                after[index],
                unknown_items[index] if index < len(unknown_items) else None,
                (*path, index),
            )
            for index in range(len(before))
        )
    return before == after


def _details(change: Mapping[str, object]) -> Mapping[str, object]:
    details = change.get("change")
    return details if isinstance(details, Mapping) else {}


def _actions(details: Mapping[str, object]) -> tuple[object, ...]:
    actions = details.get("actions")
    return tuple(actions) if isinstance(actions, list) else ()


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    targets = subcommands.add_parser("target-env")
    target_source = targets.add_mutually_exclusive_group(required=True)
    target_source.add_argument("--state-list", type=Path)
    target_source.add_argument("--terraform-dir", type=Path)
    state_env = subcommands.add_parser("state-env")
    state_source = state_env.add_mutually_exclusive_group(required=True)
    state_source.add_argument("--state-list", type=Path)
    state_source.add_argument("--terraform-dir", type=Path)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "target-env":
        print(f"TF_CLI_ARGS_plan={target_cli_args(_read_state_addresses(args))}")
        return 0
    if args.command == "state-env":
        for value in state_feature_environment(_read_state_addresses(args)):
            print(value)
        return 0

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        changed = validate_plan(
            plan,
            expected_principal_id=os.environ.get("DEPLOY_RUNNER_PRINCIPAL_ID", ""),
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"deploy identity plan accepted: {len(changed)} bounded change(s)")
    return 0


def _read_state_addresses(args: argparse.Namespace) -> list[str]:
    state_list = args.state_list
    if state_list is not None:
        if not isinstance(state_list, Path):
            raise ValueError("state list path is invalid")
        return state_list.read_text(encoding="utf-8").splitlines()
    terraform_dir = args.terraform_dir
    if not isinstance(terraform_dir, Path):
        raise ValueError("Terraform directory is invalid")
    completed = subprocess.run(
        ["terraform", "state", "list"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=terraform_dir,
    )
    return completed.stdout.splitlines()


if __name__ == "__main__":
    raise SystemExit(main())

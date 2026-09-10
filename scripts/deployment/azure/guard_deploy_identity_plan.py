#!/usr/bin/env python3
"""Validate the bounded stable deploy-identity Terraform migration plan."""

from __future__ import annotations

import argparse
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
    "module.llm_foundry_partner[0].azurerm_role_assignment.project_user["
    '"deployer"]': "Azure AI User",
    "module.foundry_web_search[0].azurerm_role_assignment.project_user["
    '"deployer"]': "Azure AI User",
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
_STATE_FEATURES = {
    "azurerm_role_assignment.dev_gateway_storage_deployer[0]": (
        "TF_VAR_enable_dev_operations_gateway"
    ),
    "module.document_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_document_ingestion"
    ),
    "module.llm_foundry_partner[0].azurerm_role_assignment.project_user["
    '"deployer"]': "TF_VAR_enable_llm",
    "module.foundry_web_search[0].azurerm_role_assignment.project_user["
    '"deployer"]': "TF_VAR_enable_llm",
    "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_operational_history"
    ),
    "module.rule_catalog_snapshot_storage[0].azurerm_role_assignment.deployer_data_owner": (
        "TF_VAR_enable_rule_catalog_snapshot_storage"
    ),
}


def target_cli_args() -> str:
    """Return the reviewed Terraform targets as one TF_CLI_ARGS_plan value."""

    return shlex.join(f"-target={address}" for address in _TARGETS)


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
        if not isinstance(address, str) or address not in _TARGETS:
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
    subcommands.add_parser("targets")
    state_env = subcommands.add_parser("state-env")
    state_source = state_env.add_mutually_exclusive_group(required=True)
    state_source.add_argument("--state-list", type=Path)
    state_source.add_argument("--terraform-dir", type=Path)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "targets":
        print(target_cli_args())
        return 0
    if args.command == "state-env":
        if args.state_list is not None:
            addresses = args.state_list.read_text(encoding="utf-8").splitlines()
        else:
            completed = subprocess.run(
                ["terraform", "state", "list"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=args.terraform_dir,
            )
            addresses = completed.stdout.splitlines()
        for value in state_feature_environment(addresses):
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


if __name__ == "__main__":
    raise SystemExit(main())

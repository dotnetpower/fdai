#!/usr/bin/env python3
"""Adopt existing stable deploy roles after an interrupted identity apply."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_STATE_ID = re.compile(r'^\s*id\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RoleBinding:
    address: str
    scope_expression: str
    role_name: str
    owner_state_address: str | None = None


_ROLE_BINDINGS = (
    RoleBinding(
        "azurerm_role_assignment.dev_gateway_storage_deployer[0]",
        'try(azurerm_storage_account.dev_gateway[0].id, "")',
        "Storage Blob Data Contributor",
        "azurerm_storage_account.dev_gateway[0]",
    ),
    RoleBinding(
        "azurerm_role_assignment.kv_officer_self",
        'try(module.key_vault.id, "")',
        "Key Vault Secrets Officer",
    ),
    RoleBinding(
        "module.case_history_storage[0].azurerm_role_assignment.deployer_data_owner",
        'try(module.case_history_storage[0].id, "")',
        "Storage Blob Data Owner",
        "module.case_history_storage[0].azurerm_storage_account.case_history",
    ),
    RoleBinding(
        "module.decision_evidence_storage[0].azurerm_role_assignment.deployer_data_owner",
        'try(module.decision_evidence_storage[0].id, "")',
        "Storage Blob Data Owner",
        "module.decision_evidence_storage[0].azurerm_storage_account.case_history",
    ),
    RoleBinding(
        "module.document_storage[0].azurerm_role_assignment.deployer_data_owner",
        'try(module.document_storage[0].id, "")',
        "Storage Blob Data Owner",
        "module.document_storage[0].azurerm_storage_account.documents",
    ),
    RoleBinding(
        'module.llm_foundry_partner[0].azurerm_role_assignment.project_user["deployer"]',
        'try(module.llm_foundry_partner[0].project_id, "")',
        "Azure AI User",
        "module.llm_foundry_partner[0].azurerm_cognitive_account_project.partner",
    ),
    RoleBinding(
        'module.foundry_web_search[0].azurerm_role_assignment.project_user["deployer"]',
        'try(module.foundry_web_search[0].project_id, "")',
        "Azure AI User",
        "module.foundry_web_search[0].azurerm_cognitive_account_project.search",
    ),
    RoleBinding(
        "module.operational_history_storage[0].azurerm_role_assignment.deployer_data_owner",
        'try(module.operational_history_storage[0].id, "")',
        "Storage Blob Data Owner",
        "module.operational_history_storage[0].azurerm_storage_account.case_history",
    ),
    RoleBinding(
        "module.rule_catalog_snapshot_storage[0].azurerm_role_assignment.deployer_data_owner",
        'try(module.rule_catalog_snapshot_storage[0].id, "")',
        "Storage Blob Data Owner",
        "module.rule_catalog_snapshot_storage[0].azurerm_storage_account.case_history",
    ),
)


def _command(
    arguments: Sequence[str],
    *,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        check=True,
        capture_output=True,
        cwd=cwd,
        input=input_text,
        text=True,
        timeout=180,
    )


def _scope(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Terraform role scope output is empty")
    try:
        decoded = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ValueError("Terraform role scope output is invalid") from error
    if not isinstance(decoded, str):
        raise ValueError("Terraform role scope output must be a string")
    if decoded and not decoded.casefold().startswith("/subscriptions/"):
        raise ValueError("Terraform role scope is not an Azure resource id")
    return decoded


def _assignment_id(
    value: str,
    *,
    scope: str,
    role_name: str,
    principal_id: str,
) -> str | None:
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise ValueError("Azure role assignment response must be an array")
    if not payload:
        return None
    if len(payload) != 1 or not isinstance(payload[0], Mapping):
        raise ValueError("Stable deploy role adoption requires exactly one assignment")
    assignment = payload[0]
    if (
        str(assignment.get("scope", "")).casefold() != scope.casefold()
        or assignment.get("roleDefinitionName") != role_name
        or str(assignment.get("principalId", "")).casefold() != principal_id.casefold()
    ):
        raise ValueError("Azure role assignment does not match the requested binding")
    assignment_id = assignment.get("id")
    expected_prefix = f"{scope.rstrip('/')}/providers/Microsoft.Authorization/roleAssignments/"
    if (
        not isinstance(assignment_id, str)
        or not assignment_id.casefold().startswith(expected_prefix.casefold())
        or _GUID.fullmatch(assignment_id.rsplit("/", 1)[-1]) is None
    ):
        raise ValueError("Azure role assignment id is invalid")
    return assignment_id


def _tracked_assignment_ids(
    terraform_dir: Path,
    *,
    state_addresses: set[str],
) -> dict[str, str]:
    tracked: dict[str, str] = {}
    for address in sorted(state_addresses):
        if not (
            address.startswith("azurerm_role_assignment.") or ".azurerm_role_assignment." in address
        ):
            continue
        output = _command(
            ("terraform", "state", "show", "-no-color", address),
            cwd=terraform_dir,
        ).stdout
        match = _STATE_ID.search(output)
        if match is None:
            raise ValueError("Terraform role assignment state has no resource id")
        normalized = match.group(1).casefold()
        if normalized in tracked:
            raise ValueError("Terraform state tracks one role assignment at multiple addresses")
        tracked[normalized] = address
    return tracked


def reconcile(
    terraform_dir: Path,
    *,
    principal_id: str,
    bindings: Sequence[RoleBinding] = _ROLE_BINDINGS,
) -> tuple[str, ...]:
    """Import exact existing stable assignments into missing Terraform addresses."""

    if _GUID.fullmatch(principal_id) is None:
        raise ValueError("DEPLOY_RUNNER_PRINCIPAL_ID must be a GUID")
    state = set(_command(("terraform", "state", "list"), cwd=terraform_dir).stdout.splitlines())
    tracked_assignment_ids = _tracked_assignment_ids(
        terraform_dir,
        state_addresses=state,
    )
    adopted: list[str] = []
    for binding in bindings:
        if binding.address in state:
            continue
        scope = _scope(
            _command(
                ("terraform", "console"),
                cwd=terraform_dir,
                input_text=f"{binding.scope_expression}\n",
            ).stdout.strip()
        )
        if not scope:
            if binding.owner_state_address in state:
                raise ValueError(
                    "Stable deploy role owner remains in state but its scope is unavailable"
                )
            continue
        assignment_id = _assignment_id(
            _command(
                (
                    "az",
                    "role",
                    "assignment",
                    "list",
                    "--scope",
                    scope,
                    "--assignee-object-id",
                    principal_id,
                    "--role",
                    binding.role_name,
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                cwd=terraform_dir,
            ).stdout,
            scope=scope,
            role_name=binding.role_name,
            principal_id=principal_id,
        )
        if assignment_id is None:
            continue
        normalized_assignment_id = assignment_id.casefold()
        if normalized_assignment_id in tracked_assignment_ids:
            raise ValueError("Stable deploy role assignment is already tracked at another address")
        _command(
            ("terraform", "import", "-input=false", binding.address, assignment_id),
            cwd=terraform_dir,
        )
        state.add(binding.address)
        tracked_assignment_ids[normalized_assignment_id] = binding.address
        adopted.append(binding.address)
    return tuple(adopted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terraform-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        adopted = reconcile(
            args.terraform_dir,
            principal_id=os.environ.get("DEPLOY_RUNNER_PRINCIPAL_ID", ""),
        )
    except (subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Stable deploy role state reconciliation completed: {len(adopted)} adopted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

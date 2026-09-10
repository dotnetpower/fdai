#!/usr/bin/env python3
"""Compare Terraform-owned deploy roles with the stable principal's Azure roles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
RoleBinding = tuple[str, str, str, str]


def terraform_role_bindings(
    states: Iterable[object],
    *,
    principal_id: str,
) -> tuple[RoleBinding, ...]:
    """Extract exact role bindings owned by Terraform for one principal."""

    if _GUID.fullmatch(principal_id) is None:
        raise ValueError("deploy principal id must be a GUID")
    bindings: set[RoleBinding] = set()
    for state in states:
        if not isinstance(state, Mapping):
            raise ValueError("Terraform state JSON must be an object")
        values = state.get("values")
        if not isinstance(values, Mapping):
            raise ValueError("Terraform state JSON has no values object")
        root = values.get("root_module")
        if not isinstance(root, Mapping):
            raise ValueError("Terraform state JSON has no root module")
        for resource in _resources(root):
            if resource.get("type") != "azurerm_role_assignment":
                continue
            attributes = resource.get("values")
            if not isinstance(attributes, Mapping):
                raise ValueError("Terraform role assignment has no values")
            if str(attributes.get("principal_id", "")).casefold() != principal_id.casefold():
                continue
            bindings.add(_binding(attributes))
    return tuple(sorted(bindings))


def azure_role_bindings(assignments: object) -> tuple[RoleBinding, ...]:
    """Normalize Azure CLI role-assignment output."""

    if not isinstance(assignments, list) or not all(
        isinstance(item, Mapping) for item in assignments
    ):
        raise ValueError("Azure role assignments must be an array of objects")
    return tuple(sorted({_binding(item) for item in assignments}))


def verify_manifest(
    states: Iterable[object],
    *,
    principal_id: str,
    assignments: object,
) -> dict[str, object]:
    """Require Azure direct roles to equal the Terraform-owned role set."""

    expected = terraform_role_bindings(states, principal_id=principal_id)
    actual = azure_role_bindings(assignments)
    if expected != actual:
        raise ValueError("stable deploy identity role manifest drift detected")
    canonical = json.dumps(expected, separators=(",", ":")).encode()
    return {
        "schema_version": "fdai.deploy-identity-manifest-receipt.v1",
        "manifest_verified": True,
        "role_count": len(expected),
        "role_set_digest": hashlib.sha256(canonical).hexdigest(),
    }


def _resources(module: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    resources = module.get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("Terraform module resources must be an array")
    for resource in resources:
        if not isinstance(resource, Mapping):
            raise ValueError("Terraform resources must be objects")
        yield resource
    children = module.get("child_modules", [])
    if not isinstance(children, list):
        raise ValueError("Terraform child modules must be an array")
    for child in children:
        if not isinstance(child, Mapping):
            raise ValueError("Terraform child modules must be objects")
        yield from _resources(child)


def _binding(value: Mapping[str, object]) -> RoleBinding:
    scope = str(value.get("scope", "")).strip().casefold()
    role_definition_id = (
        str(value.get("role_definition_id", value.get("roleDefinitionId", ""))).strip().casefold()
    )
    condition = " ".join(str(value.get("condition", "") or "").split())
    condition_version = str(
        value.get("condition_version", value.get("conditionVersion", "")) or ""
    ).strip()
    if not scope or not role_definition_id:
        raise ValueError("role assignment scope and role definition id are required")
    return scope, role_definition_id, condition, condition_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, action="append", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    states = [json.loads(path.read_text(encoding="utf-8")) for path in args.state]
    completed = subprocess.run(
        [
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            args.principal_id,
            "--all",
            "--output",
            "json",
            "--only-show-errors",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        receipt = verify_manifest(
            states,
            principal_id=args.principal_id,
            assignments=json.loads(completed.stdout),
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Stable deploy identity role manifest verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

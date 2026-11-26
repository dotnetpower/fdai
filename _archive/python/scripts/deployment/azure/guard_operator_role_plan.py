#!/usr/bin/env python3
"""Guard the one reviewed Operator API role replacement in protected plans."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

ROLE_ADDRESS = (
    'module.llm_azure_openai[0].azurerm_role_assignment.additional_openai_user["operator_api"]'
)
IDENTITY_ADDRESS = "module.operator_api_identity[0].azurerm_user_assigned_identity.primary"
ROLE_DEFINITION_NAME = "Cognitive Services OpenAI User"


def validate_operator_role_replacement(plan: object) -> bool:
    """Accept only the exact role migration paired with a name-only UAMI replacement."""

    if not isinstance(plan, Mapping):
        raise ValueError("protected Terraform plan MUST be an object")
    raw_changes = plan.get("resource_changes")
    if not isinstance(raw_changes, list):
        raise ValueError("protected Terraform plan resource_changes MUST be an array")
    changes: list[Mapping[str, object]] = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, Mapping):
            raise ValueError("protected Terraform resource changes MUST be objects")
        changes.append(raw_change)
    role_changes = [change for change in changes if change.get("address") == ROLE_ADDRESS]
    if not role_changes:
        return False
    if len(role_changes) != 1:
        raise ValueError("protected plan has duplicate Operator API role replacements")

    changes_by_address: dict[str, Mapping[str, object]] = {}
    for change in changes:
        address = change.get("address")
        details = change.get("change")
        if not isinstance(address, str) or not isinstance(details, Mapping):
            continue
        if address in changes_by_address:
            raise ValueError("protected plan has duplicate resource addresses")
        changes_by_address[address] = change

    details = role_changes[0].get("change")
    if not isinstance(details, Mapping):
        raise ValueError("Operator API role replacement change is invalid")
    before = details.get("before")
    after = details.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ValueError("Operator API role replacement values are invalid")
    accepted = (
        tuple(details.get("actions", ())) == ("delete", "create")
        and details.get("replace_paths") == [["principal_id"]]
        and _nonempty(before.get("scope"))
        and before.get("scope") == after.get("scope")
        and before.get("role_definition_name")
        == after.get("role_definition_name")
        == ROLE_DEFINITION_NAME
        and _exact_operator_identity_replacement(changes_by_address.get(IDENTITY_ADDRESS))
    )
    if not accepted:
        raise ValueError("protected plan has an unapproved Operator API role replacement")
    return True


def filter_validated_operator_role_replacement(
    plan: object,
) -> tuple[dict[str, object], bool]:
    """Remove only the validated role change from the temporary review copy."""

    accepted = validate_operator_role_replacement(plan)
    if not isinstance(plan, Mapping):
        raise ValueError("protected Terraform plan MUST be an object")
    copied = dict(plan)
    if not accepted:
        return copied, False
    raw_changes = plan.get("resource_changes")
    if not isinstance(raw_changes, list):
        raise ValueError("protected Terraform plan resource_changes MUST be an array")
    validated_addresses = {ROLE_ADDRESS, IDENTITY_ADDRESS}
    copied["resource_changes"] = [
        change
        for change in raw_changes
        if not isinstance(change, Mapping) or change.get("address") not in validated_addresses
    ]
    return copied, True


def _exact_operator_identity_replacement(change: object) -> bool:
    if not isinstance(change, Mapping):
        return False
    details = change.get("change")
    if not isinstance(details, Mapping):
        return False
    before = details.get("before")
    after = details.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return False
    return (
        tuple(details.get("actions", ())) == ("delete", "create")
        and details.get("replace_paths") == [["name"]]
        and _nonempty(before.get("name"))
        and _nonempty(after.get("name"))
        and before.get("name") != after.get("name")
        and _nonempty(before.get("location"))
        and before.get("location") == after.get("location")
        and _nonempty(before.get("resource_group_name"))
        and before.get("resource_group_name") == after.get("resource_group_name")
        and before.get("tags") == after.get("tags")
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        filtered, accepted = filter_validated_operator_role_replacement(plan)
    except ValueError as error:
        print(f"Protected plans reject delete or replacement actions:\n- {ROLE_ADDRESS}")
        print(str(error))
        return 1
    if accepted:
        args.plan.write_text(
            json.dumps(filtered, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        print(f"Protected plan permits exact identity role replacement: {ROLE_ADDRESS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify that an A3-E evidence-target plan contains only the reviewed creates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAX_PLAN_BYTES = 8 * 1024 * 1024
EXPECTED_CREATES = frozenset(
    {
        "azurerm_linux_virtual_machine.target",
        "azurerm_network_interface.target",
        "azurerm_network_security_group.target",
        "azurerm_role_assignment.executor",
        "azurerm_role_assignment.observer",
        "azurerm_role_definition.executor",
        "azurerm_subnet.target",
        "azurerm_subnet_network_security_group_association.target",
        "azurerm_user_assigned_identity.executor",
        "azurerm_user_assigned_identity.observer",
        "azurerm_virtual_network.target",
        "terraform_data.deployment_context",
    }
)


class PlanVerificationError(ValueError):
    """Report a fail-closed plan-shape violation without exposing plan values."""


def _load_plan(path: Path) -> dict[str, Any]:
    """Load one bounded Terraform JSON plan from a regular file."""
    if not path.is_file() or path.is_symlink():
        raise PlanVerificationError("plan JSON must be a regular non-symlink file")
    if path.stat().st_size > MAX_PLAN_BYTES:
        raise PlanVerificationError("plan JSON exceeds the 8 MiB verification limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanVerificationError("plan JSON is unreadable or malformed") from exc
    if not isinstance(value, dict):
        raise PlanVerificationError("plan JSON root must be an object")
    return value


def verify_plan(plan: dict[str, Any]) -> None:
    """Require the exact reviewed create-only resource set."""
    resource_changes = plan.get("resource_changes")
    if not isinstance(resource_changes, list):
        raise PlanVerificationError("plan JSON must contain resource_changes")

    observed: set[str] = set()
    for item in resource_changes:
        if not isinstance(item, dict):
            raise PlanVerificationError("resource_changes entries must be objects")
        address = item.get("address")
        change = item.get("change")
        if not isinstance(address, str) or not isinstance(change, dict):
            raise PlanVerificationError("resource change identity is malformed")
        actions = change.get("actions")
        if actions == ["no-op"]:
            continue
        if address in observed:
            raise PlanVerificationError("plan contains a duplicate changed address")
        observed.add(address)
        if address not in EXPECTED_CREATES:
            raise PlanVerificationError("plan changes an unreviewed address")
        if actions != ["create"]:
            raise PlanVerificationError("reviewed addresses may contain only create actions")

    missing = EXPECTED_CREATES - observed
    if missing:
        raise PlanVerificationError("plan omits one or more required create addresses")


def main(argv: list[str] | None = None) -> int:
    """Validate one Terraform JSON plan and emit a value-free summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path)
    args = parser.parse_args(argv)
    try:
        verify_plan(_load_plan(args.plan_json))
    except PlanVerificationError as exc:
        print(f"A3E_EVIDENCE_PLAN_BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print(f"A3E_EVIDENCE_PLAN_OK create={len(EXPECTED_CREATES)} update=0 delete=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

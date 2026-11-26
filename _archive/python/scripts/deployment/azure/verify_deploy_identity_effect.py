#!/usr/bin/env python3
"""Verify stable deploy-role effects against Azure after exact Terraform apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from scripts.deployment.azure.guard_deploy_identity_plan import validate_plan

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def expected_role_effects(
    plan: object,
    *,
    expected_principal_id: str,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Return expected stable roles and superseded principals from a valid plan."""

    validate_plan(plan, expected_principal_id=expected_principal_id)
    if not isinstance(plan, Mapping):
        raise ValueError("deploy identity plan MUST be an object")
    raw_changes = plan["resource_changes"]
    if not isinstance(raw_changes, list):
        raise ValueError("deploy identity plan resource_changes MUST be an array")
    expected: set[tuple[str, str]] = set()
    retired: set[str] = set()
    for raw_change in raw_changes:
        if not isinstance(raw_change, Mapping):
            continue
        details = raw_change.get("change")
        if not isinstance(details, Mapping):
            continue
        after = details.get("after")
        before = details.get("before")
        if isinstance(after, Mapping) and (
            str(after.get("principal_id", "")).casefold() == expected_principal_id.casefold()
        ):
            scope = after.get("scope")
            role = after.get("role_definition_name")
            if isinstance(scope, str) and isinstance(role, str):
                expected.add((scope.casefold(), role))
        if isinstance(before, Mapping):
            principal = str(before.get("principal_id", ""))
            if (
                _GUID.fullmatch(principal) is not None
                and principal.casefold() != expected_principal_id.casefold()
            ):
                retired.add(principal.casefold())
    return tuple(sorted(expected)), tuple(sorted(retired))


def verify_live_effect(
    plan: object,
    *,
    expected_principal_id: str,
) -> dict[str, object]:
    """Require every planned role and zero remaining retired-principal roles."""

    expected, retired = expected_role_effects(
        plan,
        expected_principal_id=expected_principal_id,
    )
    stable_assignments = _role_assignments(expected_principal_id)
    actual = {
        (str(item.get("scope", "")).casefold(), str(item.get("roleDefinitionName", "")))
        for item in stable_assignments
    }
    missing = sorted(set(expected).difference(actual))
    if missing:
        raise ValueError("stable deploy principal is missing planned role assignments")
    for principal_id in retired:
        if _role_assignments(principal_id):
            raise ValueError("superseded deploy principal retains role assignments")

    canonical = json.dumps(
        {"expected": expected, "retired_count": len(retired)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return {
        "schema_version": "fdai.deploy-identity-effect-receipt.v1",
        "effect_verified": True,
        "expected_role_count": len(expected),
        "retired_principal_count": len(retired),
        "retired_assignment_count": 0,
        "role_set_digest": hashlib.sha256(canonical).hexdigest(),
    }


def _role_assignments(principal_id: str) -> list[Mapping[str, object]]:
    completed = subprocess.run(
        [
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            principal_id,
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
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
        raise ValueError("Azure role assignment readback is invalid")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        receipt = verify_live_effect(plan, expected_principal_id=args.principal_id)
    except (subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Stable deploy identity effect verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

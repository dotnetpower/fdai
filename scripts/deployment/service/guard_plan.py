#!/usr/bin/env python3
"""Reject unsafe or cross-service actions in a service Terraform plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from service_contract import ServiceContractError, resolve_service


class PlanGuardError(ValueError):
    """Raised when a Terraform plan exceeds one service's resource boundary."""


def _actions(change: Any, *, address: str) -> tuple[str, ...]:
    if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
        raise PlanGuardError(f"plan change for {address} has no action list")
    actions = tuple(change["actions"])
    if not all(isinstance(action, str) for action in actions):
        raise PlanGuardError(f"plan change for {address} has an invalid action")
    return actions


def _planned_image(change: dict[str, Any], *, address: str) -> str:
    after = change.get("after")
    if not isinstance(after, dict):
        raise PlanGuardError(f"plan change for {address} has no planned resource")
    templates = after.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise PlanGuardError(f"plan change for {address} has an invalid template")
    containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise PlanGuardError(f"plan change for {address} must contain exactly one container")
    image = containers[0].get("image") if isinstance(containers[0], dict) else None
    if not isinstance(image, str) or not image:
        raise PlanGuardError(f"plan change for {address} has no container image")
    return image


def validate_plan(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    image_ref: str,
) -> None:
    """Allow only bounded actions that deploy the exact attested service image."""
    contract = resolve_service(service, environment)
    resource_changes = payload.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise PlanGuardError("Terraform plan resource_changes must be an array")
    violations: list[str] = []
    for entry in resource_changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise PlanGuardError("Terraform plan contains an invalid resource change")
        address = entry["address"]
        change = entry.get("change")
        actions = _actions(change, address=address)
        if actions == ("no-op",):
            continue
        if address != contract.allowed_resource_address:
            violations.append(f"cross-service or platform action {actions!r} at {address}")
            continue
        if "delete" in actions:
            violations.append(f"delete or replacement action {actions!r} at {address}")
            continue
        if actions not in {("create",), ("update",)}:
            violations.append(f"unsupported action {actions!r} at {address}")
            continue
        if not isinstance(change, dict) or _planned_image(change, address=address) != image_ref:
            violations.append(f"planned image at {address} does not match the attested image")
    deferred_changes = payload.get("deferred_changes", [])
    if deferred_changes not in (None, []):
        violations.append("deferred plan changes are not eligible for protected apply")
    if violations:
        raise PlanGuardError("; ".join(violations))


def main() -> int:
    """Validate a Terraform JSON plan from the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--image-ref", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.plan_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PlanGuardError("Terraform plan must contain a JSON object")
        validate_plan(
            payload,
            service=args.service,
            environment=args.environment,
            image_ref=args.image_ref,
        )
    except (OSError, json.JSONDecodeError, ServiceContractError, PlanGuardError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

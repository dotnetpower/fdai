#!/usr/bin/env python3
"""Reject unsafe or cross-service actions in a service Terraform plan."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from service_contract import ServiceContract, ServiceContractError, resolve_service


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
    image = _container(_resource(change, side="after", address=address), address=address).get(
        "image"
    )
    if not isinstance(image, str):
        raise PlanGuardError(f"resource at {address} has no container image")
    return image


def _resource(change: dict[str, Any], *, side: str, address: str) -> dict[str, Any]:
    resource = change.get(side)
    if not isinstance(resource, dict):
        raise PlanGuardError(f"plan change for {address} has no {side} resource")
    return resource


def _container(resource: dict[str, Any], *, address: str) -> dict[str, Any]:
    templates = resource.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise PlanGuardError(f"resource at {address} has an invalid template")
    containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise PlanGuardError(f"resource at {address} must contain exactly one container")
    container = containers[0]
    if not isinstance(container, dict):
        raise PlanGuardError(f"resource at {address} has an invalid container")
    image = container.get("image")
    if not isinstance(image, str) or not image:
        raise PlanGuardError(f"resource at {address} has no container image")
    return container


def _identity_ids(resource: dict[str, Any], *, address: str) -> frozenset[str]:
    identities = resource.get("identity")
    if not isinstance(identities, list) or len(identities) != 1:
        raise PlanGuardError(f"resource at {address} must contain one identity block")
    identity = identities[0]
    raw_ids = identity.get("identity_ids") if isinstance(identity, dict) else None
    if (
        not isinstance(raw_ids, list)
        or not raw_ids
        or not all(isinstance(identity_id, str) and identity_id for identity_id in raw_ids)
    ):
        raise PlanGuardError(f"resource at {address} has invalid workload identities")
    return frozenset(raw_ids)


def _runtime_contract(resource: dict[str, Any], *, address: str) -> dict[str, Any]:
    container = _container(resource, address=address)
    return {key: container.get(key) for key in ("name", "command", "args", "env")}


def _authority_cutover(resource: dict[str, Any], *, address: str) -> str | None:
    environment = _container(resource, address=address).get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    values = {
        item.get("name"): item.get("value")
        for item in environment
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    value = values.get("FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER")
    return value if isinstance(value, str) else None


def _resource_ids(value: Any) -> frozenset[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and item.lower().startswith("/subscriptions/"):
            found.add(item.lower())

    visit(value)
    return frozenset(found)


def _guard_update(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
) -> list[str]:
    violations: list[str] = []
    for field in ("name", "resource_group_name"):
        if before.get(field) != after.get(field):
            violations.append(f"target resource identity drift at {address}: {field}")
    if before.get("container_app_environment_id") != after.get("container_app_environment_id"):
        violations.append(f"platform or peer resource identity drift at {address}")

    before_identities = _identity_ids(before, address=address)
    after_identities = _identity_ids(after, address=address)
    if after_identities > before_identities:
        violations.append(f"identity expansion at {address}")
    elif after_identities != before_identities:
        violations.append(f"workload identity drift at {address}")

    if _authority_cutover(before, address=address) != _authority_cutover(after, address=address):
        violations.append(f"authority cutover change at {address}")
    elif _runtime_contract(before, address=address) != _runtime_contract(after, address=address):
        violations.append(f"command or environment drift at {address}")

    if _resource_ids(before) != _resource_ids(after):
        violations.append(f"platform or peer resource identity drift at {address}")
    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if isinstance(before_tags, dict) and isinstance(after_tags, dict):
        if before_tags.get("fdai:authority-cutover") != after_tags.get("fdai:authority-cutover"):
            violations.append(f"authority cutover tag change at {address}")
    image_only_before = copy.deepcopy(before)
    _container(image_only_before, address=address)["image"] = _planned_image(
        {"after": after}, address=address
    )
    if image_only_before != after:
        violations.append(f"protected update changes fields rollback cannot prove at {address}")
    return violations


def _guard_service_runtime(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    container = _container(resource, address=address)
    violations: list[str] = []
    if container.get("command") != [contract.entrypoint] or container.get("args") not in ([], None):
        violations.append(f"planned command does not match the service entrypoint at {address}")
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    names = [item.get("name") for item in environment if isinstance(item, dict)]
    if len(names) != len(environment) or not all(isinstance(name, str) for name in names):
        raise PlanGuardError(f"resource at {address} has an invalid environment entry")
    if len(set(names)) != len(names):
        violations.append(f"planned environment contains duplicate names at {address}")
    missing = sorted(set(contract.required_environment) - set(names))
    if missing:
        violations.append(
            f"planned environment is missing required service names at {address}: {missing!r}"
        )
    tags = resource.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != contract.service:
        violations.append(f"planned component tag does not match the selected service at {address}")
    return violations


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
    resource_drift = payload.get("resource_drift", [])
    if resource_drift not in (None, []):
        violations.append("platform or peer resource drift is not eligible for protected apply")
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
        if actions == ("create",):
            violations.append(f"service creation has no automatic recovery at {address}")
            continue
        if actions != ("update",):
            violations.append(f"unsupported action {actions!r} at {address}")
            continue
        if not isinstance(change, dict) or _planned_image(change, address=address) != image_ref:
            violations.append(f"planned image at {address} does not match the attested image")
            continue
        after = _resource(change, side="after", address=address)
        _identity_ids(after, address=address)
        violations.extend(_guard_service_runtime(after, address=address, contract=contract))
        before = _resource(change, side="before", address=address)
        violations.extend(_guard_update(before, after, address=address))
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

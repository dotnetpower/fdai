#!/usr/bin/env python3
"""Reject unsafe or cross-service actions in a service Terraform plan."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

from service_contract import ServiceContract, ServiceContractError, resolve_service


class PlanGuardError(ValueError):
    """Raised when a Terraform plan exceeds one service's resource boundary."""


_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_ALLOWED_SIDECARS = {
    "document-processing-worker": frozenset({"clamav"}),
}


def _actions(change: Any, *, address: str) -> tuple[str, ...]:
    if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
        raise PlanGuardError(f"plan change for {address} has no action list")
    actions = tuple(change["actions"])
    if not all(isinstance(action, str) for action in actions):
        raise PlanGuardError(f"plan change for {address} has an invalid action")
    return actions


def _planned_image(
    change: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> str:
    image = _primary_container(
        _resource(change, side="after", address=address),
        address=address,
        contract=contract,
    ).get("image")
    if not isinstance(image, str):
        raise PlanGuardError(f"resource at {address} has no container image")
    return image


def _resource(change: dict[str, Any], *, side: str, address: str) -> dict[str, Any]:
    resource = change.get(side)
    if not isinstance(resource, dict):
        raise PlanGuardError(f"plan change for {address} has no {side} resource")
    return resource


def _containers(resource: dict[str, Any], *, address: str) -> dict[str, dict[str, Any]]:
    templates = resource.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise PlanGuardError(f"resource at {address} has an invalid template")
    containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(containers, list) or not containers:
        raise PlanGuardError(f"resource at {address} has no containers")
    result: dict[str, dict[str, Any]] = {}
    for container in containers:
        if not isinstance(container, dict):
            raise PlanGuardError(f"resource at {address} has an invalid container")
        name = container.get("name")
        image = container.get("image")
        if not isinstance(name, str) or not name or name in result:
            raise PlanGuardError(f"resource at {address} has invalid container names")
        if not isinstance(image, str) or not image:
            raise PlanGuardError(f"container {name} at {address} has no image")
        result[name] = container
    return result


def _container_layout(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    containers = _containers(resource, address=address)
    expected_sidecars = _ALLOWED_SIDECARS.get(contract.service, frozenset())
    primary_names = set(containers) - expected_sidecars
    if len(primary_names) != 1 or set(containers) != primary_names | expected_sidecars:
        raise PlanGuardError(
            f"resource at {address} must contain one primary and the exact allowed sidecar set"
        )
    primary = containers[primary_names.pop()]
    sidecars = {name: containers[name] for name in expected_sidecars}
    return primary, sidecars


def _primary_container(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    primary, _ = _container_layout(resource, address=address, contract=contract)
    return primary


def _guard_sidecars(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    _, sidecars = _container_layout(resource, address=address, contract=contract)
    violations: list[str] = []
    for name, sidecar in sidecars.items():
        image = sidecar.get("image")
        if not isinstance(image, str) or _DIGEST_IMAGE.fullmatch(image) is None:
            violations.append(f"sidecar {name} image is not immutable at {address}")
        probes: dict[str, dict[str, Any]] = {}
        for probe_name in ("startup_probe", "liveness_probe", "readiness_probe"):
            raw_probe = sidecar.get(probe_name)
            if (
                not isinstance(raw_probe, list)
                or len(raw_probe) != 1
                or not isinstance(raw_probe[0], dict)
            ):
                violations.append(f"sidecar {name} has invalid {probe_name} at {address}")
                continue
            probes[probe_name] = raw_probe[0]
        if len(probes) != 3:
            continue
        ports = {probe.get("port") for probe in probes.values()}
        if (
            len(ports) != 1
            or not all(
                isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536
                for port in ports
            )
            or not all(probe.get("transport") == "TCP" for probe in probes.values())
            or probes["startup_probe"].get("failure_count_threshold") != 30
        ):
            violations.append(f"sidecar {name} probe contract changed at {address}")
    return violations


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


def _runtime_contract(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    container = _primary_container(resource, address=address, contract=contract)
    return {key: container.get(key) for key in ("name", "command", "args", "env")}


def _authority_cutover(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> str | None:
    environment = _primary_container(resource, address=address, contract=contract).get("env")
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


def _secret_ids(resource: dict[str, Any]) -> frozenset[str]:
    raw_secrets = resource.get("secret", [])
    if not isinstance(raw_secrets, list):
        raise PlanGuardError("service secret contract is invalid")
    return frozenset(
        secret_id
        for secret in raw_secrets
        if isinstance(secret, dict)
        and isinstance((secret_id := secret.get("key_vault_secret_id")), str)
        and secret_id
    )


def _guard_initial_cutover(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    violations: list[str] = []
    before_primary, _ = _container_layout(before, address=address, contract=contract)
    after_primary, _ = _container_layout(after, address=address, contract=contract)
    before_image = before_primary.get("image")
    if not isinstance(before_image, str) or _DIGEST_IMAGE.fullmatch(before_image) is None:
        violations.append(f"initial cutover rollback image is not immutable at {address}")
    if _runtime_contract(before, address=address, contract=contract) == _runtime_contract(
        after, address=address, contract=contract
    ):
        violations.append(f"initial cutover has no legacy runtime transition at {address}")

    before_resources = {
        key: before_primary.get(key) for key in ("cpu", "memory", "ephemeral_storage")
    }
    after_resources = {
        key: after_primary.get(key) for key in ("cpu", "memory", "ephemeral_storage")
    }
    if before_resources != after_resources:
        violations.append(f"initial cutover changes service resource limits at {address}")

    before_secret_ids = _secret_ids(before)
    after_secret_ids = _secret_ids(after)
    if not after_secret_ids or not after_secret_ids <= before_secret_ids:
        violations.append(f"initial cutover adds an unbound secret at {address}")

    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if not isinstance(before_tags, dict) or not isinstance(after_tags, dict):
        violations.append(f"initial cutover tags are invalid at {address}")
    else:
        allowed_tag_changes = {"fdai:component", "fdai:rollback-strategy"}
        changed_tags = {
            key
            for key in set(before_tags) | set(after_tags)
            if before_tags.get(key) != after_tags.get(key)
        }
        if not changed_tags <= allowed_tag_changes:
            violations.append(f"initial cutover changes unapproved tags at {address}")
        if after_tags.get("fdai:component") != contract.service:
            violations.append(f"initial cutover component tag is invalid at {address}")
        if after_tags.get("fdai:rollback-strategy") not in {
            "previous-revision",
            "image-redeploy",
        }:
            violations.append(f"initial cutover rollback tag is invalid at {address}")

    expected = copy.deepcopy(before)
    expected["tags"] = copy.deepcopy(after.get("tags"))
    expected["secret"] = copy.deepcopy(after.get("secret"))
    expected_primary = _primary_container(expected, address=address, contract=contract)
    expected_primary.clear()
    expected_primary.update(copy.deepcopy(after_primary))
    if expected != after:
        violations.append(
            f"initial cutover changes fields outside its rollback boundary at {address}"
        )
    return violations


def _guard_update(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    initial_cutover: bool,
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

    before_authority = _authority_cutover(before, address=address, contract=contract)
    after_authority = _authority_cutover(after, address=address, contract=contract)
    authority_removed_from_core = (
        initial_cutover
        and contract.service == "core-control-plane"
        and before_authority == "1"
        and after_authority is None
    )
    if before_authority != after_authority and not authority_removed_from_core:
        violations.append(f"authority cutover change at {address}")
    elif not initial_cutover and _runtime_contract(
        before, address=address, contract=contract
    ) != _runtime_contract(after, address=address, contract=contract):
        violations.append(f"command or environment drift at {address}")

    if _resource_ids(before) != _resource_ids(after):
        violations.append(f"platform or peer resource identity drift at {address}")
    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if isinstance(before_tags, dict) and isinstance(after_tags, dict):
        if before_tags.get("fdai:authority-cutover") != after_tags.get("fdai:authority-cutover"):
            violations.append(f"authority cutover tag change at {address}")
    _, before_sidecars = _container_layout(before, address=address, contract=contract)
    _, after_sidecars = _container_layout(after, address=address, contract=contract)
    if before_sidecars != after_sidecars:
        violations.append(f"sidecar contract drift at {address}")
    if initial_cutover:
        violations.extend(_guard_initial_cutover(before, after, address=address, contract=contract))
        return violations
    image_only_before = copy.deepcopy(before)
    _primary_container(image_only_before, address=address, contract=contract)["image"] = (
        _planned_image({"after": after}, address=address, contract=contract)
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
    container = _primary_container(resource, address=address, contract=contract)
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
    violations.extend(_guard_sidecars(resource, address=address, contract=contract))
    return violations


def validate_plan(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    image_ref: str,
    initial_cutover: bool = False,
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
        if (
            not isinstance(change, dict)
            or _planned_image(change, address=address, contract=contract) != image_ref
        ):
            violations.append(f"planned image at {address} does not match the attested image")
            continue
        after = _resource(change, side="after", address=address)
        _identity_ids(after, address=address)
        violations.extend(_guard_service_runtime(after, address=address, contract=contract))
        before = _resource(change, side="before", address=address)
        violations.extend(
            _guard_update(
                before,
                after,
                address=address,
                contract=contract,
                initial_cutover=initial_cutover,
            )
        )
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
    parser.add_argument("--initial-cutover", action="store_true")
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
            initial_cutover=args.initial_cutover,
        )
    except (OSError, json.JSONDecodeError, ServiceContractError, PlanGuardError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

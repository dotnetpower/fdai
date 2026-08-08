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


def _difference_paths(before: Any, after: Any, *, path: str = "$") -> list[str]:
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            nested = f"{path}.{key}"
            if key not in before or key not in after:
                paths.append(nested)
            else:
                paths.extend(_difference_paths(before[key], after[key], path=nested))
        return paths
    if isinstance(before, list):
        paths = [path] if len(before) != len(after) else []
        for index, (left, right) in enumerate(zip(before, after, strict=False)):
            paths.extend(_difference_paths(left, right, path=f"{path}[{index}]"))
        return paths
    return [] if before == after else [path]


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
    before_primary, before_sidecars = _container_layout(before, address=address, contract=contract)
    after_primary, after_sidecars = _container_layout(after, address=address, contract=contract)
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

    for name, after_sidecar in after_sidecars.items():
        before_sidecar = before_sidecars[name]
        if before_sidecar.get("image") != after_sidecar.get("image"):
            violations.append(f"initial cutover changes sidecar {name} image at {address}")
        probe_fields = {"startup_probe", "liveness_probe", "readiness_probe"}
        before_config = {
            key: value for key, value in before_sidecar.items() if key not in probe_fields
        }
        after_config = {
            key: value for key, value in after_sidecar.items() if key not in probe_fields
        }
        if before_config != after_config:
            violations.append(f"initial cutover changes sidecar {name} config at {address}")

    before_secret_ids = _secret_ids(before)
    after_secret_ids = _secret_ids(after)
    if not after_secret_ids or not after_secret_ids <= before_secret_ids:
        violations.append(f"initial cutover adds an unbound secret at {address}")

    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if not isinstance(before_tags, dict) or not isinstance(after_tags, dict):
        violations.append(f"initial cutover tags are invalid at {address}")
    else:
        allowed_tag_changes = {
            "fdai:component",
            "fdai:rollback-strategy",
            "fdai:authority-cutover",
        }
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
    expected_containers = _containers(expected, address=address)
    for name, sidecar in after_sidecars.items():
        expected_containers[name].clear()
        expected_containers[name].update(copy.deepcopy(sidecar))
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

    before_resource_ids = _resource_ids(before)
    after_resource_ids = _resource_ids(after)
    if initial_cutover and after_resource_ids <= before_resource_ids:
        pass
    elif before_resource_ids != after_resource_ids:
        violations.append(f"platform or peer resource identity drift at {address}")
    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if isinstance(before_tags, dict) and isinstance(after_tags, dict):
        before_authority_tag = before_tags.get("fdai:authority-cutover")
        after_authority_tag = after_tags.get("fdai:authority-cutover")
        aligned_executor_tag = (
            initial_cutover
            and contract.service == "isolated-executor"
            and before_authority == after_authority == "1"
            and before_authority_tag in (None, "true")
            and after_authority_tag == "true"
        )
        if before_authority_tag != after_authority_tag and not aligned_executor_tag:
            violations.append(f"authority cutover tag change at {address}")
    _, before_sidecars = _container_layout(before, address=address, contract=contract)
    _, after_sidecars = _container_layout(after, address=address, contract=contract)
    if before_sidecars != after_sidecars and not initial_cutover:
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


def _guard_initial_worker_drift(
    resource_drift: Any,
    *,
    contract: ServiceContract,
    planned_resource: dict[str, Any],
) -> bool:
    if contract.service != "document-processing-worker":
        return False
    if not isinstance(resource_drift, list) or len(resource_drift) != 1:
        return False
    entry = resource_drift[0]
    if not isinstance(entry, dict) or entry.get("address") != contract.allowed_resource_address:
        return False
    change = entry.get("change")
    if not isinstance(change, dict) or change.get("actions") != ["update"]:
        return False
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    revision_only = copy.deepcopy(before)
    revision_only["latest_revision_name"] = after.get("latest_revision_name")
    if revision_only == after:
        return True
    try:
        before_primary, before_sidecars = _container_layout(
            before,
            address=contract.allowed_resource_address,
            contract=contract,
        )
        after_primary, after_sidecars = _container_layout(
            after,
            address=contract.allowed_resource_address,
            contract=contract,
        )
        _, planned_sidecars = _container_layout(
            planned_resource,
            address=contract.allowed_resource_address,
            contract=contract,
        )
    except PlanGuardError:
        return False
    if before_primary != after_primary:
        return False
    before_sidecar = before_sidecars.get("clamav")
    after_sidecar = after_sidecars.get("clamav")
    planned_sidecar = planned_sidecars.get("clamav")
    if (
        before_sidecar is None
        or after_sidecar is None
        or planned_sidecar is None
        or before_sidecar.get("image") != "clamav/clamav:stable"
        or not isinstance(after_sidecar.get("image"), str)
        or _DIGEST_IMAGE.fullmatch(after_sidecar["image"]) is None
        or after_sidecar.get("image") != planned_sidecar.get("image")
    ):
        return False
    expected = copy.deepcopy(before)
    expected["latest_revision_name"] = after.get("latest_revision_name")
    expected_templates = expected.get("template")
    after_templates = after.get("template")
    if (
        isinstance(expected_templates, list)
        and len(expected_templates) == 1
        and isinstance(expected_templates[0], dict)
        and isinstance(after_templates, list)
        and len(after_templates) == 1
        and isinstance(after_templates[0], dict)
    ):
        expected_templates[0]["revision_suffix"] = after_templates[0].get("revision_suffix")
    expected_sidecars = _container_layout(
        expected,
        address=contract.allowed_resource_address,
        contract=contract,
    )[1]
    expected_sidecars["clamav"]["image"] = after_sidecar["image"]
    return expected == after


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
    selected_after: dict[str, Any] | None = None
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
        selected_after = after
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
    resource_drift = payload.get("resource_drift", [])
    allowed_worker_drift = (
        initial_cutover
        and selected_after is not None
        and _guard_initial_worker_drift(
            resource_drift,
            contract=contract,
            planned_resource=selected_after,
        )
    )
    if resource_drift not in (None, []) and not allowed_worker_drift:
        drift_paths: list[str] = []
        if isinstance(resource_drift, list) and len(resource_drift) == 1:
            drift_change = resource_drift[0].get("change")
            if isinstance(drift_change, dict):
                drift_paths = _difference_paths(
                    drift_change.get("before"), drift_change.get("after")
                )
        suffix = f": {drift_paths!r}" if drift_paths else ""
        violations.append(
            f"platform or peer resource drift is not eligible for protected apply{suffix}"
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

#!/usr/bin/env python3
"""Structural decoding primitives for the independent-service plan guard."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from service_contract import ServiceContract


class PlanGuardError(ValueError):
    """Raised when a Terraform plan exceeds one service's resource boundary."""


_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_ALLOWED_SIDECARS = {
    "document-processing-worker": frozenset({"clamav"}),
}
_MAX_PLAN_NESTING_DEPTH = 64


def difference_paths(
    before: Any,
    after: Any,
    *,
    path: str = "$",
    _depth: int = 0,
) -> list[str]:
    """Return deterministic leaf paths whose values or shapes differ."""
    if _depth > _MAX_PLAN_NESTING_DEPTH:
        raise PlanGuardError("Terraform plan nesting exceeds the validation limit")
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            nested = f"{path}.{key}"
            if key not in before or key not in after:
                paths.append(nested)
            else:
                paths.extend(
                    difference_paths(
                        before[key],
                        after[key],
                        path=nested,
                        _depth=_depth + 1,
                    )
                )
        return paths
    if isinstance(before, list):
        paths = [path] if len(before) != len(after) else []
        for index, (left, right) in enumerate(zip(before, after, strict=False)):
            paths.extend(
                difference_paths(
                    left,
                    right,
                    path=f"{path}[{index}]",
                    _depth=_depth + 1,
                )
            )
        return paths
    return [] if before == after else [path]


def bounded_string_array(value: object, *, maximum: int = 32) -> tuple[str, ...] | None:
    """Decode one bounded unique JSON string array or return no value."""
    if not isinstance(value, str):
        return None
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(loaded, list)
        or not 1 <= len(loaded) <= maximum
        or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in loaded)
        or len(loaded) != len(set(loaded))
    ):
        return None
    return tuple(loaded)


def actions(change: Any, *, address: str) -> tuple[str, ...]:
    """Decode one Terraform change action list without accepting non-string actions."""
    if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
        raise PlanGuardError(f"plan change for {address} has no action list")
    result = tuple(change["actions"])
    if not all(isinstance(action, str) for action in result):
        raise PlanGuardError(f"plan change for {address} has an invalid action")
    return result


def planned_image(
    change: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> str:
    """Return the planned primary container image for one service resource."""
    image = primary_container(
        resource(change, side="after", address=address),
        address=address,
        contract=contract,
    ).get("image")
    if not isinstance(image, str):
        raise PlanGuardError(f"resource at {address} has no container image")
    return image


def resource(change: dict[str, Any], *, side: str, address: str) -> dict[str, Any]:
    """Return one typed before or after resource from a Terraform change."""
    selected = change.get(side)
    if not isinstance(selected, dict):
        raise PlanGuardError(f"plan change for {address} has no {side} resource")
    return selected


def containers(resource_value: dict[str, Any], *, address: str) -> dict[str, dict[str, Any]]:
    """Index one Container App template by unique non-empty container name."""
    templates = resource_value.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise PlanGuardError(f"resource at {address} has an invalid template")
    raw_containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(raw_containers, list) or not raw_containers:
        raise PlanGuardError(f"resource at {address} has no containers")
    result: dict[str, dict[str, Any]] = {}
    for container in raw_containers:
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


def container_layout(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Separate one primary container from the exact allowlisted sidecar set."""
    indexed = containers(resource_value, address=address)
    expected_sidecars = _ALLOWED_SIDECARS.get(contract.service, frozenset())
    primary_names = set(indexed) - expected_sidecars
    if len(primary_names) != 1 or set(indexed) != primary_names | expected_sidecars:
        raise PlanGuardError(
            f"resource at {address} must contain one primary and the exact allowed sidecar set"
        )
    primary = indexed[primary_names.pop()]
    sidecars = {name: indexed[name] for name in expected_sidecars}
    return primary, sidecars


def primary_container(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    """Return the sole primary container from a validated layout."""
    primary, _ = container_layout(resource_value, address=address, contract=contract)
    return primary


def guard_sidecars(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    """Return immutable-image and probe-contract violations for allowlisted sidecars."""
    _, sidecars = container_layout(resource_value, address=address, contract=contract)
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


def identity_ids(resource_value: dict[str, Any], *, address: str) -> frozenset[str]:
    """Return the non-empty workload identity set from one exact identity block."""
    identities = resource_value.get("identity")
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


def runtime_contract(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    """Project the order-sensitive primary runtime contract."""
    container = primary_container(resource_value, address=address, contract=contract)
    return {key: container.get(key) for key in ("name", "command", "args", "env")}


def runtime_contract_by_name(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    """Project the primary runtime contract with environment bindings keyed by name."""
    container = primary_container(resource_value, address=address, contract=contract)
    environment = environment_by_name(container, address=address)
    return {
        "name": container.get("name"),
        "command": container.get("command"),
        "args": container.get("args"),
        "env": {name: environment_binding(item) for name, item in sorted(environment.items())},
    }


def runtime_contract_drift_names(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> tuple[str, ...]:
    """Return primary runtime fields whose normalized values changed."""
    before_runtime = runtime_contract_by_name(before, address=address, contract=contract)
    after_runtime = runtime_contract_by_name(after, address=address, contract=contract)
    changed = [
        key for key in ("name", "command", "args") if before_runtime[key] != after_runtime[key]
    ]
    before_environment = before_runtime["env"]
    after_environment = after_runtime["env"]
    if not isinstance(before_environment, dict) or not isinstance(after_environment, dict):
        raise PlanGuardError(f"resource at {address} has an invalid normalized environment")
    changed.extend(
        f"env:{name}"
        for name in sorted(set(before_environment) | set(after_environment))
        if before_environment.get(name) != after_environment.get(name)
    )
    return tuple(changed)


def sort_primary_environment(
    resource_value: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    """Return a deep-copied resource with deterministic primary environment ordering."""
    normalized = copy.deepcopy(resource_value)
    container = primary_container(normalized, address=address, contract=contract)
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    container["env"] = sorted(
        environment,
        key=lambda item: str(item.get("name")) if isinstance(item, dict) else "",
    )
    return normalized


def environment_by_name(container: dict[str, Any], *, address: str) -> dict[str, dict[str, Any]]:
    """Index unique non-empty environment bindings by variable name."""
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    result: dict[str, dict[str, Any]] = {}
    for item in environment:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or name in result:
            raise PlanGuardError(f"resource at {address} has invalid environment names")
        result[name] = item
    return result


def environment_binding(item: dict[str, Any] | None) -> tuple[Any, Any] | None:
    """Normalize one plain or secret-backed environment binding."""
    if item is None:
        return None
    secret_name = item.get("secret_name")
    normalized_secret = None if secret_name in (None, "") else secret_name
    return (
        None if normalized_secret is not None else item.get("value"),
        normalized_secret,
    )

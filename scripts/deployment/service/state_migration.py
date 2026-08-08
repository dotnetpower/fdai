#!/usr/bin/env python3
"""Validate independent-service Terraform state migration and legacy cutover fences."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from service_contract import ServiceContractError, resolve_service

_MANIFEST = Path(__file__).resolve().parents[3] / "infra" / "services" / "state-migration.json"


class StateMigrationError(ValueError):
    """Raised when state ownership is missing, duplicated, or recreatable."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StateMigrationError(f"{path.name} must contain a JSON object")
    return value


def migration_coordinates(service: str, environment: str) -> tuple[str, str, str, str]:
    """Return source key, destination key, source address, and destination address."""
    contract = resolve_service(service, environment)
    manifest = _object(_MANIFEST)
    raw = manifest.get("services", {}).get(service)
    if not isinstance(raw, dict):
        raise StateMigrationError("state migration manifest has no selected service")
    moves = raw.get("moves")
    if not isinstance(moves, list) or len(moves) != 1 or not isinstance(moves[0], dict):
        raise StateMigrationError("selected service must have exactly one state move")
    source_key_template = raw.get("source_backend_key_template")
    if not isinstance(source_key_template, str):
        raise StateMigrationError("selected service has no source backend key template")
    source = moves[0].get("from")
    destination = moves[0].get("to")
    if not isinstance(source, str) or not isinstance(destination, str):
        raise StateMigrationError("selected service state move is invalid")
    if destination != contract.allowed_resource_address:
        raise StateMigrationError("state move destination disagrees with service contract")
    return (
        source_key_template.format(environment=environment),
        contract.backend_key,
        source,
        destination,
    )


def _managed_resources(state: dict[str, Any]) -> list[tuple[str, str | None]]:
    values = state.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if root is None:
        return _raw_managed_resources(state)
    found: list[tuple[str, str | None]] = []

    def walk(module: Any) -> None:
        if not isinstance(module, dict):
            raise StateMigrationError("Terraform state contains an invalid module")
        resources = module.get("resources", [])
        if not isinstance(resources, list):
            raise StateMigrationError("Terraform state resources must be an array")
        for resource in resources:
            address = resource.get("address") if isinstance(resource, dict) else None
            if not isinstance(address, str):
                raise StateMigrationError("Terraform state resource has no address")
            if resource.get("mode", "managed") != "managed":
                continue
            resource_values = resource.get("values")
            resource_id = resource_values.get("id") if isinstance(resource_values, dict) else None
            found.append((address, resource_id if isinstance(resource_id, str) else None))
        children = module.get("child_modules", [])
        if not isinstance(children, list):
            raise StateMigrationError("Terraform state child_modules must be an array")
        for child in children:
            walk(child)

    walk(root)
    return found


def _raw_managed_resources(state: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Read managed addresses directly from a pulled Terraform state v4 document."""
    if state == {}:
        return []
    if state.get("version") != 4:
        raise StateMigrationError("raw Terraform state must use version 4")
    resources = state.get("resources")
    if not isinstance(resources, list):
        raise StateMigrationError("raw Terraform state resources must be an array")
    found: list[tuple[str, str | None]] = []
    for resource in resources:
        if not isinstance(resource, dict):
            raise StateMigrationError("raw Terraform state contains an invalid resource")
        if resource.get("mode", "managed") != "managed":
            continue
        resource_type = resource.get("type")
        name = resource.get("name")
        module = resource.get("module")
        instances = resource.get("instances")
        if (
            not isinstance(resource_type, str)
            or not isinstance(name, str)
            or (module is not None and not isinstance(module, str))
            or not isinstance(instances, list)
        ):
            raise StateMigrationError("raw Terraform state resource identity is invalid")
        base_address = ".".join(item for item in (module, resource_type, name) if item)
        for instance in instances:
            if not isinstance(instance, dict):
                raise StateMigrationError("raw Terraform state instance is invalid")
            address = base_address + _raw_instance_suffix(instance.get("index_key"))
            attributes = instance.get("attributes")
            resource_id = attributes.get("id") if isinstance(attributes, dict) else None
            found.append((address, resource_id if isinstance(resource_id, str) else None))
    return found


def _raw_instance_suffix(index_key: object) -> str:
    if index_key is None:
        return ""
    if isinstance(index_key, bool):
        raise StateMigrationError("raw Terraform state index key is invalid")
    if isinstance(index_key, int):
        return f"[{index_key}]"
    if isinstance(index_key, str):
        return f"[{json.dumps(index_key)}]"
    raise StateMigrationError("raw Terraform state index key is invalid")


def verify_state_pair(
    source_state: dict[str, Any],
    destination_state: dict[str, Any],
    *,
    source_address: str,
    destination_address: str,
    phase: str,
) -> None:
    """Require exactly one owner before migration or one destination owner after it."""
    source_resources = _managed_resources(source_state)
    destination_resources = _managed_resources(destination_state)
    source_matches = [
        resource_id for address, resource_id in source_resources if address == source_address
    ]
    destination_matches = [
        resource_id
        for address, resource_id in destination_resources
        if address == destination_address
    ]
    source_count = len(source_matches)
    destination_count = len(destination_matches)
    expected = (1, 0) if phase == "pre" else (0, 1)
    if (source_count, destination_count) != expected:
        raise StateMigrationError(
            f"{phase}-migration ownership must be source={expected[0]} and "
            f"destination={expected[1]}; got source={source_count} and "
            f"destination={destination_count}"
        )
    selected_ids = source_matches if phase == "pre" else destination_matches
    if len(selected_ids) != 1 or not selected_ids[0]:
        raise StateMigrationError("selected service state has no physical resource id")
    source_ids = {resource_id.lower() for _, resource_id in source_resources if resource_id}
    destination_ids = {
        resource_id.lower() for _, resource_id in destination_resources if resource_id
    }
    if source_ids & destination_ids:
        raise StateMigrationError(
            "source and destination states contain duplicate physical resource ownership"
        )


def guard_legacy_plan(payload: dict[str, Any]) -> None:
    """Reject any legacy platform plan that would touch a migrated runtime address."""
    manifest = _object(_MANIFEST)
    services = manifest.get("services")
    if not isinstance(services, dict):
        raise StateMigrationError("state migration services must be an object")
    legacy_addresses = {
        move["from"]
        for raw in services.values()
        if isinstance(raw, dict)
        for move in raw.get("moves", [])
        if isinstance(move, dict) and isinstance(move.get("from"), str)
    }
    changes = payload.get("resource_changes", [])
    if not isinstance(changes, list):
        raise StateMigrationError("legacy plan resource_changes must be an array")
    violations: list[str] = []
    for entry in changes:
        if not isinstance(entry, dict):
            raise StateMigrationError("legacy plan contains an invalid resource change")
        address = entry.get("address")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if address in legacy_addresses and actions != ["no-op"]:
            violations.append(f"legacy deploy cannot recreate migrated runtime {address}")
    if violations:
        raise StateMigrationError("; ".join(violations))


def main() -> int:
    """Resolve coordinates, verify state cardinality, or guard a legacy plan."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    coordinates = commands.add_parser("coordinates")
    coordinates.add_argument("--service", required=True)
    coordinates.add_argument("--environment", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--source-state", type=Path, required=True)
    verify.add_argument("--destination-state", type=Path, required=True)
    verify.add_argument("--source-address", required=True)
    verify.add_argument("--destination-address", required=True)
    verify.add_argument("--phase", choices=("pre", "post"), required=True)
    legacy = commands.add_parser("guard-legacy-plan")
    legacy.add_argument("--plan-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "coordinates":
            print("\n".join(migration_coordinates(args.service, args.environment)))
        elif args.command == "verify":
            verify_state_pair(
                _object(args.source_state),
                _object(args.destination_state),
                source_address=args.source_address,
                destination_address=args.destination_address,
                phase=args.phase,
            )
        else:
            guard_legacy_plan(_object(args.plan_json))
    except (OSError, json.JSONDecodeError, ServiceContractError, StateMigrationError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

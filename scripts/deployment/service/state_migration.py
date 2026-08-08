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


def _addresses(state: dict[str, Any]) -> list[str]:
    values = state.get("values")
    root = values.get("root_module") if isinstance(values, dict) else None
    if root is None:
        return []
    found: list[str] = []

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
            found.append(address)
        children = module.get("child_modules", [])
        if not isinstance(children, list):
            raise StateMigrationError("Terraform state child_modules must be an array")
        for child in children:
            walk(child)

    walk(root)
    return found


def verify_state_pair(
    source_state: dict[str, Any],
    destination_state: dict[str, Any],
    *,
    source_address: str,
    destination_address: str,
    phase: str,
) -> None:
    """Require exactly one owner before migration or one destination owner after it."""
    source_count = _addresses(source_state).count(source_address)
    destination_count = _addresses(destination_state).count(destination_address)
    expected = (1, 0) if phase == "pre" else (0, 1)
    already_cutover = phase == "pre" and (source_count, destination_count) == (0, 1)
    if (source_count, destination_count) != expected and not already_cutover:
        raise StateMigrationError(
            f"{phase}-migration ownership must be source={expected[0]} and "
            f"destination={expected[1]}; got source={source_count} and "
            f"destination={destination_count}"
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

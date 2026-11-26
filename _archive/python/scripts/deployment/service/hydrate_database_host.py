#!/usr/bin/env python3
"""Hydrate a selected service tfvars object with its authoritative database host."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service


class DatabaseHostError(ValueError):
    """Raised when the authoritative host or selected tfvars object is invalid."""


def normalize_database_host(value: str) -> str:
    """Return one normalized ASCII DNS hostname or fail closed."""
    host = value.strip().rstrip(".")
    labels = host.split(".")
    if (
        not host
        or len(host) > 253
        or any(
            not label.isascii()
            or not label
            or len(label) > 63
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not character.isalnum() and character != "-" for character in label)
            for label in labels
        )
    ):
        raise DatabaseHostError("database host must be a valid DNS hostname")
    return host


def hydrate_database_host(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    database_host: str,
) -> dict[str, Any]:
    """Copy tfvars and replace only the selected service's non-secret database host."""
    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise DatabaseHostError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise DatabaseHostError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise DatabaseHostError(f"tfvars payload has no non-empty entry for {service}")
    database = selected.get("database")
    if not isinstance(database, dict):
        raise DatabaseHostError("selected service tfvars must contain a database object")

    hydrated = copy.deepcopy(payload)
    hydrated["environments"][environment][service]["database"]["host"] = normalize_database_host(
        database_host
    )
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the host-hydrated payload to stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--database-host", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise DatabaseHostError("tfvars payload must be a JSON object")
        hydrated = hydrate_database_host(
            raw,
            service=args.service,
            environment=args.environment,
            database_host=args.database_host,
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (json.JSONDecodeError, ServiceContractError, DatabaseHostError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

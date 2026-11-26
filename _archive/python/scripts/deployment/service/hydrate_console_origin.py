#!/usr/bin/env python3
"""Hydrate Operator tfvars with the authoritative Console Static Web App origin."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

from hydrate_database_host import DatabaseHostError, normalize_database_host
from service_contract import ServiceContractError, resolve_service


class ConsoleOriginError(ValueError):
    """Raised when the Console hostname or selected Operator tfvars are invalid."""


def normalize_console_origin(value: str) -> str:
    """Return the HTTPS origin for one Azure Static Web Apps default hostname."""
    try:
        hostname = normalize_database_host(value)
    except DatabaseHostError as exc:
        raise ConsoleOriginError("Console hostname must be a valid DNS hostname") from exc
    if not hostname.endswith(".azurestaticapps.net"):
        raise ConsoleOriginError(
            "Console hostname must be an Azure Static Web Apps default hostname"
        )
    return f"https://{hostname}"


def hydrate_console_origin(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    console_hostname: str,
) -> dict[str, Any]:
    """Copy tfvars and replace only the Operator Console CORS origin."""
    resolve_service(service, environment)
    hydrated = copy.deepcopy(payload)
    if service != "operator-service":
        if console_hostname:
            raise ConsoleOriginError("Console hostname is valid only for operator-service")
        return hydrated

    environments = hydrated.get("environments")
    if not isinstance(environments, dict):
        raise ConsoleOriginError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise ConsoleOriginError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise ConsoleOriginError(f"tfvars payload has no non-empty entry for {service}")
    selected["cors_allow_origins"] = normalize_console_origin(console_hostname)
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the Console-origin-hydrated payload."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--console-hostname", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ConsoleOriginError("tfvars payload must be a JSON object")
        hydrated = hydrate_console_origin(
            raw,
            service=args.service,
            environment=args.environment,
            console_hostname=args.console_hostname,
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (json.JSONDecodeError, ServiceContractError, ConsoleOriginError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

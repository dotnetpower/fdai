#!/usr/bin/env python3
"""Hydrate Core tfvars with the authoritative platform observation binding."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service


class ObservationContextError(ValueError):
    """Raised when the platform observation binding is malformed."""


def hydrate_observation_context(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    binding: object,
) -> dict[str, Any]:
    """Copy tfvars and replace only Core's platform-owned observation binding."""

    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise ObservationContextError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise ObservationContextError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise ObservationContextError(f"tfvars payload has no non-empty entry for {service}")

    hydrated = copy.deepcopy(payload)
    if service != "core-control-plane":
        return hydrated
    if binding is None:
        hydrated["environments"][environment][service].pop("observation_context", None)
        return hydrated
    if not isinstance(binding, dict) or set(binding) != {
        "signing_seed_secret_id",
        "executor_credential_lineage",
        "source_credential_lineage",
    }:
        raise ObservationContextError("platform observation binding has unexpected fields")
    if any(not isinstance(value, str) or not value.strip() for value in binding.values()):
        raise ObservationContextError(
            "platform observation binding values must be non-empty strings"
        )
    normalized = {name: value.strip() for name, value in binding.items()}
    if (
        normalized["executor_credential_lineage"].casefold()
        == normalized["source_credential_lineage"].casefold()
    ):
        raise ObservationContextError(
            "platform observation executor and source credential lineages must be distinct"
        )
    hydrated["environments"][environment][service]["observation_context"] = {
        "enabled": True,
        **normalized,
    }
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the observation-hydrated payload."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--binding-json", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ObservationContextError("tfvars payload must be a JSON object")
        binding = json.loads(args.binding_json)
        hydrated = hydrate_observation_context(
            raw,
            service=args.service,
            environment=args.environment,
            binding=binding,
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (
        json.JSONDecodeError,
        ServiceContractError,
        ObservationContextError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

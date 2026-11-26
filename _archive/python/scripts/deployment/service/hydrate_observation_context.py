#!/usr/bin/env python3
"""Hydrate Core tfvars with the authoritative platform observation binding."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from typing import Any
from uuid import UUID

from service_contract import ServiceContractError, resolve_service

_IDENTITY_RESOURCE_ID = re.compile(
    r"^/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
    r"/providers/Microsoft\.ManagedIdentity/userAssignedIdentities/"
    r"[A-Za-z0-9_.()-]{1,128}$",
    re.IGNORECASE,
)


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
    if not isinstance(binding, dict) or not isinstance(binding.get("enabled"), bool):
        raise ObservationContextError("platform observation binding has unexpected fields")
    enabled = binding["enabled"]
    enabled_fields = {
        "enabled",
        "signing_seed_secret_id",
        "executor_credential_lineage",
        "vm_start_executor_credential_lineage",
        "source_credential_lineage",
        "source_identity_client_id",
        "source_identity_resource_id",
    }
    disabled_fields = {
        "enabled",
        "source_identity_client_id",
        "source_identity_resource_id",
    }
    if set(binding) != (enabled_fields if enabled else disabled_fields):
        raise ObservationContextError("platform observation binding has unexpected fields")
    values = {name: value for name, value in binding.items() if name != "enabled"}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ObservationContextError(
            "platform observation binding values must be non-empty strings"
        )
    normalized = {name: value.strip() for name, value in values.items()}
    try:
        source_identity_client_id = str(UUID(normalized["source_identity_client_id"]))
    except ValueError as exc:
        raise ObservationContextError(
            "platform observation source identity client id must be a canonical UUID"
        ) from exc
    if source_identity_client_id != normalized["source_identity_client_id"].casefold():
        raise ObservationContextError(
            "platform observation source identity client id must be a canonical UUID"
        )
    source_identity_resource_id = normalized.pop("source_identity_resource_id")
    if _IDENTITY_RESOURCE_ID.fullmatch(source_identity_resource_id) is None:
        raise ObservationContextError(
            "platform observation source identity resource id must be canonical"
        )
    if (
        enabled
        and len(
            {
                normalized["executor_credential_lineage"].casefold(),
                normalized["vm_start_executor_credential_lineage"].casefold(),
                normalized["source_credential_lineage"].casefold(),
            }
        )
        != 3
    ):
        raise ObservationContextError(
            "platform observation action executor and source credential lineages must be distinct"
        )
    identity = hydrated["environments"][environment][service].get("identity")
    if not isinstance(identity, dict):
        raise ObservationContextError("Core tfvars must contain an identity object")
    extra_resource_ids = identity.get("extra_resource_ids", [])
    if not isinstance(extra_resource_ids, list) or any(
        not isinstance(value, str) or not value.strip() for value in extra_resource_ids
    ):
        raise ObservationContextError("Core identity extra_resource_ids must be a string list")
    retained_resource_ids = [
        value
        for value in extra_resource_ids
        if value.casefold() != source_identity_resource_id.casefold()
    ]
    if not enabled:
        identity["extra_resource_ids"] = retained_resource_ids
        hydrated["environments"][environment][service].pop("observation_context", None)
        return hydrated
    identity["extra_resource_ids"] = retained_resource_ids + [source_identity_resource_id]
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

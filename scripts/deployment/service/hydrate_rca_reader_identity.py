#!/usr/bin/env python3
"""Hydrate split Core tfvars with the platform-owned RCA reader identity."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service


class RcaReaderIdentityError(ValueError):
    """The platform RCA reader identity is malformed."""


def hydrate_rca_reader_identity(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    identity: object,
) -> dict[str, Any]:
    """Copy tfvars and replace only Core's platform-owned RCA reader identity."""

    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise RcaReaderIdentityError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise RcaReaderIdentityError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise RcaReaderIdentityError(f"tfvars payload has no non-empty entry for {service}")

    hydrated = copy.deepcopy(payload)
    if service != "core-control-plane":
        return hydrated
    if not isinstance(identity, dict) or set(identity) != {
        "client_id",
        "principal_id",
        "resource_id",
    }:
        raise RcaReaderIdentityError("platform RCA reader identity has unexpected fields")
    if any(
        not isinstance(value, str) or not value.strip() or value != value.strip()
        for value in identity.values()
    ):
        raise RcaReaderIdentityError(
            "platform RCA reader identity values must be trimmed non-empty strings"
        )
    resource_id = identity["resource_id"]
    if not resource_id.casefold().endswith("-rca-reader"):
        raise RcaReaderIdentityError(
            "platform RCA reader resource id must name the dedicated RCA reader"
        )
    hydrated["environments"][environment][service]["rca_reader_identity"] = {
        "resource_id": resource_id,
        "client_id": identity["client_id"],
    }
    return hydrated


def main() -> int:
    """Read tfvars from stdin and emit the RCA-reader-hydrated payload."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--identity-json", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise RcaReaderIdentityError("tfvars payload must be a JSON object")
        identity = json.loads(args.identity_json)
        hydrated = hydrate_rca_reader_identity(
            raw,
            service=args.service,
            environment=args.environment,
            identity=identity,
        )
        json.dump(hydrated, sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
    except (
        json.JSONDecodeError,
        ServiceContractError,
        RcaReaderIdentityError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

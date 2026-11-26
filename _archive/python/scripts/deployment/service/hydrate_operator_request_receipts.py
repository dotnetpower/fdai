#!/usr/bin/env python3
"""Hydrate service tfvars with platform-owned operator_request receipt bindings."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from typing import Any

from service_contract import ServiceContractError, resolve_service

_SECRET_ID = re.compile(r"^https://[^/]+/secrets/[^/]+$")
_PRODUCER_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class OperatorRequestReceiptBindingError(ValueError):
    """Raised when platform operator_request receipt binding is malformed."""


def hydrate_operator_request_receipts(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    binding: object,
) -> dict[str, Any]:
    """Copy tfvars and replace only the selected service's receipt binding."""

    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise OperatorRequestReceiptBindingError(
            "tfvars payload must contain an environments object"
        )
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise OperatorRequestReceiptBindingError(
            f"tfvars payload has no {environment} environment object"
        )
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise OperatorRequestReceiptBindingError(
            f"tfvars payload has no non-empty entry for {service}"
        )

    hydrated = copy.deepcopy(payload)
    target = hydrated["environments"][environment][service]
    if binding is None:
        target.pop("operator_request_receipts", None)
        return hydrated
    if service not in {"core-control-plane", "operator-service"}:
        target.pop("operator_request_receipts", None)
        return hydrated
    if not isinstance(binding, dict):
        raise OperatorRequestReceiptBindingError(
            "operator_request receipt binding must be an object or null"
        )
    expected = {
        "core_signing_seed_secret_id",
        "operator_signing_seed_secret_id",
        "core_producer_id",
        "operator_producer_id",
    }
    if set(binding) != expected:
        raise OperatorRequestReceiptBindingError(
            "operator_request receipt binding has unexpected fields"
        )
    for key in ("core_signing_seed_secret_id", "operator_signing_seed_secret_id"):
        value = binding[key]
        if not isinstance(value, str) or _SECRET_ID.fullmatch(value.strip()) is None:
            raise OperatorRequestReceiptBindingError(
                "operator_request receipt seed secret ids must be versionless HTTPS Key Vault ids"
            )
    for key in ("core_producer_id", "operator_producer_id"):
        value = binding[key]
        if not isinstance(value, str) or _PRODUCER_ID.fullmatch(value.strip()) is None:
            raise OperatorRequestReceiptBindingError(
                "operator_request receipt producer ids must be bounded identifiers"
            )
    if binding["core_producer_id"] == binding["operator_producer_id"]:
        raise OperatorRequestReceiptBindingError(
            "operator_request receipt producer ids must be distinct"
        )

    if service == "core-control-plane":
        target["operator_request_receipts"] = {
            "core_signing_seed_secret_id": binding["core_signing_seed_secret_id"].strip(),
            "operator_signing_seed_secret_id": binding["operator_signing_seed_secret_id"].strip(),
            "core_producer_id": binding["core_producer_id"].strip(),
            "operator_producer_id": binding["operator_producer_id"].strip(),
        }
    else:
        target["operator_request_receipts"] = {
            "operator_signing_seed_secret_id": binding["operator_signing_seed_secret_id"].strip(),
            "producer_id": binding["operator_producer_id"].strip(),
        }
    return hydrated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--binding-json", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise OperatorRequestReceiptBindingError("tfvars payload must be a JSON object")
        binding = json.loads(args.binding_json)
        hydrated = hydrate_operator_request_receipts(
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
        OperatorRequestReceiptBindingError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

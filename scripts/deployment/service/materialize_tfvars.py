#!/usr/bin/env python3
"""Materialize one service's protected Terraform inputs from stdin."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from service_contract import ServiceContractError, resolve_service


class TfvarsError(ValueError):
    """Raised when protected service tfvars are missing or ambiguous."""


def select_tfvars(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    operator_channel_edge_enabled: bool | None = None,
) -> dict[str, Any]:
    """Select exactly one environment/service object and reserve image for the workflow."""
    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise TfvarsError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise TfvarsError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise TfvarsError(f"tfvars payload has no non-empty entry for {service}")
    if "image" in selected:
        raise TfvarsError("tfvars payload must not set image; the attested workflow input owns it")
    materialized = copy.deepcopy(selected)
    if operator_channel_edge_enabled is not None:
        if service != "operator-service":
            raise TfvarsError("operator channel edge override is valid only for operator-service")
        channel_edge = materialized.get("channel_edge")
        if not isinstance(channel_edge, dict):
            raise TfvarsError("operator tfvars must contain a channel_edge object")
        channel_edge["enabled"] = operator_channel_edge_enabled
    return materialized


def write_tfvars(path: Path, payload: dict[str, Any]) -> None:
    """Write selected deployment inputs with owner-only permissions."""
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    """Read the repository secret from stdin and write one temporary tfvars file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--operator-channel-edge-enabled",
        choices=("true", "false"),
    )
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise TfvarsError("tfvars payload must be a JSON object")
        edge_enabled = (
            args.operator_channel_edge_enabled == "true"
            if args.operator_channel_edge_enabled is not None
            else None
        )
        selected = select_tfvars(
            raw,
            service=args.service,
            environment=args.environment,
            operator_channel_edge_enabled=edge_enabled,
        )
        write_tfvars(args.output, selected)
    except (OSError, json.JSONDecodeError, ServiceContractError, TfvarsError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

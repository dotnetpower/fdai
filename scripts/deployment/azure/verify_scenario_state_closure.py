#!/usr/bin/env python3
"""Verify that the disposable scenario Terraform state owns no live resources."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path


def verify_state_closed(state: object | None) -> dict[str, object]:
    """Accept an absent state or one with no managed resource instances."""

    managed: list[str] = []
    if state is not None:
        if not isinstance(state, Mapping):
            raise ValueError("scenario Terraform state must be an object")
        resources = state.get("resources", [])
        if not isinstance(resources, list):
            raise ValueError("scenario Terraform state resources must be an array")
        for resource in resources:
            if not isinstance(resource, Mapping):
                raise ValueError("scenario Terraform resources must be objects")
            if resource.get("mode") != "managed":
                continue
            instances = resource.get("instances", [])
            if not isinstance(instances, list):
                raise ValueError("scenario Terraform resource instances must be an array")
            if instances:
                managed.append(str(resource.get("type", "unknown")))
    if managed:
        raise ValueError("scenario Terraform state still owns managed resources")
    canonical = json.dumps(sorted(managed), separators=(",", ":")).encode()
    return {
        "schema_version": "fdai.scenario-state-closure-receipt.v1",
        "state_present": state is not None,
        "managed_resource_count": 0,
        "state_closed": True,
        "resource_type_digest": hashlib.sha256(canonical).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state is not None else None
    try:
        receipt = verify_state_closed(state)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Scenario Terraform state closure verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

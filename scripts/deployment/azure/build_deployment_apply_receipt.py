#!/usr/bin/env python3
"""Build the sanitized receipt for one exact protected deployment apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def build_apply_receipt(
    *,
    environ: Mapping[str, str],
    inventory_path: Path,
    plan_metadata_path: Path,
) -> dict[str, object]:
    """Return an apply receipt closed over every available required observation."""
    receipt: dict[str, object] = {
        "schema_version": "fdai.deployment-apply-receipt.v1",
        "plan_id": environ["APPLY_PLAN_ID"],
        "plan_digest": environ["APPLY_PLAN_DIGEST"],
        "request_id": environ["APPLY_REQUEST_ID"],
        "context_digest": environ["APPLY_CONTEXT_DIGEST"],
        "source_commit": environ["APPLY_SOURCE_COMMIT"],
        "workflow_run_id": environ["GITHUB_RUN_ID"],
        "workflow_run_attempt": environ["GITHUB_RUN_ATTEMPT"],
        "applied_at": environ["APPLIED_AT"],
        "status": "applied",
        "subscription_ready": False,
    }
    if inventory_path.is_file():
        inventory_bytes = inventory_path.read_bytes()
        inventory = _json_object(inventory_bytes, "initial inventory receipt")
        if (
            inventory.get("schema_version") != "fdai.genesis-initial-inventory-execution-receipt.v1"
            or inventory.get("source_commit") != environ["APPLY_SOURCE_COMMIT"]
            or inventory.get("status") != "succeeded"
            or inventory.get("active_generation_verified") is not False
            or inventory.get("subscription_ready") is not False
        ):
            raise ValueError("initial inventory receipt is invalid")
        receipt.update(
            {
                "terraform_zero_change_verified": True,
                "migration_stage_verified": True,
                "runtime_health_verified": True,
                "canary_verified": True,
                "initial_inventory_execution_receipt_digest": hashlib.sha256(
                    inventory_bytes
                ).hexdigest(),
            }
        )
    readback_digest = environ.get("MODEL_BINDING_READBACK_DIGEST", "")
    if readback_digest:
        if not _is_digest(readback_digest):
            raise ValueError("model binding readback digest is invalid")
        model_resolution = _load_json_object(plan_metadata_path, "plan metadata").get(
            "model_resolution"
        )
        if not isinstance(model_resolution, dict):
            raise ValueError("model binding apply receipt has no model resolution")
        receipt["model_binding"] = {
            "model_resolution": model_resolution,
            "readback_receipt_digest": readback_digest,
        }
    identity_effect_digest = environ.get("DEPLOY_IDENTITY_EFFECT_DIGEST", "")
    if identity_effect_digest:
        receipt["deploy_identity_effect_digest"] = identity_effect_digest
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_digest(value: Mapping[str, object]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return _json_object(path.read_bytes(), label)
    except OSError as exc:
        raise ValueError(f"{label} is invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-receipt",
        type=Path,
        default=Path("initial-inventory-receipt.json"),
    )
    parser.add_argument("--plan-metadata", type=Path, default=Path("plan-metadata.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_apply_receipt(
            environ=os.environ,
            inventory_path=args.inventory_receipt,
            plan_metadata_path=args.plan_metadata,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

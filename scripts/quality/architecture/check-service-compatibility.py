#!/usr/bin/env python3
"""Validate five-service N/N-1 wire and independent transition evidence."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_SOURCE = REPO_ROOT / "service-contracts" / "src"
sys.path.insert(0, str(CONTRACT_SOURCE))

from fdai_service_contracts import (  # noqa: E402
    CompatibilityError,
    load_json_object,
    project_additive_fields,
    validate_delivery_trace,
    validate_manifest,
    validate_peer_upgrade_receipt,
)

MANIFEST_PATH = CONTRACT_SOURCE / "fdai_service_contracts" / "compatibility-manifest.json"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "services"
SERVICE_IDS = {
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
}


def validate() -> None:
    """Validate the manifest, wire payloads, delivery traces, and transition receipts."""

    manifest = load_json_object(MANIFEST_PATH)
    summary = validate_manifest(manifest, repo_root=REPO_ROOT)
    contracts = _contract_map(manifest)
    _validate_wire_payloads(contracts)
    _validate_delivery_traces()
    receipt_count = _validate_upgrade_receipts(manifest)
    print(
        "check-service-compatibility: OK "
        f"(services={summary.service_count} contracts={summary.contract_count} "
        f"matrix_edges={summary.matrix_edge_count} receipts={receipt_count})"
    )


def _validate_wire_payloads(contracts: Mapping[str, Mapping[str, Any]]) -> None:
    fixtures = _load_json_array(FIXTURE_ROOT / "wire-payloads.json")
    seen: set[str] = set()
    for fixture in fixtures:
        contract_id = fixture.get("contract_id")
        release = fixture.get("producer_release")
        payload = _mapping(fixture.get("payload"), "wire payload")
        if not isinstance(contract_id, str) or contract_id not in contracts:
            raise CompatibilityError("wire fixture references an unknown contract")
        if release not in {"N", "N-1"}:
            raise CompatibilityError(f"{contract_id} fixture has an unknown release")
        contract = contracts[contract_id]
        schemas = _mapping(contract.get("producer_schemas"), f"{contract_id}.producer_schemas")
        schema_ref = _mapping(schemas[str(release)], f"{contract_id}.{release}")
        schema = load_json_object(REPO_ROOT / str(schema_ref["path"]))
        _validator(schema).validate(payload)
        if contract.get("compatibility_policy") == "additive-ignore-unknown" and release == "N":
            previous_ref = _mapping(schemas["N-1"], f"{contract_id}.N-1")
            previous_schema = load_json_object(REPO_ROOT / str(previous_ref["path"]))
            _validator(previous_schema).validate(project_additive_fields(previous_schema, payload))
        seen.add(contract_id)
    if seen != set(contracts):
        raise CompatibilityError("wire fixtures must cover every contract")


def _validate_delivery_traces() -> None:
    fixtures = _load_json_array(FIXTURE_ROOT / "delivery-traces.json")
    seen: set[str] = set()
    for fixture in fixtures:
        service_id = fixture.get("service_id")
        if not isinstance(service_id, str) or service_id in seen:
            raise CompatibilityError("delivery trace service ids must be unique strings")
        attempts_value = fixture.get("attempts")
        if not isinstance(attempts_value, list):
            raise CompatibilityError(f"{service_id} attempts must be an array")
        attempts = [
            _mapping(attempt, f"{service_id} delivery attempt") for attempt in attempts_value
        ]
        result = validate_delivery_trace(attempts)
        if result.duplicate_count < 1:
            raise CompatibilityError(f"{service_id} delivery trace must exercise a duplicate")
        seen.add(service_id)
    if seen != SERVICE_IDS:
        raise CompatibilityError("delivery traces must cover exactly the five services")


def _validate_upgrade_receipts(manifest: Mapping[str, Any]) -> int:
    receipt_contract = _mapping(manifest.get("upgrade_receipt"), "upgrade_receipt")
    schema = load_json_object(REPO_ROOT / str(receipt_contract["schema_path"]))
    fixtures = _load_json_array(FIXTURE_ROOT / "upgrade-receipts.json")
    seen: set[tuple[str, str]] = set()
    for receipt in fixtures:
        _validator(schema).validate(receipt)
        validate_peer_upgrade_receipt(manifest, receipt)
        service_id = receipt.get("service_id")
        direction = receipt.get("direction")
        if not isinstance(service_id, str) or not isinstance(direction, str):
            raise CompatibilityError("receipt identity and direction must be strings")
        key = (service_id, direction)
        if key in seen:
            raise CompatibilityError("upgrade receipt fixture identities must be unique")
        seen.add(key)
    expected = {
        (service_id, direction)
        for service_id in SERVICE_IDS
        for direction in ("migration", "rollback")
    }
    if seen != expected:
        raise CompatibilityError("receipts must cover migration and rollback for all five services")
    return len(fixtures)


def _contract_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    value = manifest.get("contracts")
    if not isinstance(value, list):
        raise CompatibilityError("manifest contracts must be an array")
    contracts: dict[str, Mapping[str, Any]] = {}
    for item in value:
        contract = _mapping(item, "contract")
        contract_id = contract.get("id")
        if not isinstance(contract_id, str):
            raise CompatibilityError("contract id must be a string")
        contracts[contract_id] = contract
    return contracts


def _validator(schema: Mapping[str, Any]) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _load_json_array(path: Path) -> list[Mapping[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot load JSON array: {path}") from exc
    if not isinstance(value, list):
        raise CompatibilityError(f"JSON fixture must be an array: {path}")
    return [_mapping(item, f"fixture in {path.name}") for item in value]


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


def main() -> int:
    """Run the compatibility gate as a command-line check."""

    try:
        validate()
    except (CompatibilityError, KeyError, SchemaError, ValidationError) as exc:
        print(f"check-service-compatibility: ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

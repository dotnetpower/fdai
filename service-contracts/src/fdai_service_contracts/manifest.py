"""Validation for the five-service N/N-1 compatibility manifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_service_contracts.compatibility import (
    CompatibilityError,
    SemVer,
    assert_additive_schema,
    load_json_object,
)

_SERVICE_IDS = frozenset(
    {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
)
_RELEASE_LABELS = frozenset({"N", "N-1"})
_REQUIRED_PAIRS = frozenset(
    {
        ("N-1", "N-1"),
        ("N-1", "N"),
        ("N", "N-1"),
        ("N", "N"),
    }
)
_REQUIRED_DELIVERY = {
    "guarantee": "at-least-once",
    "duplicate_policy": "deduplicate-by-idempotency-key",
    "reorder_policy": "partition-sequence",
}


@dataclass(frozen=True, slots=True)
class CompatibilitySummary:
    """Counts from one successfully validated compatibility manifest."""

    service_count: int
    contract_count: int
    matrix_edge_count: int


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path,
) -> CompatibilitySummary:
    """Validate service versions, wire contracts, matrix coverage, and rollback declarations."""

    if manifest.get("manifest_version") != "1.0.0":
        raise CompatibilityError("manifest_version must be 1.0.0")
    policy = _mapping(manifest.get("policy"), "policy")
    if set(_string_list(policy.get("release_labels"), "policy.release_labels")) != _RELEASE_LABELS:
        raise CompatibilityError("policy release_labels must be N and N-1")
    services = _validate_services(manifest.get("services"))
    contracts = _validate_contracts(manifest.get("contracts"), services, repo_root=repo_root)
    edge_count = _validate_matrix(manifest.get("producer_consumer_matrix"), contracts)
    _validate_receipt_contract(manifest.get("upgrade_receipt"), repo_root=repo_root)
    return CompatibilitySummary(len(services), len(contracts), edge_count)


def _validate_services(value: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise CompatibilityError("services must be an array")
    services: dict[str, Mapping[str, Any]] = {}
    for item in value:
        service = _mapping(item, "service")
        service_id = service.get("id")
        if not isinstance(service_id, str) or service_id in services:
            raise CompatibilityError("service ids must be unique strings")
        current = SemVer.parse(service.get("current_version"))
        previous = SemVer.parse(service.get("previous_version"))
        supported_major = service.get("supported_major")
        if supported_major != current.major or previous.major != current.major:
            raise CompatibilityError(f"{service_id} versions must share supported_major")
        if current <= previous:
            raise CompatibilityError(f"{service_id} current_version must follow previous_version")
        migration = _mapping(service.get("migration"), f"{service_id}.migration")
        rollback = _mapping(service.get("rollback"), f"{service_id}.rollback")
        if migration != {
            "from_version": str(previous),
            "to_version": str(current),
        }:
            raise CompatibilityError(f"{service_id} migration versions are not exact")
        if rollback != {
            "from_version": str(current),
            "to_version": str(previous),
        }:
            raise CompatibilityError(f"{service_id} rollback versions are not exact")
        services[service_id] = service
    if set(services) != _SERVICE_IDS:
        raise CompatibilityError("manifest must declare exactly the five FDAI services")
    return services


def _validate_contracts(
    value: object,
    services: Mapping[str, Mapping[str, Any]],
    *,
    repo_root: Path,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise CompatibilityError("contracts must be a non-empty array")
    contracts: dict[str, Mapping[str, Any]] = {}
    participating_services: set[str] = set()
    for item in value:
        contract = _mapping(item, "contract")
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not contract_id or contract_id in contracts:
            raise CompatibilityError("contract ids must be unique non-empty strings")
        producer = contract.get("producer")
        consumer = contract.get("consumer")
        if producer not in services or consumer not in services or producer == consumer:
            raise CompatibilityError(
                f"{contract_id} producer and consumer must be distinct services"
            )
        participating_services.update((str(producer), str(consumer)))
        _validate_delivery(contract_id, contract.get("delivery"))
        producer_schemas = _mapping(
            contract.get("producer_schemas"), f"{contract_id}.producer_schemas"
        )
        consumer_accepts = _mapping(
            contract.get("consumer_accepts"), f"{contract_id}.consumer_accepts"
        )
        if set(producer_schemas) != _RELEASE_LABELS or set(consumer_accepts) != _RELEASE_LABELS:
            raise CompatibilityError(f"{contract_id} must declare N and N-1 schema support")
        resolved_schemas: dict[str, Mapping[str, Any]] = {}
        schema_versions: dict[str, str] = {}
        for release_label in _RELEASE_LABELS:
            schema_ref = _mapping(
                producer_schemas[release_label],
                f"{contract_id}.producer_schemas.{release_label}",
            )
            version = str(SemVer.parse(schema_ref.get("version")))
            path = _safe_repo_path(repo_root, schema_ref.get("path"))
            resolved_schemas[release_label] = load_json_object(path)
            schema_versions[release_label] = version
            accepted = set(
                _string_list(
                    consumer_accepts[release_label],
                    f"{contract_id}.consumer_accepts.{release_label}",
                )
            )
            for accepted_version in accepted:
                SemVer.parse(accepted_version)
            if not accepted:
                raise CompatibilityError(f"{contract_id} consumer acceptance cannot be empty")
        policy = contract.get("compatibility_policy")
        if policy == "additive-ignore-unknown":
            assert_additive_schema(resolved_schemas["N-1"], resolved_schemas["N"])
        elif policy == "stable":
            if producer_schemas["N-1"] != producer_schemas["N"]:
                raise CompatibilityError(f"{contract_id} stable schemas must be identical")
        elif policy != "version-negotiated":
            raise CompatibilityError(f"{contract_id} has unsupported compatibility_policy")
        for producer_release, consumer_release in _REQUIRED_PAIRS:
            produced_version = schema_versions[producer_release]
            accepted_versions = set(
                _string_list(
                    consumer_accepts[consumer_release],
                    f"{contract_id}.consumer_accepts.{consumer_release}",
                )
            )
            if produced_version not in accepted_versions:
                raise CompatibilityError(
                    f"{contract_id} {producer_release}->{consumer_release} rejects {produced_version}"
                )
        contracts[contract_id] = contract
    if participating_services != _SERVICE_IDS:
        raise CompatibilityError("wire contracts must cover all five services")
    return contracts


def _validate_delivery(contract_id: str, value: object) -> None:
    delivery = _mapping(value, f"{contract_id}.delivery")
    for key, expected in _REQUIRED_DELIVERY.items():
        if delivery.get(key) != expected:
            raise CompatibilityError(f"{contract_id} delivery {key} must be {expected}")
    for key in ("partition_key_field", "idempotency_key_field"):
        if not isinstance(delivery.get(key), str) or not delivery[key]:
            raise CompatibilityError(f"{contract_id} delivery {key} must be non-empty")
    if delivery.get("normal_retention_days") != 1 or delivery.get("dlq_retention_days") != 7:
        raise CompatibilityError(f"{contract_id} retention must be 1 day and DLQ 7 days")


def _validate_matrix(
    value: object,
    contracts: Mapping[str, Mapping[str, Any]],
) -> int:
    if not isinstance(value, list):
        raise CompatibilityError("producer_consumer_matrix must be an array")
    seen: set[str] = set()
    for item in value:
        edge = _mapping(item, "producer_consumer_matrix edge")
        contract_id = edge.get("contract_id")
        if not isinstance(contract_id, str) or contract_id in seen or contract_id not in contracts:
            raise CompatibilityError("matrix contract ids must be unique and declared")
        contract = contracts[contract_id]
        if edge.get("producer") != contract.get("producer"):
            raise CompatibilityError(f"{contract_id} matrix producer mismatch")
        if edge.get("consumer") != contract.get("consumer"):
            raise CompatibilityError(f"{contract_id} matrix consumer mismatch")
        pairs_value = edge.get("supported_pairs")
        if not isinstance(pairs_value, list):
            raise CompatibilityError(f"{contract_id} supported_pairs must be an array")
        pairs: set[tuple[str, str]] = set()
        for pair_value in pairs_value:
            pair = _mapping(pair_value, f"{contract_id} supported pair")
            producer_release = pair.get("producer_release")
            consumer_release = pair.get("consumer_release")
            if not isinstance(producer_release, str) or not isinstance(consumer_release, str):
                raise CompatibilityError(f"{contract_id} supported pair labels must be strings")
            pairs.add((producer_release, consumer_release))
        if pairs != _REQUIRED_PAIRS or len(pairs_value) != len(_REQUIRED_PAIRS):
            raise CompatibilityError(f"{contract_id} matrix must contain each N/N-1 pair once")
        seen.add(contract_id)
    if seen != set(contracts):
        raise CompatibilityError("matrix must contain every declared contract")
    return len(seen)


def _validate_receipt_contract(value: object, *, repo_root: Path) -> None:
    receipt = _mapping(value, "upgrade_receipt")
    SemVer.parse(receipt.get("version"))
    _safe_repo_path(repo_root, receipt.get("schema_path"))
    required_checks = set(_string_list(receipt.get("required_checks"), "required_checks"))
    expected = {
        "additive_fields",
        "duplicate_delivery",
        "health",
        "idempotency",
        "matrix",
        "reordered_delivery",
        "unsupported_major_rejection",
    }
    if required_checks != expected:
        raise CompatibilityError("upgrade receipt checks do not match the compatibility gate")


def _safe_repo_path(repo_root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise CompatibilityError("schema path must be a non-empty string")
    root = repo_root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise CompatibilityError(f"schema path is missing or escapes the repository: {value}")
    return path


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CompatibilityError(f"{name} must be a string array")
    return value


__all__ = ["CompatibilitySummary", "validate_manifest"]

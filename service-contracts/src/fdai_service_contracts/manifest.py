"""Validation for the five-service N/N-1 compatibility manifest."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from fdai_service_contracts.compatibility import (
    CompatibilityError,
    SemVer,
    assert_additive_schema,
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
_ALL_PAIRS = frozenset(
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
    repo_root: Path | None = None,
) -> CompatibilitySummary:
    """Validate the bundled manifest without depending on a repository checkout.

    ``repo_root`` remains accepted for N/N-1 callers that still pass it, but schema
    resolution is package-backed so an installed wheel validates the same artifact.
    """

    del repo_root

    if manifest.get("manifest_version") != "1.0.0":
        raise CompatibilityError("manifest_version must be 1.0.0")
    policy = _mapping(manifest.get("policy"), "policy")
    if set(_string_list(policy.get("release_labels"), "policy.release_labels")) != _RELEASE_LABELS:
        raise CompatibilityError("policy release_labels must be N and N-1")
    services = _validate_services(manifest.get("services"))
    contracts = _validate_contracts(manifest.get("contracts"), services)
    edge_count = _validate_matrix(manifest.get("producer_consumer_matrix"), contracts)
    _validate_receipt_contract(manifest.get("upgrade_receipt"))
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
        _validate_transition(
            service_id,
            "migration",
            migration,
            from_version=str(previous),
            to_version=str(current),
            supported_major=current.major,
        )
        _validate_transition(
            service_id,
            "rollback",
            rollback,
            from_version=str(current),
            to_version=str(previous),
            supported_major=current.major,
        )
        services[service_id] = service
    if set(services) != _SERVICE_IDS:
        raise CompatibilityError("manifest must declare exactly the five FDAI services")
    return services


def _validate_transition(
    service_id: str,
    direction: str,
    transition: Mapping[str, Any],
    *,
    from_version: str,
    to_version: str,
    supported_major: int,
) -> None:
    if transition.get("from_version") != from_version or transition.get("to_version") != to_version:
        raise CompatibilityError(f"{service_id} {direction} versions are not exact")
    requirements = _mapping(
        transition.get("requires_peer_versions", {}),
        f"{service_id}.{direction}.requires_peer_versions",
    )
    if service_id in requirements or not set(requirements) <= _SERVICE_IDS - {service_id}:
        raise CompatibilityError(f"{service_id} {direction} peer requirements are invalid")
    for version in requirements.values():
        if SemVer.parse(version).major != supported_major:
            raise CompatibilityError(f"{service_id} {direction} peer version is unsupported")


def _validate_contracts(
    value: object,
    services: Mapping[str, Mapping[str, Any]],
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
        _validate_codec_references(contract_id, contract)
        if set(producer_schemas) != _RELEASE_LABELS or set(consumer_accepts) != _RELEASE_LABELS:
            raise CompatibilityError(f"{contract_id} must declare N and N-1 schema support")
        resolved_schemas: dict[str, Mapping[str, Any]] = {}
        for release_label in _RELEASE_LABELS:
            schema_ref = _mapping(
                producer_schemas[release_label],
                f"{contract_id}.producer_schemas.{release_label}",
            )
            SemVer.parse(schema_ref.get("version"))
            resolved_schemas[release_label] = _load_package_schema(schema_ref.get("path"))
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
            assert_additive_schema(
                resolved_schemas["N-1"],
                resolved_schemas["N"],
                version_field="schema_version",
            )
        elif policy == "stable":
            if producer_schemas["N-1"] != producer_schemas["N"]:
                raise CompatibilityError(f"{contract_id} stable schemas must be identical")
        elif policy != "version-negotiated":
            raise CompatibilityError(f"{contract_id} has unsupported compatibility_policy")
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


def _validate_codec_references(contract_id: str, contract: Mapping[str, Any]) -> None:
    for artifact_kind in ("producer_codecs", "consumer_codecs"):
        references = _mapping(contract.get(artifact_kind), f"{contract_id}.{artifact_kind}")
        if set(references) != _RELEASE_LABELS:
            raise CompatibilityError(f"{contract_id} {artifact_kind} must declare N and N-1")
        if any(
            not isinstance(reference, str) or reference.count(":") != 1
            for reference in references.values()
        ):
            raise CompatibilityError(f"{contract_id} {artifact_kind} reference is invalid")


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
        unsupported_value = edge.get("unsupported_pairs", [])
        if not isinstance(unsupported_value, list):
            raise CompatibilityError(f"{contract_id} unsupported_pairs must be an array")
        unsupported: set[tuple[str, str]] = set()
        for pair_value in unsupported_value:
            pair = _mapping(pair_value, f"{contract_id} unsupported pair")
            producer_release = pair.get("producer_release")
            consumer_release = pair.get("consumer_release")
            reason = pair.get("reason")
            if (
                not isinstance(producer_release, str)
                or not isinstance(consumer_release, str)
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                raise CompatibilityError(
                    f"{contract_id} unsupported pair labels and reason must be strings"
                )
            unsupported.add((producer_release, consumer_release))
        if (
            pairs & unsupported
            or pairs | unsupported != _ALL_PAIRS
            or len(pairs_value) + len(unsupported_value) != len(_ALL_PAIRS)
        ):
            raise CompatibilityError(f"{contract_id} matrix must classify each N/N-1 pair once")
        producer_schemas = _mapping(contract.get("producer_schemas"), "producer_schemas")
        consumer_accepts = _mapping(contract.get("consumer_accepts"), "consumer_accepts")
        translators = _mapping(contract.get("translators", {}), "translators")
        for direction, reference in translators.items():
            if direction not in {"N->N-1", "N-1->N"}:
                raise CompatibilityError(f"{contract_id} translator direction is unsupported")
            if not isinstance(reference, str) or ":" not in reference:
                raise CompatibilityError(f"{contract_id} translator reference is invalid")
        for producer_release, consumer_release in _ALL_PAIRS:
            schema_ref = _mapping(producer_schemas[producer_release], "producer schema")
            directly_supported = schema_ref.get("version") in set(
                _string_list(consumer_accepts[consumer_release], "consumer acceptance")
            )
            translated_supported = f"{producer_release}->{consumer_release}" in translators
            classified_supported = (producer_release, consumer_release) in pairs
            if (directly_supported or translated_supported) != classified_supported:
                raise CompatibilityError(
                    f"{contract_id} matrix conflicts with consumer acceptance for "
                    f"{producer_release}->{consumer_release}"
                )
        seen.add(contract_id)
    if seen != set(contracts):
        raise CompatibilityError("matrix must contain every declared contract")
    return len(seen)


def _validate_receipt_contract(value: object) -> None:
    receipt = _mapping(value, "upgrade_receipt")
    SemVer.parse(receipt.get("version"))
    _load_package_schema(receipt.get("schema_path"))
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


def _load_package_schema(value: object) -> Mapping[str, Any]:
    if not isinstance(value, str) or not value:
        raise CompatibilityError("schema path must be a non-empty string")
    path = PurePosixPath(value)
    legacy_prefix = ("service-contracts", "src", "fdai_service_contracts")
    parts = path.parts
    if parts[: len(legacy_prefix)] == legacy_prefix:
        parts = parts[len(legacy_prefix) :]
    if path.is_absolute() or not parts or parts[0] != "schemas" or ".." in parts:
        raise CompatibilityError(f"schema path is missing or escapes the package: {value}")
    resource = resources.files("fdai_service_contracts").joinpath(*parts)
    if not resource.is_file():
        raise CompatibilityError(f"schema path is missing or escapes the package: {value}")
    try:
        loaded = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot load JSON object from package schema: {value}") from exc
    if not isinstance(loaded, dict):
        raise CompatibilityError(f"package schema is not a JSON object: {value}")
    return loaded


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CompatibilityError(f"{name} must be a string array")
    return value


__all__ = ["CompatibilitySummary", "validate_manifest"]

#!/usr/bin/env python3
"""Validate five-service N/N-1 wire and independent transition evidence."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_SOURCE = REPO_ROOT / "service-contracts" / "src"
SERVICE_SOURCES = (
    REPO_ROOT / "services" / "core-control-plane" / "src",
    REPO_ROOT / "services" / "operator-service" / "src",
    REPO_ROOT / "services" / "document-ingestion-api" / "src",
    REPO_ROOT / "services" / "document-processing-worker" / "src",
    REPO_ROOT / "services" / "isolated-executor" / "src",
)
for source_root in (CONTRACT_SOURCE, *SERVICE_SOURCES):
    sys.path.insert(0, str(source_root))

from fdai_service_contracts import (  # noqa: E402
    CompatibilityError,
    ConsumerCodec,
    ProducerCodec,
    assert_additive_schema,
    delivery_checks,
    load_json_object,
    project_additive_fields,
    run_delivery_transition_harness,
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


class ReceiptSummary:
    """Proof-kind counts from validated persisted compatibility receipts."""

    __slots__ = ("focused_receipts", "live_receipts", "live_services")

    def __init__(self, *, focused_receipts: int, live_receipts: int, live_services: int) -> None:
        self.focused_receipts = focused_receipts
        self.live_receipts = live_receipts
        self.live_services = live_services


def validate(
    *,
    mode: str,
    receipts_path: Path | None = None,
    evidence_manifest_path: Path | None = None,
) -> None:
    """Validate the manifest, wire payloads, delivery traces, and transition receipts."""

    if mode not in {"focused", "live"}:
        raise CompatibilityError("compatibility mode must be focused or live")

    manifest = load_json_object(MANIFEST_PATH)
    summary = validate_manifest(manifest, repo_root=REPO_ROOT)
    contracts = _contract_map(manifest)
    _validate_wire_payloads(contracts)
    unsupported_major_rejection = _validate_codec_artifacts(manifest, contracts)
    _validate_delivery_traces()
    receipt_summary = _validate_upgrade_receipts(
        manifest,
        unsupported_major_rejection=unsupported_major_rejection,
        required_proof_kind=mode,
        receipts_path=receipts_path,
        evidence_manifest_path=evidence_manifest_path,
    )
    print(
        "check-service-compatibility: OK "
        f"(mode={mode} proof_kind={mode} services={summary.service_count} "
        f"contracts={summary.contract_count} matrix_edges={summary.matrix_edge_count} "
        f"mechanics_proofs={receipt_summary.focused_receipts} "
        f"live_proofs={receipt_summary.live_receipts} "
        f"live_service_proofs={receipt_summary.live_services})"
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


def _validate_codec_artifacts(
    manifest: Mapping[str, Any],
    contracts: Mapping[str, Mapping[str, Any]],
) -> bool:
    fixtures = _load_json_array(FIXTURE_ROOT / "wire-payloads.json")
    payloads = {
        (str(fixture["contract_id"]), str(fixture["producer_release"])): _mapping(
            fixture.get("payload"), "wire payload"
        )
        for fixture in fixtures
    }
    matrix = {
        str(_mapping(edge, "matrix edge")["contract_id"]): _mapping(edge, "matrix edge")
        for edge in _sequence(manifest.get("producer_consumer_matrix"), "matrix")
    }
    for contract_id, contract in contracts.items():
        producer_codecs = _mapping(contract.get("producer_codecs"), "producer_codecs")
        consumer_codecs = _mapping(contract.get("consumer_codecs"), "consumer_codecs")
        translators = _mapping(contract.get("translators", {}), "translators")
        edge = matrix[contract_id]
        supported_pairs = {
            (str(pair["producer_release"]), str(pair["consumer_release"]))
            for pair in (
                _mapping(item, "supported pair")
                for item in _sequence(edge.get("supported_pairs"), "supported_pairs")
            )
        }
        for producer_release in ("N-1", "N"):
            producer = _load_symbol(str(producer_codecs[producer_release]))
            if not isinstance(producer, ProducerCodec):
                raise CompatibilityError(f"{contract_id} producer codec has the wrong type")
            payload = _payload_for_release(
                contract_id,
                producer_release,
                payloads=payloads,
                translators=translators,
            )
            encoded = producer.encode(payload)
            for consumer_release in ("N-1", "N"):
                consumer = _load_symbol(str(consumer_codecs[consumer_release]))
                if not isinstance(consumer, ConsumerCodec):
                    raise CompatibilityError(f"{contract_id} consumer codec has the wrong type")
                if (producer_release, consumer_release) not in supported_pairs:
                    try:
                        consumer.decode(encoded)
                    except CompatibilityError:
                        continue
                    raise CompatibilityError(
                        f"{contract_id} consumer accepted unsupported pair "
                        f"{producer_release}->{consumer_release}"
                    )
                translated = encoded
                translator_ref = translators.get(f"{producer_release}->{consumer_release}")
                if translator_ref is not None:
                    translator = _load_translator(str(translator_ref))
                    translated_payload = _mapping(translator(payload), "translated wire payload")
                    translated = json.dumps(
                        translated_payload, separators=(",", ":"), sort_keys=True
                    ).encode()
                consumer.decode(translated)
        for consumer_release in ("N-1", "N"):
            consumer = _load_symbol(str(consumer_codecs[consumer_release]))
            if not isinstance(consumer, ConsumerCodec):
                raise CompatibilityError(f"{contract_id} consumer codec has the wrong type")
            accepted_release = next(
                release
                for release in ("N-1", "N")
                if str(
                    _mapping(
                        _mapping(contract.get("producer_schemas"), "producer_schemas")[release],
                        "producer schema",
                    )["version"]
                )
                in consumer.accepted_versions
            )
            major_probe = dict(
                _payload_for_release(
                    contract_id,
                    accepted_release,
                    payloads=payloads,
                    translators=translators,
                )
            )
            major_probe["schema_version"] = "2.0.0"
            encoded_probe = json.dumps(
                major_probe,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            try:
                consumer.decode(encoded_probe)
            except CompatibilityError:
                continue
            raise CompatibilityError(
                f"{contract_id} consumer {consumer_release} accepted unsupported major 2"
            )
    return True


def _payload_for_release(
    contract_id: str,
    release: str,
    *,
    payloads: Mapping[tuple[str, str], Mapping[str, Any]],
    translators: Mapping[str, Any],
) -> Mapping[str, Any]:
    payload = payloads.get((contract_id, release))
    if payload is not None:
        return payload
    current = payloads.get((contract_id, "N"))
    if current is None:
        raise CompatibilityError(f"{contract_id} has no executable wire payload")
    translator_ref = translators.get("N->N-1")
    if translator_ref is None:
        return current
    translator = _load_translator(str(translator_ref))
    return _mapping(translator(current), "translated wire payload")


def _load_symbol(reference: str) -> object:
    module_name, separator, symbol_name = reference.partition(":")
    if not separator or not module_name or not symbol_name:
        raise CompatibilityError(f"invalid artifact reference: {reference}")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, symbol_name)
    except (ImportError, AttributeError) as exc:
        raise CompatibilityError(f"cannot import artifact: {reference}") from exc


def _load_translator(reference: str) -> Callable[[Mapping[str, Any]], object]:
    symbol = _load_symbol(reference)
    if not callable(symbol):
        raise CompatibilityError(f"translator artifact is not callable: {reference}")
    return symbol


def _validate_delivery_traces() -> None:
    persisted = _load_json_array(FIXTURE_ROOT / "delivery-traces.json")
    expected: list[dict[str, object]] = []
    for service_id in SERVICE_IDS:
        receipts = run_delivery_transition_harness(service_id)
        checks = delivery_checks(receipts)
        if set(receipt.scenario for receipt in receipts) != {
            "commit_failure_redelivery",
            "restart_from_committed_offset",
            "rebalance_before_commit",
            "process_restart_duplicate",
        } or any(value is not True for value in checks.values()):
            raise CompatibilityError(f"{service_id} executable delivery transitions failed")
        expected.extend(
            {
                "service_id": service_id,
                "scenario": receipt.scenario,
                "committed_offset": receipt.committed_offset,
                "terminal_effects": receipt.terminal_effects,
                "duplicate_count": receipt.duplicate_count,
                "redelivery_count": receipt.redelivery_count,
            }
            for receipt in receipts
        )
    if sorted(persisted, key=_delivery_evidence_key) != sorted(
        expected,
        key=_delivery_evidence_key,
    ):
        raise CompatibilityError(
            "persisted delivery evidence does not match executable transition observations"
        )


def _delivery_evidence_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item.get("service_id")), str(item.get("scenario"))


def _validate_upgrade_receipts(
    manifest: Mapping[str, Any],
    *,
    unsupported_major_rejection: bool,
    required_proof_kind: str,
    evidence_manifest: Mapping[str, Any] | None = None,
    receipts_path: Path | None = None,
    evidence_manifest_path: Path | None = None,
) -> ReceiptSummary:
    receipt_contract = _mapping(manifest.get("upgrade_receipt"), "upgrade_receipt")
    schema = load_json_object(REPO_ROOT / str(receipt_contract["schema_path"]))
    if evidence_manifest is not None and evidence_manifest_path is not None:
        raise CompatibilityError("live evidence manifest must have one source")
    if evidence_manifest_path is not None:
        evidence_manifest = load_json_object(evidence_manifest_path)
    if evidence_manifest is not None:
        evidence_schema = load_json_object(
            REPO_ROOT / str(receipt_contract["evidence_manifest_schema_path"])
        )
        _validator(evidence_schema).validate(evidence_manifest)
    checks = _upgrade_checks(
        manifest,
        unsupported_major_rejection=unsupported_major_rejection,
    )
    fixtures = _load_json_array(receipts_path or FIXTURE_ROOT / "upgrade-receipts.json")
    live_services = {
        str(receipt.get("service_id"))
        for receipt in fixtures
        if receipt.get("proof_kind") == "live"
    }
    if required_proof_kind == "live" and live_services != SERVICE_IDS:
        raise CompatibilityError(
            "live certification requires verified live receipts for all five services"
        )
    expected_checks = {name: value for name, value in checks.items() if name != "offsets_preserved"}
    seen: set[tuple[str, str]] = set()
    for receipt in fixtures:
        _validator(schema).validate(receipt)
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind=required_proof_kind,
            evidence_manifest=evidence_manifest,
        )
        if (
            receipt.get("offsets_preserved") is not checks["offsets_preserved"]
            or receipt.get("checks") != expected_checks
        ):
            raise CompatibilityError(
                "persisted upgrade receipt does not match executable compatibility checks"
            )
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
    focused_receipts = sum(receipt.get("proof_kind") == "focused" for receipt in fixtures)
    live_receipts = sum(receipt.get("proof_kind") == "live" for receipt in fixtures)
    return ReceiptSummary(
        focused_receipts=focused_receipts,
        live_receipts=live_receipts,
        live_services=len(live_services),
    )


def _upgrade_checks(
    manifest: Mapping[str, Any],
    *,
    unsupported_major_rejection: bool | None = None,
) -> dict[str, bool]:
    receipts = tuple(
        receipt
        for service_id in sorted(SERVICE_IDS)
        for receipt in run_delivery_transition_harness(service_id)
    )
    checks = delivery_checks(receipts)
    checks.update(
        {
            "additive_fields": _additive_contracts_pass(manifest),
            "matrix": _matrix_is_complete(manifest),
            "unsupported_major_rejection": (
                _validate_codec_artifacts(manifest, _contract_map(manifest))
                if unsupported_major_rejection is None
                else unsupported_major_rejection
            ),
        }
    )
    return checks


def _additive_contracts_pass(manifest: Mapping[str, Any]) -> bool:
    for contract in _contract_map(manifest).values():
        if contract.get("compatibility_policy") != "additive-ignore-unknown":
            continue
        schemas = _mapping(contract.get("producer_schemas"), "producer_schemas")
        previous = _mapping(schemas["N-1"], "N-1 schema")
        current = _mapping(schemas["N"], "N schema")
        assert_additive_schema(
            load_json_object(REPO_ROOT / str(previous["path"])),
            load_json_object(REPO_ROOT / str(current["path"])),
            version_field="schema_version",
        )
    return True


def _matrix_is_complete(manifest: Mapping[str, Any]) -> bool:
    expected = {("N-1", "N-1"), ("N-1", "N"), ("N", "N-1"), ("N", "N")}
    for edge_value in _sequence(manifest.get("producer_consumer_matrix"), "matrix"):
        edge = _mapping(edge_value, "matrix edge")
        classified = {
            (str(pair["producer_release"]), str(pair["consumer_release"]))
            for key in ("supported_pairs", "unsupported_pairs")
            for pair in (
                _mapping(item, "matrix pair") for item in _sequence(edge.get(key, []), key)
            )
        }
        if classified != expected:
            return False
    return True


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


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise CompatibilityError(f"{name} must be an array")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    """Run the compatibility gate as a command-line check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("focused", "live"), required=True)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--evidence-manifest", type=Path)
    args = parser.parse_args(argv)

    try:
        validate(
            mode=args.mode,
            receipts_path=args.receipts,
            evidence_manifest_path=args.evidence_manifest,
        )
    except (CompatibilityError, KeyError, SchemaError, ValidationError) as exc:
        print(f"check-service-compatibility: ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

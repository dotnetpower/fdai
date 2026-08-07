"""Five-service N/N-1 compatibility and independent transition evidence tests."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fdai_service_contracts import (
    CompatibilityError,
    assert_additive_schema,
    ensure_supported_version,
    load_json_object,
    validate_delivery_trace,
    validate_manifest,
    validate_peer_upgrade_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT
    / "service-contracts"
    / "src"
    / "fdai_service_contracts"
    / "compatibility-manifest.json"
)
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "services"
CHECKER_PATH = REPO_ROOT / "scripts" / "quality" / "architecture" / "check-service-compatibility.py"
SERVICE_IDS = {
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
}
REQUIRED_PAIRS = {
    ("N-1", "N-1"),
    ("N-1", "N"),
    ("N", "N-1"),
    ("N", "N"),
}


def _manifest() -> dict[str, Any]:
    return load_json_object(MANIFEST_PATH)


def _fixture_array(name: str) -> list[dict[str, Any]]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


def _checker_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_service_compatibility", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_and_focused_fixture_gate_pass() -> None:
    summary = validate_manifest(_manifest(), repo_root=REPO_ROOT)
    _checker_module().validate()

    assert summary.service_count == 5
    assert summary.contract_count == 7
    assert summary.matrix_edge_count == 7


def test_matrix_covers_every_release_pair_for_every_contract() -> None:
    manifest = _manifest()
    matrix = manifest["producer_consumer_matrix"]
    assert isinstance(matrix, list)

    for edge in matrix:
        assert isinstance(edge, dict)
        pairs = {
            (pair["producer_release"], pair["consumer_release"]) for pair in edge["supported_pairs"]
        }
        assert pairs == REQUIRED_PAIRS


def test_missing_new_producer_old_consumer_pair_fails_closed() -> None:
    manifest = _manifest()
    matrix = manifest["producer_consumer_matrix"]
    assert isinstance(matrix, list)
    edge = matrix[0]
    assert isinstance(edge, dict)
    pairs = edge["supported_pairs"]
    assert isinstance(pairs, list)
    edge["supported_pairs"] = [
        pair for pair in pairs if pair != {"producer_release": "N", "consumer_release": "N-1"}
    ]

    with pytest.raises(CompatibilityError, match="each N/N-1 pair once"):
        validate_manifest(manifest, repo_root=REPO_ROOT)


def test_additive_fields_are_allowed_but_new_required_fields_are_rejected() -> None:
    previous = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
    }
    additive = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}, "digest": {"type": "string"}},
    }
    breaking = copy.deepcopy(additive)
    breaking["required"] = ["id", "digest"]

    assert_additive_schema(previous, additive)
    with pytest.raises(CompatibilityError, match="adds required fields"):
        assert_additive_schema(previous, breaking)


def test_unsupported_major_is_rejected() -> None:
    assert str(ensure_supported_version("1.9.0", 1)) == "1.9.0"
    with pytest.raises(CompatibilityError, match="unsupported major 2"):
        ensure_supported_version("2.0.0", 1)


def test_duplicate_and_reordered_delivery_converges_for_all_five_services() -> None:
    traces = _fixture_array("delivery-traces.json")
    assert {trace["service_id"] for trace in traces} == SERVICE_IDS

    for trace in traces:
        attempts = trace["attempts"]
        assert isinstance(attempts, list)
        result = validate_delivery_trace(attempts)
        assert result.duplicate_count == 2
        assert len(result.accepted_idempotency_keys) == 1


def test_idempotency_collision_and_duplicate_terminal_effect_fail_closed() -> None:
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    collision = [
        {
            "sequence": 0,
            "idempotency_key": "same",
            "payload_digest": digest_a,
            "terminal_effect": False,
        },
        {
            "sequence": 1,
            "idempotency_key": "same",
            "payload_digest": digest_b,
            "terminal_effect": False,
        },
    ]
    duplicate_effect = [
        {
            "sequence": 0,
            "idempotency_key": "same",
            "payload_digest": digest_a,
            "terminal_effect": True,
        },
        {
            "sequence": 1,
            "idempotency_key": "same",
            "payload_digest": digest_a,
            "terminal_effect": True,
        },
    ]

    with pytest.raises(CompatibilityError, match="idempotency collision"):
        validate_delivery_trace(collision)
    with pytest.raises(CompatibilityError, match="duplicate terminal effect"):
        validate_delivery_trace(duplicate_effect)


def test_each_service_has_valid_independent_migration_and_rollback_receipts() -> None:
    manifest = _manifest()
    receipts = _fixture_array("upgrade-receipts.json")
    identities: set[tuple[object, object]] = set()

    for receipt in receipts:
        validate_peer_upgrade_receipt(manifest, receipt)
        identities.add((receipt["service_id"], receipt["direction"]))

    assert identities == {
        (service_id, direction)
        for service_id in SERVICE_IDS
        for direction in ("migration", "rollback")
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("peer_version", "peer versions changed"),
        ("peer_restart", "restarted a peer"),
        ("matrix_digest", "matrix digest"),
        ("major", "unsupported major 2"),
    ],
)
def test_upgrade_receipt_tampering_fails_closed(mutation: str, message: str) -> None:
    manifest = _manifest()
    receipt = copy.deepcopy(_fixture_array("upgrade-receipts.json")[0])

    if mutation == "peer_version":
        peers_after = receipt["peer_versions_after"]
        assert isinstance(peers_after, dict)
        peers_after["operator-service"] = "1.1.0"
    elif mutation == "peer_restart":
        receipt["peer_restart_count"] = 1
    elif mutation == "matrix_digest":
        receipt["matrix_digest"] = "sha256:" + "f" * 64
    else:
        peers_before = receipt["peer_versions_before"]
        peers_after = receipt["peer_versions_after"]
        assert isinstance(peers_before, dict) and isinstance(peers_after, dict)
        peers_before["operator-service"] = "2.0.0"
        peers_after["operator-service"] = "2.0.0"

    with pytest.raises(CompatibilityError, match=message):
        validate_peer_upgrade_receipt(manifest, receipt)


def test_contract_sdk_remains_free_of_service_implementation_imports() -> None:
    source_root = REPO_ROOT / "service-contracts" / "src" / "fdai_service_contracts"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))

    assert "from fdai." not in source
    assert "import fdai." not in source


def test_wire_fixtures_cover_each_contract_and_all_five_services() -> None:
    manifest = _manifest()
    contracts = manifest["contracts"]
    assert isinstance(contracts, list)
    fixture_contracts = {fixture["contract_id"] for fixture in _fixture_array("wire-payloads.json")}
    participants = {
        service_id
        for contract in contracts
        for service_id in (contract["producer"], contract["consumer"])
    }

    assert fixture_contracts == {contract["id"] for contract in contracts}
    assert participants == SERVICE_IDS

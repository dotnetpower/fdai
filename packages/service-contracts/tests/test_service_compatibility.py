"""Five-service N/N-1 compatibility and independent transition evidence tests."""

from __future__ import annotations

import copy
import importlib.util
import json
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fdai_service_contracts import (
    CompatibilityError,
    ConsumerCodec,
    ServiceDescriptor,
    ServiceKind,
    assert_additive_schema,
    canonical_digest,
    delivery_checks,
    ensure_supported_version,
    generate_upgrade_receipts,
    load_json_object,
    load_manifest_codec,
    matrix_digest,
    run_delivery_transition_harness,
    validate_manifest,
    validate_peer_upgrade_receipt,
)
from fdai_service_contracts.codec import MAX_WIRE_BYTES
from jsonschema.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPO_ROOT
    / "packages"
    / "service-contracts"
    / "src"
    / "fdai_service_contracts"
    / "compatibility-manifest.json"
)
INDEPENDENT_SERVICES_PATH = REPO_ROOT / "config" / "independent-services.json"
FIXTURE_ROOT = REPO_ROOT / "packages" / "service-contracts" / "tests" / "fixtures" / "services"
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


def _generated_upgrade_receipts(manifest: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    checker = _checker_module()
    upgrade_checks = checker._upgrade_checks
    checks = upgrade_checks(manifest)
    assert all(checks.values())
    return generate_upgrade_receipts(manifest, checks=checks)


def test_manifest_and_focused_fixture_gate_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = validate_manifest(_manifest(), repo_root=REPO_ROOT)
    _checker_module().validate(mode="focused")

    assert summary.service_count == 5
    assert summary.contract_count == 7
    assert summary.matrix_edge_count == 7
    output = capsys.readouterr().out
    assert "mode=focused" in output
    assert "proof_kind=focused" in output
    assert "mechanics_proofs=10" in output
    assert "live_proofs=0" in output
    assert "live_service_proofs=0" in output
    assert "receipts=" not in output


def test_service_versions_match_real_n_and_n_minus_one_distributions() -> None:
    manifest_services = {service["id"]: service for service in _manifest()["services"]}
    independent = json.loads(INDEPENDENT_SERVICES_PATH.read_text(encoding="utf-8"))
    transition = independent["release_transition"]

    assert transition == {
        "n_distribution_version": "0.1.3",
        "n_source_revision": "396a095a03af87b8d54026218068528059379a5a",
        "n_minus_one_distribution_version": "0.1.2",
        "n_minus_one_source_revision": "352c8d1e661a6a53f0958767550fd57c2b975706",
        "local_n_minus_one_source_revision": "9f1234f93d356dedbddcb3b88aa7bc4da38b2dc2",
        "n_contract_set_version": "1.1.0",
        "n_minus_one_contract_set_version": "1.0.0",
    }

    for service in independent["services"]:
        package = tomllib.loads(
            (REPO_ROOT / service["target_package"] / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        declared = manifest_services[service["id"]]
        assert service["distribution"] == package["name"] == declared["distribution"]
        assert (
            service["distribution_version"]
            == package["version"]
            == declared["distribution_version"]
            == "0.1.3"
        )
        assert service["previous_distribution_version"] == "0.1.2"
        assert declared["previous_distribution_version"] == "0.1.2"
        assert service["contract_set_version"] == declared["current_contract_set_version"]
        assert declared["previous_contract_set_version"] == "1.0.0"
        assert "previous_version" not in declared
        assert "current_version" not in declared

    assert independent["current_baseline"]["independent_upgrade_and_rollback_proofs"] == 5
    assert independent["compatibility_retirements"] == {
        "legacy_isolated_executor_module": "retired",
        "ingestion_cohost": "retired",
    }

    descriptor = ServiceDescriptor(
        service_id="core-control-plane",
        distribution="fdai-core-control-plane",
        image="fdai-core-control-plane",
        entrypoint="fdai-core-control-plane",
        kind=ServiceKind.CONTROL_PLANE,
    )
    assert descriptor.distribution_version == "0.1.3"
    assert descriptor.previous_distribution_version == "0.1.2"
    assert descriptor.release_label == "N"
    assert descriptor.contract_set_version == "1.1.0"


def test_checker_rejects_missing_persisted_transition_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    wire_payloads = (FIXTURE_ROOT / "wire-payloads.json").read_text(encoding="utf-8")
    (tmp_path / "wire-payloads.json").write_text(wire_payloads, encoding="utf-8")
    monkeypatch.setattr(checker, "FIXTURE_ROOT", tmp_path)

    with pytest.raises(CompatibilityError, match="cannot load JSON array"):
        checker.validate(mode="focused")


def test_checker_rejects_self_attested_receipt_when_executable_check_fails() -> None:
    checker = _checker_module()

    with pytest.raises(
        CompatibilityError,
        match="persisted upgrade receipt does not match executable compatibility checks",
    ):
        checker._validate_upgrade_receipts(
            _manifest(),
            unsupported_major_rejection=False,
            required_proof_kind="focused",
            evidence_manifest=None,
        )


def test_matrix_covers_every_release_pair_for_every_contract() -> None:
    manifest = _manifest()
    matrix = manifest["producer_consumer_matrix"]
    assert isinstance(matrix, list)

    for edge in matrix:
        assert isinstance(edge, dict)
        pairs = {
            (pair["producer_release"], pair["consumer_release"]) for pair in edge["supported_pairs"]
        }
        unsupported = {
            (pair["producer_release"], pair["consumer_release"])
            for pair in edge.get("unsupported_pairs", [])
        }
        assert pairs | unsupported == REQUIRED_PAIRS
        assert pairs.isdisjoint(unsupported)

    executor_receipt = next(edge for edge in matrix if edge["contract_id"] == "executor-receipt")
    assert executor_receipt["unsupported_pairs"] == [
        {
            "producer_release": "N",
            "consumer_release": "N-1",
            "reason": "executor receipt 1.1.0 requires Core 1.1.0 before Executor 1.1.0",
        }
    ]


def test_semantic_turn_contract_requires_verified_evidence_for_answer() -> None:
    from fdai_service_contracts import (
        OperatorRole,
        SemanticTurnDisposition,
        SemanticTurnPrincipal,
        SemanticTurnResult,
    )

    principal = SemanticTurnPrincipal(subject_id="operator-1", roles=(OperatorRole.READER,))
    assert principal.roles == (OperatorRole.READER,)
    with pytest.raises(ValueError, match="complete verified evidence"):
        SemanticTurnResult(
            disposition=SemanticTurnDisposition.ANSWERED,
            reason_code="semantic_execution_completed",
            session_id="session-1",
            turn_id="turn-1",
            turn_sequence=1,
        )


def test_semantic_turn_principal_rejects_more_roles_than_wire_schema() -> None:
    from pydantic import ValidationError

    from fdai_service_contracts import OperatorRole, SemanticTurnPrincipal

    with pytest.raises(ValidationError):
        SemanticTurnPrincipal(
            subject_id="operator-1",
            roles=(
                OperatorRole.READER,
                OperatorRole.CONTRIBUTOR,
                OperatorRole.APPROVER,
                OperatorRole.OWNER,
                OperatorRole.BREAK_GLASS,
            ),
        )


def test_semantic_contracts_cannot_downgrade_to_n_minus_one() -> None:
    from fdai_service_contracts.translators import (
        core_operator_projection_1_2_to_1_0,
        operator_core_request_1_2_to_1_0,
    )

    with pytest.raises(CompatibilityError, match="cannot be downgraded"):
        operator_core_request_1_2_to_1_0({"request_kind": "semantic_query", "semantic_turn": {}})
    with pytest.raises(CompatibilityError, match="cannot be downgraded"):
        core_operator_projection_1_2_to_1_0({"semantic_result": {}})


def test_missing_pair_without_explicit_unsupported_rollout_fails_closed() -> None:
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

    with pytest.raises(CompatibilityError, match="classify each N/N-1 pair once"):
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


@pytest.mark.parametrize(
    ("keyword", "previous_value", "current_value"),
    [
        ("maxLength", 32, 16),
        ("minLength", 1, 2),
        ("maximum", 100, 99),
        ("minimum", 0, 1),
        ("pattern", None, "^[a-z]+$"),
        ("format", None, "uuid"),
        ("const", None, "fixed"),
        ("additionalProperties", True, False),
    ],
)
def test_additive_schema_rejects_new_or_narrower_constraints(
    keyword: str,
    previous_value: object,
    current_value: object,
) -> None:
    previous: dict[str, object] = {"type": "string"}
    current: dict[str, object] = {"type": "string"}
    if previous_value is not None:
        previous[keyword] = previous_value
    if current_value is not None:
        current[keyword] = current_value

    with pytest.raises(CompatibilityError, match=keyword):
        assert_additive_schema(previous, current)


@pytest.mark.parametrize("keyword", ["allOf", "anyOf", "oneOf", "not"])
def test_additive_schema_rejects_new_composition_constraints(keyword: str) -> None:
    with pytest.raises(CompatibilityError, match=keyword):
        assert_additive_schema(
            {"type": "object"},
            {"type": "object", keyword: [{"required": ["new_field"]}]},
        )


def test_unsupported_major_is_rejected() -> None:
    assert str(ensure_supported_version("1.9.0", 1)) == "1.9.0"
    with pytest.raises(CompatibilityError, match="unsupported major 2"):
        ensure_supported_version("2.0.0", 1)


def test_real_codecs_exercise_supported_pairs_and_reject_unsupported_versions() -> None:
    manifest = _manifest()
    checker = _checker_module()

    assert checker._validate_codec_artifacts(
        manifest,
        checker._contract_map(manifest),
    )


def test_executor_receipt_consumer_enforces_versions_and_wire_size() -> None:
    payload = next(
        fixture["payload"]
        for fixture in _fixture_array("wire-payloads.json")
        if fixture["contract_id"] == "executor-receipt" and fixture["producer_release"] == "N-1"
    )
    codec = ConsumerCodec("executor-receipt", "N", ("1.0.0", "1.1.0"))

    assert codec.decode_mapping(payload) == payload

    wrong_version = {**payload, "schema_version": "1.0.1"}
    with pytest.raises(CompatibilityError, match="rejects version"):
        codec.decode_mapping(wrong_version)

    oversized = {**payload, "reason": "x" * MAX_WIRE_BYTES}
    with pytest.raises(CompatibilityError, match="exceeds 256 KiB"):
        codec.decode_mapping(oversized)


@pytest.mark.parametrize("service_id", sorted(SERVICE_IDS))
def test_delivery_transition_harness_proves_required_restart_scenarios(service_id: str) -> None:
    receipts = run_delivery_transition_harness(service_id)
    by_scenario = {receipt.scenario: receipt for receipt in receipts}

    assert set(by_scenario) == {
        "commit_failure_redelivery",
        "restart_from_committed_offset",
        "rebalance_before_commit",
        "process_restart_duplicate",
    }
    assert by_scenario["commit_failure_redelivery"].duplicate_count == 1
    assert by_scenario["rebalance_before_commit"].terminal_effects == 1
    assert by_scenario["process_restart_duplicate"].terminal_effects == 1
    assert by_scenario["restart_from_committed_offset"].committed_offset == 1
    assert all(delivery_checks(receipts).values())


def test_each_service_has_valid_independent_migration_and_rollback_receipts() -> None:
    manifest = _manifest()
    receipts = _fixture_array("upgrade-receipts.json")
    checker = _checker_module()
    checks = checker._upgrade_checks(manifest)
    identities: set[tuple[object, object]] = set()

    for receipt in receipts:
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="focused",
        )
        assert receipt["offsets_preserved"] is checks["offsets_preserved"]
        assert receipt["checks"] == {
            name: value for name, value in checks.items() if name != "offsets_preserved"
        }
        identities.add((receipt["service_id"], receipt["direction"]))

    assert identities == {
        (service_id, direction)
        for service_id in SERVICE_IDS
        for direction in ("migration", "rollback")
    }
    executor_migration = next(
        receipt
        for receipt in receipts
        if receipt["service_id"] == "isolated-executor" and receipt["direction"] == "migration"
    )
    core_rollback = next(
        receipt
        for receipt in receipts
        if receipt["service_id"] == "core-control-plane" and receipt["direction"] == "rollback"
    )
    assert executor_migration["peer_versions_before"]["core-control-plane"] == "1.1.0"
    assert core_rollback["peer_versions_before"]["isolated-executor"] == "1.0.0"


def test_focused_receipt_remains_valid_without_live_observations() -> None:
    manifest = _manifest()
    receipt = copy.deepcopy(_generated_upgrade_receipts(manifest)[0])

    assert receipt["proof_kind"] == "focused"
    assert "observation_refs" not in receipt
    validate_peer_upgrade_receipt(
        manifest,
        receipt,
        required_proof_kind="focused",
    )

    with pytest.raises(CompatibilityError, match="required proof_kind live"):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="live",
        )


def _bound_live_evidence(receipt: dict[str, Any]) -> dict[str, Any]:
    run_id = "service-compatibility-run-42"
    source = {
        "repository": "example/fdai",
        "revision": "a" * 40,
        "workflow": "service-live-compatibility",
    }
    source_digest = canonical_digest(source)
    artifacts: list[dict[str, Any]] = []
    observation_refs: dict[str, str] = {}
    for kind in ("health", "identity", "image", "offset", "schema", "source", "topology"):
        content = {
            "kind": kind,
            "observed": True,
            "service_id": receipt["service_id"],
        }
        artifact = {
            "kind": kind,
            "service_id": receipt["service_id"],
            "run_id": run_id,
            "source_digest": source_digest,
            "content_digest": canonical_digest(content),
            "content": content,
        }
        artifact["ref"] = canonical_digest(artifact)
        artifacts.append(artifact)
        observation_refs[kind] = artifact["ref"]
    evidence_manifest = {
        "manifest_version": "1.0.0",
        "run_id": run_id,
        "source": source,
        "source_digest": source_digest,
        "artifacts": artifacts,
    }
    receipt.update(
        {
            "proof_kind": "live",
            "evidence_manifest_digest": canonical_digest(evidence_manifest),
            "evidence_run_id": run_id,
            "evidence_source_digest": source_digest,
            "observation_refs": observation_refs,
        }
    )
    return evidence_manifest


def test_live_receipt_requires_exact_immutable_observation_refs() -> None:
    manifest = _manifest()
    receipt = copy.deepcopy(_generated_upgrade_receipts(manifest)[0])
    receipt["proof_kind"] = "live"
    schema = load_json_object(
        REPO_ROOT
        / "packages"
        / "service-contracts"
        / "src"
        / "fdai_service_contracts"
        / "schemas"
        / "service-upgrade-receipt"
        / "1.0.0.json"
    )

    with pytest.raises(ValidationError, match="evidence_manifest_digest"):
        _checker_module()._validator(schema).validate(receipt)

    with pytest.raises(CompatibilityError, match="must name exact"):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="live",
        )

    evidence_manifest = _bound_live_evidence(receipt)
    _checker_module()._validator(schema).validate(receipt)
    with pytest.raises(CompatibilityError, match="persisted evidence manifest"):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="live",
        )
    validate_peer_upgrade_receipt(
        manifest,
        receipt,
        required_proof_kind="live",
        evidence_manifest=evidence_manifest,
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("content", "content digest"),
        ("artifact_ref", "artifact digest"),
        ("run", "run binding"),
        ("source", "source binding"),
        ("manifest", "manifest digest"),
    ],
)
def test_live_receipt_rejects_unbound_evidence(
    mutation: str,
    message: str,
) -> None:
    manifest = _manifest()
    receipt = copy.deepcopy(_generated_upgrade_receipts(manifest)[0])
    evidence_manifest = _bound_live_evidence(receipt)
    artifact = evidence_manifest["artifacts"][0]

    if mutation == "content":
        artifact["content"] = {"observed": False}
    elif mutation == "artifact_ref":
        artifact["ref"] = "sha256:" + "f" * 64
        receipt["observation_refs"]["health"] = artifact["ref"]
    elif mutation == "run":
        artifact["run_id"] = "another-run"
    elif mutation == "source":
        artifact["source_digest"] = "sha256:" + "e" * 64
    else:
        receipt["evidence_manifest_digest"] = "sha256:" + "d" * 64
    if mutation != "manifest":
        receipt["evidence_manifest_digest"] = canonical_digest(evidence_manifest)

    with pytest.raises(CompatibilityError, match=message):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="live",
            evidence_manifest=evidence_manifest,
        )


def test_live_receipt_rejects_digest_valid_but_unobserved_content() -> None:
    manifest = _manifest()
    receipt = copy.deepcopy(_generated_upgrade_receipts(manifest)[0])
    evidence_manifest = _bound_live_evidence(receipt)
    artifact = evidence_manifest["artifacts"][0]
    old_ref = artifact["ref"]
    artifact["content"]["observed"] = False
    artifact["content_digest"] = canonical_digest(artifact["content"])
    artifact["ref"] = canonical_digest(
        {key: value for key, value in artifact.items() if key != "ref"}
    )
    receipt["observation_refs"][artifact["kind"]] = artifact["ref"]
    assert receipt["observation_refs"][artifact["kind"]] != old_ref
    receipt["evidence_manifest_digest"] = canonical_digest(evidence_manifest)

    with pytest.raises(CompatibilityError, match="observation is invalid"):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="live",
            evidence_manifest=evidence_manifest,
        )


def test_live_checker_requires_verified_receipts_for_all_five_services() -> None:
    with pytest.raises(
        CompatibilityError,
        match="live certification requires verified live receipts for all five services",
    ):
        _checker_module().validate(mode="live")


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
    receipt = copy.deepcopy(_generated_upgrade_receipts(manifest)[0])

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

    if mutation != "matrix_digest":
        receipt["matrix_digest"] = matrix_digest(manifest)

    with pytest.raises(CompatibilityError, match=message):
        validate_peer_upgrade_receipt(
            manifest,
            receipt,
            required_proof_kind="focused",
        )


def test_contract_sdk_remains_free_of_service_implementation_imports() -> None:
    source_root = REPO_ROOT / "packages" / "service-contracts" / "src" / "fdai_service_contracts"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))

    assert "from fdai." not in source
    assert "import fdai." not in source


def test_checker_fails_when_declared_codec_artifact_is_not_importable() -> None:
    manifest = _manifest()
    contracts = manifest["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    producer_codecs = contract["producer_codecs"]
    assert isinstance(producer_codecs, dict)
    producer_codecs["N"] = "missing.service.codec:NOT_PRESENT"
    checker = _checker_module()

    with pytest.raises(CompatibilityError, match="cannot import artifact"):
        checker._validate_codec_artifacts(manifest, checker._contract_map(manifest))


def test_core_uses_manifest_declared_executor_receipt_codec_object() -> None:
    from fdai_core_service.contract_codecs import EXECUTOR_RECEIPT_CONSUMER_V11

    from fdai.runtime import isolated_executor_client

    declared = load_manifest_codec(
        "executor-receipt",
        artifact_kind="consumer_codecs",
        release="N",
    )

    assert declared is EXECUTOR_RECEIPT_CONSUMER_V11
    assert isolated_executor_client._EXECUTOR_RECEIPT_CONSUMER is declared


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

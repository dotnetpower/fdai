from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "independent-services.json"
TRANSITION_EVIDENCE_PATH = (
    REPO_ROOT / "config" / "independent-service-local-transition-evidence.json"
)
CHECKER_PATH = REPO_ROOT / "scripts/quality/architecture/check-independent-services.py"


def _checker_module():
    spec = importlib.util.spec_from_file_location("check_independent_services", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_names_exactly_five_independent_services() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["target_service_count"] == 5
    assert [service["id"] for service in manifest["services"]] == [
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    ]
    assert len({service["target_package"] for service in manifest["services"]}) == 5
    assert len({service["target_image"] for service in manifest["services"]}) == 5
    assert len({service["target_terraform_root"] for service in manifest["services"]}) == 5
    assert manifest["release_transition"] == {
        "n_distribution_version": "0.1.3",
        "n_source_revision": "396a095a03af87b8d54026218068528059379a5a",
        "n_minus_one_distribution_version": "0.1.2",
        "n_minus_one_source_revision": "352c8d1e661a6a53f0958767550fd57c2b975706",
        "local_n_minus_one_source_revision": "9f1234f93d356dedbddcb3b88aa7bc4da38b2dc2",
        "n_contract_set_version": "1.1.0",
        "n_minus_one_contract_set_version": "1.0.0",
    }


def test_manifest_requires_zero_cross_service_implementation_imports() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["independence_targets"] == {
        "cross_service_implementation_imports": 0,
        "service_python_distributions": 5,
        "service_images": 5,
        "service_terraform_roots": 5,
        "service_migration_branches": 5,
        "independent_upgrade_and_rollback_proofs": 5,
    }


def test_contract_sdk_uses_final_package_layout() -> None:
    assert (REPO_ROOT / "packages" / "service-contracts" / "pyproject.toml").is_file()
    assert not (REPO_ROOT / "service-contracts").exists()


def test_core_source_uses_final_service_root() -> None:
    core_source = REPO_ROOT / "services" / "core-control-plane" / "src" / "fdai"
    assert (core_source / "runtime" / "bootstrap.py").is_file()
    assert (core_source / "agents" / "_framework" / "pantheon.py").is_file()
    assert not (REPO_ROOT / "src" / "fdai").exists()


def test_root_is_workspace_orchestration_only() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["package"] is False
    assert project["project"]["dependencies"] == []
    assert "build-system" not in project
    assert "scripts" not in project["project"]


def test_runtime_packages_own_tests_and_root_keeps_integration_only() -> None:
    for service_id in (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    ):
        assert (REPO_ROOT / "services" / service_id / "tests").is_dir()
    assert (REPO_ROOT / "packages" / "service-contracts" / "tests").is_dir()
    assert {path.name for path in (REPO_ROOT / "tests").iterdir()} == {"integration"}


def test_manifest_records_completed_local_layout_assurance() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    evidence = manifest["local_layout_evidence"]
    statuses = {item["id"]: item["status"] for item in manifest["work_packages"]}

    assert evidence["state"] == "completed"
    assert evidence["independent_critique_rounds"] >= 33
    assert evidence["medium_or_higher_local_residuals"] == 0
    assert evidence["pending_parallel_lanes"] == []
    assert statuses["IS-04"] == "completed"
    assert statuses["IS-06"] == "completed"
    assert statuses["IS-07"] == "completed"
    assert statuses["IS-08"] == "completed"
    assert statuses["IS-09"] == "completed"

    deployment = manifest["local_deployment_evidence"]
    assert deployment == {
        "state": "completed",
        "service_terraform_roots": 5,
        "isolated_backend_keys": 5,
        "state_migration_contracts": 5,
        "peer_state_isolation_mechanics": "passed",
        "protected_plan_apply_contract": "passed",
        "focused_tests_passed": 113,
    }

    final_verification = manifest["program_final_verification"]
    assert final_verification["completion_basis"] == "local-executable-evidence"
    assert final_verification["status"] == "completed"
    assert final_verification["required_before_work_package"] == "IS-09"
    assert final_verification["remote_targets"] == {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
    }
    assert final_verification["accepted_remote_evidence"] == {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
    }
    assert final_verification["remote_attestation"] == {
        "state": "verified",
        "evidence_source_revision": "a721d1ae587af73b8f32986fe3b54acaae400b63",
        "bundle_path": "config/independent-service-remote-evidence.attestation.jsonl",
        "signer_workflow": "dotnetpower/fdai/.github/workflows/remote-evidence-attest.yml",
    }

    transition = manifest["local_upgrade_and_rollback_evidence"]
    assert transition["state"] == "completed"
    assert transition["evidence_path"] == TRANSITION_EVIDENCE_PATH.relative_to(REPO_ROOT).as_posix()
    assert transition["service_artifact_pairs"] == 5
    assert transition["focused_transition_receipts"] == 10
    assert transition["independent_upgrade_and_rollback_proofs"] == 5
    assert transition["peer_restart_count"] == 0
    assert transition["duplicate_terminal_effects"] == 0
    assert transition["offsets_preserved"] is True


def test_local_transition_evidence_covers_five_stable_artifact_pairs() -> None:
    evidence = json.loads(TRANSITION_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert evidence["proof_kind"] == "local"
    assert len(evidence["services"]) == 5
    assert {item["id"] for item in evidence["services"]} == {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    assert all(item["peer_stable"] is True for item in evidence["services"])
    assert all(
        item["transition_sequence"] == ["0.1.3", "0.1.2", "0.1.3"] for item in evidence["services"]
    )
    assert evidence["summary"]["independent_upgrade_and_rollback_proofs"] == 5


def test_checker_rejects_tampered_local_transition_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(TRANSITION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    evidence["services"][0]["n"]["image_sha256"] = "sha256:invalid"
    tampered = tmp_path / "evidence.json"
    tampered.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(checker, "LOCAL_TRANSITION_EVIDENCE_PATH", tampered)

    with pytest.raises(ValueError, match="artifact digest is invalid"):
        checker._validate_local_transition_evidence(manifest)


def test_checker_rejects_extra_local_transition_service_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(TRANSITION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    evidence["services"][0]["backend_resource_group"] = "deployment-specific"
    tampered = tmp_path / "evidence.json"
    tampered.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(checker, "LOCAL_TRANSITION_EVIDENCE_PATH", tampered)

    with pytest.raises(ValueError, match="service fields are invalid"):
        checker._validate_local_transition_evidence(manifest)


def test_is09_cannot_complete_while_remote_verification_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    next(item for item in manifest["work_packages"] if item["id"] == "IS-09")["status"] = (
        "completed"
    )
    manifest["program_final_verification"]["status"] = "deferred"
    manifest["program_final_verification"]["remote_attestation"]["state"] = "pending"
    manifest["program_final_verification"]["remote_attestation"]["evidence_source_revision"] = ""

    with pytest.raises(ValueError, match="IS-09 cannot complete"):
        checker._validate_program_final_verification(manifest)


def test_is09_cannot_complete_before_layout_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    next(item for item in manifest["work_packages"] if item["id"] == "IS-08")["status"] = (
        "in_progress"
    )
    next(item for item in manifest["work_packages"] if item["id"] == "IS-09")["status"] = (
        "completed"
    )
    manifest["program_final_verification"]["status"] = "completed"
    manifest["program_final_verification"]["accepted_remote_evidence"] = {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
    }
    monkeypatch.setattr(checker, "_validate_remote_attestation", lambda *_args: None)
    monkeypatch.setattr(checker, "_validate_completed_remote_evidence", lambda *_args: None)

    with pytest.raises(ValueError, match="before IS-07 and IS-08"):
        checker._validate_program_final_verification(manifest)


def test_completed_program_verification_requires_all_remote_evidence() -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["program_final_verification"]["status"] = "completed"
    manifest["program_final_verification"]["accepted_remote_evidence"] = {
        "service_plan_apply_receipts": 0,
        "service_upgrade_and_rollback_proofs": 0,
    }

    with pytest.raises(ValueError, match="requires all remote evidence"):
        checker._validate_program_final_verification(manifest)


def test_completed_program_verification_requires_persisted_remote_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["program_final_verification"]["status"] = "completed"
    manifest["program_final_verification"]["accepted_remote_evidence"] = {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
    }
    monkeypatch.setattr(checker, "_validate_remote_attestation", lambda *_args: None)
    monkeypatch.setattr(checker, "REMOTE_EVIDENCE_PATH", tmp_path / "missing.json")

    with pytest.raises(ValueError, match="cannot load remote service evidence"):
        checker._validate_program_final_verification(manifest)


def test_completed_program_verification_requires_persisted_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["program_final_verification"]["status"] = "completed"
    manifest["program_final_verification"]["accepted_remote_evidence"] = {
        "service_plan_apply_receipts": 5,
        "service_upgrade_and_rollback_proofs": 5,
    }
    monkeypatch.setattr(checker, "_validate_remote_attestation", lambda *_args: None)
    remote = tmp_path / "remote.json"
    remote.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REMOTE_EVIDENCE_PATH", remote)
    monkeypatch.setattr(checker, "LIVE_RECEIPTS_PATH", tmp_path / "missing-receipts.json")
    monkeypatch.setattr(
        checker,
        "_validate_remote_service_evidence",
        lambda _manifest, _evidence: SimpleNamespace(
            service_plan_apply_receipts=5,
            service_upgrade_and_rollback_proofs=5,
            protected_plan_runs=15,
            protected_apply_runs=15,
            peer_isolation_receipts=30,
        ),
    )

    with pytest.raises(ValueError, match="cannot load live service receipts"):
        checker._validate_program_final_verification(manifest)


def test_completed_program_verification_requires_verified_attestation() -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    policy = manifest["program_final_verification"]
    policy["status"] = "completed"
    policy["remote_attestation"]["state"] = "pending"
    policy["remote_attestation"]["evidence_source_revision"] = ""

    with pytest.raises(ValueError, match="completed program-final attestation is invalid"):
        checker._validate_remote_attestation(policy)


def test_completed_program_verification_rechecks_all_remote_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    remote = tmp_path / "remote.json"
    remote.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REMOTE_EVIDENCE_PATH", remote)
    monkeypatch.setattr(
        checker,
        "_validate_remote_service_evidence",
        lambda _manifest, _evidence: SimpleNamespace(
            service_plan_apply_receipts=5,
            service_upgrade_and_rollback_proofs=5,
            protected_plan_runs=14,
            protected_apply_runs=15,
            peer_isolation_receipts=30,
        ),
    )

    with pytest.raises(ValueError, match="does not satisfy program-final targets"):
        checker._validate_completed_remote_evidence(
            manifest,
            manifest["program_final_verification"]["remote_targets"],
        )


def test_completed_program_verification_rejects_unbound_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    remote = tmp_path / "remote.json"
    receipts = tmp_path / "receipts.json"
    live_manifest = tmp_path / "manifest.json"
    remote.write_text("{}\n", encoding="utf-8")
    receipts.write_text("[]\n", encoding="utf-8")
    live_manifest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REMOTE_EVIDENCE_PATH", remote)
    monkeypatch.setattr(checker, "LIVE_RECEIPTS_PATH", receipts)
    monkeypatch.setattr(checker, "LIVE_EVIDENCE_MANIFEST_PATH", live_manifest)
    monkeypatch.setattr(
        checker,
        "_validate_remote_service_evidence",
        lambda _manifest, _evidence: SimpleNamespace(
            service_plan_apply_receipts=5,
            service_upgrade_and_rollback_proofs=5,
            protected_plan_runs=15,
            protected_apply_runs=15,
            peer_isolation_receipts=30,
        ),
    )
    monkeypatch.setattr(
        checker,
        "_build_live_remote_evidence",
        lambda _compatibility, _remote: ([{"expected": True}], {"expected": True}),
    )

    with pytest.raises(ValueError, match="not bound to remote transitions"):
        checker._validate_completed_remote_evidence(
            manifest,
            manifest["program_final_verification"]["remote_targets"],
        )


def _write_final_layout(root: Path) -> None:
    for service_id in (
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    ):
        service_root = root / "services" / service_id
        (service_root / "src").mkdir(parents=True)
        (service_root / "tests").mkdir()
        (service_root / "docker").mkdir()
        (service_root / "docker" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (service_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    contract_root = root / "packages" / "service-contracts"
    (contract_root / "src").mkdir(parents=True)
    (contract_root / "tests").mkdir()
    (contract_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "tests" / "integration").mkdir(parents=True)


def test_checker_accepts_final_service_owned_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    _write_final_layout(tmp_path)
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    checker._validate_final_layout()


@pytest.mark.parametrize(
    "legacy_path",
    ("Dockerfile", "src/fdai", "service-contracts", "services/Dockerfile"),
)
def test_checker_rejects_retired_compatibility_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_path: str,
) -> None:
    checker = _checker_module()
    _write_final_layout(tmp_path)
    path = tmp_path / legacy_path
    if path.suffix:
        path.write_text("legacy\n", encoding="utf-8")
    else:
        path.mkdir(parents=True)
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="retired compatibility path"):
        checker._validate_final_layout()


def test_checker_rejects_service_missing_owned_build_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    _write_final_layout(tmp_path)
    (tmp_path / "services" / "operator-service" / "docker" / "Dockerfile").unlink()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="service-owned Dockerfile"):
        checker._validate_final_layout()


def test_checker_rejects_non_integration_root_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    _write_final_layout(tmp_path)
    (tmp_path / "tests" / "unit").mkdir()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="integration tests only"):
        checker._validate_final_layout()


def test_checker_counts_cross_service_implementation_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    _write_final_layout(tmp_path)
    source = (
        tmp_path
        / "services"
        / "operator-service"
        / "src"
        / "fdai_operator_service"
        / "application.py"
    )
    source.parent.mkdir()
    source.write_text("import fdai\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    assert checker._count_service_forbidden_imports() == 1


def test_checker_rejects_entrypoint_outside_distribution_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["services"][0]["entrypoint"] = "python -m fdai"
    monkeypatch.setattr(checker, "_load_manifest", lambda: manifest)
    monkeypatch.setattr(checker, "_validate_final_layout", lambda: None)

    try:
        checker.validate()
    except ValueError as exc:
        assert "entrypoint is not a service-owned distribution script" in str(exc)
    else:
        raise AssertionError("checker accepted an entrypoint outside project.scripts")

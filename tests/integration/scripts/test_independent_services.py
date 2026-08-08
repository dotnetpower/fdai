from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "independent-services.json"
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
    assert evidence["independent_critique_rounds"] >= 10
    assert evidence["medium_or_higher_local_residuals"] == 0
    assert evidence["pending_parallel_lanes"] == []
    assert statuses["IS-04"] == "completed"
    assert statuses["IS-08"] == "completed"
    assert statuses["IS-09"] == "in_progress"


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

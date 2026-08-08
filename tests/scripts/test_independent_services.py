from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
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


def test_checker_accepts_current_non_growth_baseline() -> None:
    _checker_module().validate()


def test_checker_rejects_entrypoint_outside_distribution_scripts(
    monkeypatch,
) -> None:
    checker = _checker_module()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["services"][0]["entrypoint"] = "python -m fdai"
    monkeypatch.setattr(checker, "_load_manifest", lambda: manifest)

    try:
        checker.validate()
    except ValueError as exc:
        assert "entrypoint is not a service-owned distribution script" in str(exc)
    else:
        raise AssertionError("checker accepted an entrypoint outside project.scripts")

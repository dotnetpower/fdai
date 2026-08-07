"""Protected independent-service deployment contract tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts" / "deployment" / "service"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    return _load("service_contract")


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    return _load("guard_plan")


@pytest.fixture(scope="module")
def bundle() -> ModuleType:
    return _load("plan_bundle")


@pytest.fixture(scope="module")
def tfvars() -> ModuleType:
    return _load("materialize_tfvars")


def _image(service_image: str) -> str:
    return f"ghcr.io/example/fdai/{service_image}@sha256:{'a' * 64}"


def _plan(address: str, actions: list[str], *, image: str = "image") -> dict[str, object]:
    return {
        "resource_changes": [
            {
                "address": address,
                "change": {
                    "actions": actions,
                    "after": {"template": [{"container": [{"image": image}]}]},
                },
            }
        ]
    }


def test_matrix_resolves_exact_five_services_and_state_keys(contract: ModuleType) -> None:
    matrix = contract.load_matrix()
    assert set(matrix["services"]) == {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    for service in matrix["services"]:
        resolved = contract.resolve_service(service, "staging")
        assert resolved.backend_key == f"services/{service}/staging.tfstate"
        assert resolved.terraform_root == f"infra/services/{service}"


def test_unknown_service_and_environment_fail_closed(contract: ModuleType) -> None:
    with pytest.raises(contract.ServiceContractError, match="five independent"):
        contract.resolve_service("platform", "dev")
    with pytest.raises(contract.ServiceContractError, match="environment"):
        contract.resolve_service("core-control-plane", "preview")


def test_image_reference_is_service_specific_and_digest_pinned(contract: ModuleType) -> None:
    resolved = contract.resolve_service("operator-service", "dev")
    image = _image("fdai-operator-service")
    digest = contract.validate_image_reference(resolved, "example/fdai", image)
    assert digest == f"sha256:{'a' * 64}"
    with pytest.raises(contract.ServiceContractError, match="selected service"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            _image("fdai-core-control-plane"),
        )
    with pytest.raises(contract.ServiceContractError, match="sha256"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            image.rsplit("@", 1)[0] + "@latest",
        )


def test_plan_guard_allows_only_selected_service_create_or_update(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    for action in ("create", "update", "no-op"):
        guard.validate_plan(
            _plan(address, [action]),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"], ["create", "delete"]])
def test_plan_guard_rejects_delete_and_replacement(guard: ModuleType, actions: list[str]) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="delete or replacement"):
        guard.validate_plan(
            _plan(address, actions),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_platform_and_other_service_actions(guard: ModuleType) -> None:
    for address in (
        "azurerm_resource_group.platform",
        "module.core_control_plane.module.container_app.azurerm_container_app.service",
    ):
        with pytest.raises(guard.PlanGuardError, match="cross-service or platform"):
            guard.validate_plan(
                _plan(address, ["update"]),
                service="operator-service",
                environment="dev",
                image_ref="image",
            )


def test_plan_guard_rejects_image_substitution(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="attested image"):
        guard.validate_plan(
            _plan(address, ["update"], image="mutable:latest"),
            service="operator-service",
            environment="dev",
            image_ref="ghcr.io/example/fdai/fdai-operator-service@sha256:" + "a" * 64,
        )


def test_tfvars_selects_one_service_and_reserves_image(tfvars: ModuleType, tmp_path: Path) -> None:
    payload = {"environments": {"dev": {"operator-service": {"name": "example"}}}}
    selected = tfvars.select_tfvars(payload, service="operator-service", environment="dev")
    output = tmp_path / "service.tfvars.json"
    tfvars.write_tfvars(output, selected)
    assert json.loads(output.read_text(encoding="utf-8")) == {"name": "example"}
    assert output.stat().st_mode & 0o777 == 0o600
    payload["environments"]["dev"]["operator-service"]["image"] = "mutable"
    with pytest.raises(tfvars.TfvarsError, match="must not set image"):
        tfvars.select_tfvars(payload, service="operator-service", environment="dev")


def test_plan_bundle_round_trip_and_tamper_rejection(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    plan_json.write_text('{"resource_changes": []}\n', encoding="utf-8")
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=now,
    )
    verified = bundle.verify_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        plan_digest=created["plan_digest"],
        context_digest=created["context_digest"],
        plan_run_id="123",
        now=now + timedelta(minutes=5),
    )
    assert verified == created
    plan.write_bytes(b"tampered")
    with pytest.raises(bundle.PlanBundleError, match="binary plan digest"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
        )


def test_expired_plan_bundle_is_rejected(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    plan_json.write_text('{"resource_changes": []}\n', encoding="utf-8")
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-core-control-plane")
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="core-control-plane",
        environment="dev",
        repository="example/fdai",
        commit_sha="c" * 40,
        image_ref=image,
        workflow_run_id="456",
        now=now,
    )
    with pytest.raises(bundle.PlanBundleError, match="expired"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="core-control-plane",
            environment="dev",
            repository="example/fdai",
            commit_sha="c" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="456",
            now=now + timedelta(hours=25),
        )

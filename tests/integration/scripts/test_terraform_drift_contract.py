"""Production Terraform drift coverage contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[3]
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
def drift() -> ModuleType:
    return _load("drift_contract")


def _state(address: str, *images: str) -> dict[str, object]:
    return {
        "values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            {
                                "address": address,
                                "values": {
                                    "template": [
                                        {
                                            "container": [
                                                {"name": f"container-{index}", "image": image}
                                                for index, image in enumerate(images)
                                            ]
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ]
            }
        }
    }


def test_production_roots_cover_legacy_bootstrap_and_all_services(drift: ModuleType) -> None:
    roots = drift.production_roots("dev")

    assert len(roots) == 7
    assert [(root.root_id, root.backend_key) for root in roots[:2]] == [
        ("legacy", "fdai-dev.tfstate"),
        ("bootstrap", "ops/bootstrap/dev.tfstate"),
    ]
    assert {root.root_id for root in roots[2:]} == {
        "service:core-control-plane",
        "service:operator-service",
        "service:document-ingestion-api",
        "service:document-processing-worker",
        "service:isolated-executor",
    }
    assert len({root.backend_key for root in roots}) == len(roots)


def test_workflow_plans_every_production_root() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "infra-drift.yml").read_text(encoding="utf-8")

    assert "Plan legacy root" in workflow
    assert "Plan independent service roots" in workflow
    assert "Plan bootstrap root" in workflow
    assert "drift_contract.py roots" in workflow
    assert "drift_contract.py stored-image" in workflow
    assert '[[ "$service_count" -eq 5 ]]' in workflow
    assert 'terraform -chdir="$terraform_root" init' in workflow
    assert "ops/bootstrap/${{ inputs.environment || 'dev' }}.tfstate" in workflow
    assert "Enforce complete drift evidence" in workflow


def test_bootstrap_backend_activation_is_tracked_and_generated_file_is_ignored() -> None:
    backend = _ROOT / "infra" / "bootstrap" / "backend.azurerm.tf.example"
    ignore = (_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'backend "azurerm" {}' in backend.read_text(encoding="utf-8")
    assert "infra/bootstrap/backend.tf" in ignore


def test_stored_service_image_selects_primary_digest_before_refresh(drift: ModuleType) -> None:
    contract = drift.resolve_service("core-control-plane", "dev")
    primary = f"ghcr.io/example/fdai/{contract.image_repository}@sha256:{'a' * 64}"
    state = _state(
        contract.allowed_resource_address,
        "ghcr.io/example/sidecar@sha256:" + "b" * 64,
        primary,
    )

    assert (
        drift.stored_service_image(
            state,
            contract=contract,
            repository="example/fdai",
        )
        == primary
    )


def test_stored_service_image_rejects_missing_or_ambiguous_primary(
    drift: ModuleType,
) -> None:
    contract = drift.resolve_service("core-control-plane", "dev")
    primary = f"ghcr.io/example/fdai/{contract.image_repository}@sha256:{'a' * 64}"

    with pytest.raises(drift.DriftContractError, match="exactly one primary image"):
        drift.stored_service_image(
            _state(contract.allowed_resource_address, primary, primary),
            contract=contract,
            repository="example/fdai",
        )
    with pytest.raises(LookupError):
        drift.stored_service_image(
            _state("module.other.azurerm_container_app.service", primary),
            contract=contract,
            repository="example/fdai",
        )


def test_stored_bootstrap_inputs_preserve_pre_refresh_intent(drift: ModuleType) -> None:
    state = {
        "values": {
            "root_module": {
                "resources": [
                    {
                        "address": "data.azurerm_resource_group.app[0]",
                        "values": {"name": "rg-example-dev"},
                    },
                    {
                        "address": "azurerm_linux_virtual_machine.runner[0]",
                        "values": {
                            "admin_ssh_key": [
                                {"public_key": "ssh-ed25519 AAAA example@example.com"}
                            ]
                        },
                    },
                ]
            }
        }
    }

    assert drift.stored_bootstrap_inputs(state) == {
        "app_resource_group_name": "rg-example-dev",
        "runner_ssh_public_key": "ssh-ed25519 AAAA example@example.com",
    }


def test_stored_bootstrap_inputs_reject_incomplete_state(drift: ModuleType) -> None:
    with pytest.raises(LookupError):
        drift.stored_bootstrap_inputs({"values": {"root_module": {"resources": []}}})

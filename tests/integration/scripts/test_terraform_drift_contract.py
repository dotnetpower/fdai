"""Production Terraform drift coverage contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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


def _platform_state(*, missing_address: str | None = None) -> dict[str, Any]:
    resources = [
        {
            "address": "module.state_store.azurerm_postgresql_flexible_server.primary",
            "values": {"fqdn": "postgres.example.com"},
        },
        {
            "address": 'module.event_bus.azurerm_eventhub.topic["fdai.change.events"]',
            "values": {"name": "fdai.change.events"},
        },
        {
            "address": ('module.event_bus.azurerm_eventhub.auxiliary["fdai.pipeline.stages"]'),
            "values": {"name": "fdai.pipeline.stages"},
        },
        {
            "address": 'module.event_bus.azurerm_eventhub.topic["fdai.pantheon.objects"]',
            "values": {"name": "fdai.pantheon.objects"},
        },
        {
            "address": "module.llm_azure_openai[0].azurerm_cognitive_account.primary",
            "values": {
                "name": "oai-example",
                "endpoint": "https://oai-example.openai.azure.com/",
            },
        },
    ]
    return {
        "values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            resource
                            for resource in resources
                            if resource["address"] != missing_address
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
    assert workflow.count("-refresh-only") == 3
    assert '"scripts/deployment/service/drift_contract.py"' in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert '"infra/bootstrap/check-runner-storage-posture.sh"' in workflow
    assert '"scripts/deployment/azure/verify_deploy_identity_manifest.py"' in workflow
    assert '"scripts/deployment/azure/verify_scenario_state_closure.py"' in workflow
    assert "options: [all, runner]" in workflow
    assert workflow.count("if: inputs.scope != 'runner'") == 7
    assert "drift_contract.py roots" in workflow
    assert "drift_contract.py stored-image" in workflow
    assert "drift_contract.py \\\n            platform-inputs" in workflow
    assert '[[ "$service_count" -eq 5 ]]' in workflow
    assert 'terraform -chdir="$terraform_root" init' in workflow
    assert "TF_VAR_core_image: ${{ vars.CORE_IMAGE || vars.OPERATOR_API_IMAGE }}" in workflow
    assert "scripts/deployment/service/hydrate_database_host.py" in workflow
    assert "scripts/deployment/service/hydrate_event_topic.py" in workflow
    assert "RESOLVED_MODELS_JSON: ${{ vars.RESOLVED_MODELS_JSON }}" in workflow
    assert "resolved_models_digest=" in workflow
    assert 'MODEL_ENDPOINTS_JSON="$model_endpoints_json"' in workflow
    assert "resolved_model_args+=(--model-binding-transition)" in workflow
    assert '"${resolved_model_args[@]}"' in workflow
    assert "terraform -chdir=infra show -json" in workflow
    assert "database_host=\"$(jq -er '.database_host'" in workflow
    assert "event_topic=\"$(jq -er '.event_topic'" in workflow
    assert "pipeline_stage_topic=\"$(jq -er '.pipeline_stage_topic'" in workflow
    assert "pantheon_object_topic=\"$(jq -er '.pantheon_object_topic'" in workflow
    assert "ops/bootstrap/${{ inputs.environment || 'dev' }}.tfstate" in workflow
    assert "Verify runner storage and identity posture" in workflow
    assert "Verify stable deploy identity role manifest" in workflow
    assert "deploy-identity-manifest-receipt.json" in workflow
    manifest_step = workflow.split(
        "- name: Verify stable deploy identity role manifest", maxsplit=1
    )[1].split("- name: Publish stable deploy identity manifest receipt", maxsplit=1)[0]
    assert manifest_step.index("umask 077") < manifest_step.index(
        "terraform -chdir=infra show -json"
    )
    assert "Verify disposable scenario state closure" in workflow
    assert "scenario-lab/fdai-sre-lab.tfstate" in workflow
    assert "scenario-state-closure-receipt.json" in workflow
    assert "./check-runner-storage-posture.sh" in workflow
    assert "TF_VAR_runner_vm_size: Standard_D4ds_v5" in workflow
    assert "TF_VAR_runner_vm_name: ${{ vars.DEPLOY_RUNNER_VM_NAME }}" in workflow
    assert 'refresh_plan="$RUNNER_TEMP/bootstrap-refresh.tfplan"' in workflow
    assert 'app_resource_group_name="$(terraform output -raw app_resource_group_name)"' in workflow
    assert '"$HOME/.ssh/authorized_keys"' in workflow
    assert "Recovered promoted runner plan inputs from authoritative host readback." in workflow
    assert "($plan.resource_drift // [])[]" in workflow
    assert "($plan.output_changes // {}) | to_entries[]" in workflow
    assert '[[ "$drift_count" -eq 0 ]]' in workflow
    assert 'echo "No bootstrap Terraform drift detected."' in workflow
    assert workflow.index('echo "No bootstrap Terraform drift detected."') < workflow.index(
        "Enforce complete drift evidence"
    )
    assert "RUNNER_STORAGE_OUTCOME" in workflow
    assert "DEPLOY_IDENTITY_MANIFEST_OUTCOME" in workflow
    assert "SCENARIO_STATE_OUTCOME" in workflow
    assert '"$DEPLOY_RUNNER_PRINCIPAL_ID"' in workflow
    assert 'if [[ "$DRIFT_SCOPE" != "runner" ]]' in workflow
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


def test_stored_platform_inputs_preserve_pre_refresh_service_bindings(
    drift: ModuleType,
) -> None:
    assert drift.stored_platform_inputs(_platform_state()) == {
        "database_host": "postgres.example.com",
        "event_topic": "fdai.change.events",
        "model_endpoints": {"azure-openai:oai-example": "https://oai-example.openai.azure.com"},
        "pantheon_object_topic": "fdai.pantheon.objects",
        "pipeline_stage_topic": "fdai.pipeline.stages",
    }


def test_stored_platform_inputs_reject_incomplete_state(drift: ModuleType) -> None:
    with pytest.raises(LookupError):
        drift.stored_platform_inputs(
            _platform_state(
                missing_address=('module.event_bus.azurerm_eventhub.topic["fdai.pantheon.objects"]')
            )
        )


def test_stored_platform_inputs_reject_unexpected_topic(drift: ModuleType) -> None:
    state = _platform_state()
    root = state["values"]["root_module"]
    topic = root["child_modules"][0]["resources"][1]
    topic["values"]["name"] = "fdai.unexpected.events"

    with pytest.raises(drift.DriftContractError, match="unexpected event_topic"):
        drift.stored_platform_inputs(state)


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

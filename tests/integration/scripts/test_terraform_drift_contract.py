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


@pytest.fixture(scope="module")
def service_contract() -> ModuleType:
    return _load("service_contract")


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


_COST_KEY_ID = "https://kv-example.vault.azure.net/secrets/fdai-cost-pseudonym-key/0123abcd"


def _platform_state(
    *, missing_address: str | None = None, cost_key: object = _COST_KEY_ID
) -> dict[str, Any]:
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
    root_resources = (
        []
        if cost_key is None
        else [
            {
                "address": "azurerm_key_vault_secret.cost_pseudonym_key[0]",
                "values": {"id": cost_key},
            }
        ]
    )
    return {
        "values": {
            "root_module": {
                "resources": root_resources,
                "child_modules": [
                    {
                        "resources": [
                            resource
                            for resource in resources
                            if resource["address"] != missing_address
                        ]
                    }
                ],
            }
        }
    }


def _legacy_platform_state(*, incomplete_governed_identities: bool = False) -> dict[str, Any]:
    addresses = [
        "module.console[0].azurerm_static_web_app.console",
        "azurerm_function_app_flex_consumption.dev_gateway[0]",
        "module.ingestion_identity[0].azurerm_user_assigned_identity.primary",
        "module.document_intelligence[0].azurerm_cognitive_account.primary",
        "module.identity_change[0].azurerm_user_assigned_identity.primary",
        "module.identity_resilience[0].azurerm_user_assigned_identity.primary",
        "module.identity_finops[0].azurerm_user_assigned_identity.primary",
        "module.isolated_executor_identity[0].azurerm_user_assigned_identity.primary",
        "module.llm_azure_openai[0].azurerm_cognitive_account.primary",
        "module.monitoring[0].azurerm_monitor_action_group.main",
        "azurerm_linux_virtual_machine_scale_set.ohl_evidence[0]",
        ("module.operational_evidence_verifier_identity[0].azurerm_user_assigned_identity.primary"),
        "module.operational_history_storage[0].azurerm_storage_account.case_history",
        "module.operator_api_identity[0].azurerm_user_assigned_identity.primary",
        "module.operator_channel_edge_identity[0].azurerm_user_assigned_identity.primary",
    ]
    model_deployments = [
        {
            "address": (
                'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.judge"]'
            ),
            "values": {
                "name": "t1.judge",
                "model": [{"name": "gpt-5-mini", "version": "2026-01-01"}],
                "sku": [{"name": "GlobalStandard", "capacity": 200}],
            },
        },
        {
            "address": (
                "module.llm_azure_openai[0].azurerm_cognitive_deployment."
                'capability["t2.reasoner.primary"]'
            ),
            "values": {
                "name": "t2.reasoner.primary",
                "model": [{"name": "gpt-5.4", "version": "2026-02-01"}],
                "sku": [{"name": "ProvisionedManaged", "capacity": 12}],
            },
        },
    ]
    outputs = {
        "decision_evidence_container_url": {"value": "https://example.com/decision-evidence"},
        "decision_evidence_storage_account_name": {"value": "exampledecision"},
        "dev_operations_gateway_audience": {"value": "00000000-0000-0000-0000-000000000010"},
        "identity_change_principal_id": {"value": "00000000-0000-0000-0000-000000000011"},
        "identity_change_resource_id": {"value": "/example/change"},
        "identity_finops_principal_id": {
            "value": (
                "" if incomplete_governed_identities else "00000000-0000-0000-0000-000000000012"
            )
        },
        "identity_finops_resource_id": {"value": "/example/finops"},
        "identity_resilience_principal_id": {"value": "00000000-0000-0000-0000-000000000013"},
        "identity_resilience_resource_id": {"value": "/example/resilience"},
        "llm_resource_id": {"value": "/example/openai"},
        "ohl_scale_out_evidence_target_id": {"value": "/example/vmss"},
        "resolved_models_sha256": {"value": "a" * 64},
    }
    return {
        "state": {
            "values": {
                "outputs": outputs,
                "root_module": {
                    "resources": [
                        {
                            "address": address,
                            "values": (
                                {"principal_id": "00000000-0000-0000-0000-000000000001"}
                                if address
                                == (
                                    "module.operator_api_identity[0]."
                                    "azurerm_user_assigned_identity.primary"
                                )
                                else {}
                            ),
                        }
                        for address in addresses
                    ]
                    + model_deployments
                },
            }
        },
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
    assert workflow.count("if: inputs.scope != 'runner'") == 8
    assert '"scripts/deployment/azure/postgres_power_window.py"' in workflow
    assert "drift_contract.py roots" in workflow
    assert "drift_contract.py stored-image" in workflow
    assert "drift_contract.py \\\n            platform-inputs" in workflow
    assert '[[ "$service_count" -eq 5 ]]' in workflow
    assert 'terraform -chdir="$terraform_root" init' in workflow
    assert "TF_VAR_core_image: ${{ vars.CORE_IMAGE || vars.OPERATOR_API_IMAGE }}" in workflow
    assert (
        "TARGET_COMMIT_SHA: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.commit_sha || github.sha }}" in workflow
    )
    assert "scripts/deployment/service/hydrate_database_host.py" in workflow
    assert "scripts/deployment/service/hydrate_event_topic.py" in workflow
    assert "RESOLVED_MODELS_JSON: ${{ vars.RESOLVED_MODELS_JSON }}" in workflow
    assert "resolved_models_digest=" in workflow
    assert 'source_revision_binding="$TARGET_COMMIT_SHA"' in workflow
    assert 'MODEL_ENDPOINTS_JSON="$model_endpoints_json"' in workflow
    assert 'SOURCE_REVISION="$source_revision_binding"' in workflow
    assert "jq -r '.cost_pseudonym_key_secret_id // \"\"'" in workflow
    assert 'COST_PSEUDONYM_KEY_SECRET_ID="$cost_pseudonym_binding"' in workflow
    assert "Platform state has no Cost pseudonym key binding for $root_id." in workflow
    assert "resolved_model_args+=(--model-binding-transition)" in workflow
    assert '"${resolved_model_args[@]}"' in workflow
    assert "terraform -chdir=infra show -json" in workflow
    assert "platform-output-inputs" in workflow
    assert '-var-file="$plan_inputs" -detailed-exitcode' in workflow
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


def test_core_service_accepts_only_declared_distribution_images(
    service_contract: ModuleType,
) -> None:
    core = service_contract.resolve_service("core-control-plane", "dev")
    assert core.image_repositories == (
        "fdai-core-control-plane",
        "fdai-cost-governance",
    )
    for repository in core.image_repositories:
        image = f"ghcr.io/example/fdai/{repository}@sha256:{'a' * 64}"
        assert service_contract.validate_image_reference(core, "example/fdai", image) == (
            f"sha256:{'a' * 64}"
        )

    operator = service_contract.resolve_service("operator-service", "dev")
    with pytest.raises(service_contract.ServiceContractError, match="selected service"):
        service_contract.validate_image_reference(
            operator,
            "example/fdai",
            f"ghcr.io/example/fdai/fdai-cost-governance@sha256:{'a' * 64}",
        )


def test_stored_core_image_accepts_cost_governance_distribution(drift: ModuleType) -> None:
    contract = drift.resolve_service("core-control-plane", "dev")
    image = f"ghcr.io/example/fdai/fdai-cost-governance@sha256:{'a' * 64}"
    state = _state(contract.allowed_resource_address, image)

    assert (
        drift.stored_service_image(
            state,
            contract=contract,
            repository="example/fdai",
        )
        == image
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
        "cost_pseudonym_key_secret_id": _COST_KEY_ID,
        "database_host": "postgres.example.com",
        "event_topic": "fdai.change.events",
        "model_endpoints": {"azure-openai:oai-example": "https://oai-example.openai.azure.com"},
        "pantheon_object_topic": "fdai.pantheon.objects",
        "pipeline_stage_topic": "fdai.pipeline.stages",
    }


def test_stored_platform_inputs_report_an_absent_cost_pseudonym_key(drift: ModuleType) -> None:
    inputs = drift.stored_platform_inputs(_platform_state(cost_key=None))

    assert inputs["cost_pseudonym_key_secret_id"] is None


@pytest.mark.parametrize("cost_key", ["", "line\nbreak", 7])
def test_stored_platform_inputs_reject_an_invalid_cost_pseudonym_key(
    drift: ModuleType, cost_key: object
) -> None:
    with pytest.raises(drift.DriftContractError, match="invalid cost pseudonym key binding"):
        drift.stored_platform_inputs(_platform_state(cost_key=cost_key))


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


_SERVER_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
    "/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-example"
)


def _database_state(server_id: object) -> dict[str, Any]:
    return {
        "values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            {
                                "address": (
                                    "module.state_store.azurerm_postgresql_flexible_server.primary"
                                ),
                                "values": {"id": server_id, "fqdn": "postgres.example.com"},
                            }
                        ]
                    }
                ]
            }
        }
    }


def test_stored_platform_database_reads_the_exact_server_id(drift: ModuleType) -> None:
    assert drift.stored_platform_database(_database_state(_SERVER_ID)) == {"server_id": _SERVER_ID}


@pytest.mark.parametrize(
    "server_id",
    [
        None,
        "",
        _SERVER_ID + "/databases/fdai",
        _SERVER_ID.replace("DBforPostgreSQL", "DBforMySQL"),
    ],
)
def test_stored_platform_database_rejects_invalid_server_ids(
    drift: ModuleType, server_id: object
) -> None:
    with pytest.raises(drift.DriftContractError, match="invalid PostgreSQL server id"):
        drift.stored_platform_database(_database_state(server_id))


def test_stored_platform_database_requires_the_server(drift: ModuleType) -> None:
    with pytest.raises(drift.DriftContractError, match="missing the PostgreSQL server"):
        drift.stored_platform_database(
            _platform_state(
                missing_address="module.state_store.azurerm_postgresql_flexible_server.primary"
            )
        )


def test_drift_opens_the_database_window_before_the_legacy_plan_and_always_closes_it() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "infra-drift.yml").read_text(encoding="utf-8")
    opened = workflow.index("      - name: Open legacy database power window")
    legacy = workflow.index("      - name: Plan legacy root")
    services = workflow.index("      - name: Plan independent service roots")
    closed = workflow.index("      - name: Close legacy database power window")
    enforced = workflow.index("      - name: Enforce complete drift evidence")

    assert workflow.index("      - name: Initialize legacy state") < opened < legacy < services
    assert services < closed < enforced
    assert "drift_contract.py \\\n            platform-database" in workflow
    assert "postgres_power_window.py open" in workflow
    assert "postgres_power_window.py close" in workflow
    assert "steps.database_window.outcome != 'skipped'" in workflow[closed:enforced]
    assert '[[ "$DATABASE_WINDOW_OUTCOME" == "success" ]]' in workflow
    assert "group: legacy-database-power-window-${{ inputs.environment || 'dev' }}" in workflow


def test_observation_export_shares_the_database_window() -> None:
    workflow = (
        _ROOT / ".github" / "workflows" / "cost-governance-observation-export.yml"
    ).read_text(encoding="utf-8")
    opened = workflow.index("      - name: Open legacy database power window")

    assert workflow.index("      - name: Authenticate and bind private platform state") < opened
    assert opened < workflow.index("      - name: Resolve exact active package pin")
    assert workflow.index("      - name: Close legacy database power window") < workflow.index(
        "      - name: Clean private state material"
    )
    assert "group: legacy-database-power-window-${{ inputs.environment || 'dev' }}" in workflow


def test_reconcile_applies_only_reviewed_saved_refresh_only_plans() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "infra-drift-reconcile.yml").read_text(
        encoding="utf-8"
    )
    plan = workflow.index("      - name: Plan reviewable refresh-only drift")
    apply = workflow.index("      - name: Apply reviewed refresh-only drift")
    verify = workflow.index("      - name: Verify every root is drift-free")
    closed = workflow.index("      - name: Close legacy database power window")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "push:" not in workflow
    assert (
        "environment: ${{ inputs.reviewed_drift_digest != '' && 'drift-reconcile' || 'plan-only' }}"
        in workflow
    )
    assert workflow.index("      - name: Open legacy database power window") < plan
    assert plan < apply < verify < closed
    assert workflow.count("plan -refresh-only") == 4
    assert "terraform apply -refresh-only" not in workflow
    assert "-auto-approve" not in workflow
    assert "-target" not in workflow
    assert '[[ "$OBSERVED_DRIFT_DIGEST" == "$REVIEWED_DRIFT_DIGEST" ]]' in workflow
    apply_block = workflow[apply:verify]
    assert apply_block.index('OBSERVED_DRIFT_DIGEST" == ') < apply_block.index(
        'apply -input=false -lock-timeout=300s "$plan_file"'
    )
    assert "if: inputs.reviewed_drift_digest != ''" in apply_block
    assert "refresh_drift_digest.py summarize" in workflow
    assert "refresh_drift_digest.py digest" in workflow
    assert "platform-output-inputs" in workflow
    assert '-var-file="$work/vars/legacy-output-inputs.tfvars.json"' in workflow
    assert "| jq '.variables | map_values(.value)' >\"$work/verify/vars.json\"" in workflow
    assert "group: legacy-database-power-window-${{ inputs.environment }}" in workflow
    assert "Drift remains after reconciliation." in workflow
    assert 'printf \'%s\\n\' "$root_id" >>"$work/skipped-roots.txt"' in workflow
    assert "Skipped roots: ${skipped:-none}" in workflow
    assert "Recovered promoted runner plan inputs from authoritative host readback." in workflow
    assert workflow.count("map_values(.value)") == 1


def test_recovers_legacy_output_inputs_from_stored_state(drift: ModuleType) -> None:
    fixture = _legacy_platform_state()

    inputs = drift.stored_platform_output_inputs(fixture["state"])

    assert inputs == {
        "enable_dev_operations_gateway": True,
        "enable_governed_execution": True,
        "enable_inventory_evidence_store_reader": True,
        "enable_llm": True,
        "enable_ohl_scale_out_evidence_target": True,
        "enable_operational_history": True,
        "operator_api_audience": "00000000-0000-0000-0000-000000000010",
        "resolved_capabilities": [
            {
                "name": "t1.judge",
                "publisher": "OpenAI",
                "family": "gpt-5-mini",
                "version": "2026-01-01",
                "sku": "GlobalStandard",
                "capacity_unit": "tpm",
                "capacity_tpm": 200000,
                "capacity_value": 0,
            },
            {
                "name": "t2.reasoner.primary",
                "publisher": "OpenAI",
                "family": "gpt-5.4",
                "version": "2026-02-01",
                "sku": "ProvisionedManaged",
                "capacity_unit": "ptu",
                "capacity_tpm": 0,
                "capacity_value": 12,
            },
        ],
        "resolved_models_sha256": "a" * 64,
    }


def test_recovers_operator_identity_without_root_output(drift: ModuleType) -> None:
    fixture = _legacy_platform_state()

    assert drift.stored_platform_operator_identity(fixture["state"]) == {
        "principal_id": "00000000-0000-0000-0000-000000000001"
    }


def test_treats_null_optional_legacy_output_as_disabled(drift: ModuleType) -> None:
    fixture = _legacy_platform_state()
    fixture["state"]["values"]["outputs"]["ohl_scale_out_evidence_target_id"]["value"] = None

    inputs = drift.stored_platform_output_inputs(fixture["state"])

    assert inputs["enable_ohl_scale_out_evidence_target"] is False


def test_rejects_invalid_legacy_model_deployment(drift: ModuleType) -> None:
    fixture = _legacy_platform_state()
    resources = fixture["state"]["values"]["root_module"]["resources"]
    deployment = next(
        resource for resource in resources if "azurerm_cognitive_deployment" in resource["address"]
    )
    deployment["values"]["sku"][0]["capacity"] = 0

    with pytest.raises(
        drift.DriftContractError,
        match="invalid model deployment",
    ):
        drift.stored_platform_output_inputs(fixture["state"])


def test_rejects_incomplete_legacy_governed_identities(drift: ModuleType) -> None:
    fixture = _legacy_platform_state(incomplete_governed_identities=True)

    with pytest.raises(
        drift.DriftContractError,
        match="incomplete governed identity set",
    ):
        drift.stored_platform_output_inputs(fixture["state"])

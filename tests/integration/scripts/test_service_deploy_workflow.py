"""Static contracts for the protected independent-service workflow."""

from __future__ import annotations

import json
import re
import runpy
import shutil
import subprocess
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "service-deploy.yml").read_text(encoding="utf-8")
_PEER_CAPTURE = (_ROOT / "scripts" / "deployment" / "service" / "capture_peer_states.sh").read_text(
    encoding="utf-8"
)
_HEALTH_SCRIPT = (_ROOT / "scripts" / "deployment" / "service" / "verify_health.sh").read_text(
    encoding="utf-8"
)
_CORE_TERRAFORM = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text(encoding="utf-8")
_OPERATOR_VARIABLES = (_ROOT / "infra/services/operator-service/variables.tf").read_text(
    encoding="utf-8"
)
_SERVICE_CONTAINER_APP = (_ROOT / "infra/services/_modules/container-app/main.tf").read_text(
    encoding="utf-8"
)
_LEGACY_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")
_PLAN_SCOPE = (_ROOT / "scripts/deployment/azure/enforce_plan_scope.py").read_text(encoding="utf-8")
_IMAGE_BINDER = (_ROOT / "scripts/deployment/azure/bind_core_runtime_image.sh").read_text(
    encoding="utf-8"
)
_CONSOLE_PUBLISHER = (_ROOT / "scripts/deployment/azure/publish-console.sh").read_text(
    encoding="utf-8"
)
_GH_INSTALLER = (_ROOT / "scripts/deployment/azure/install-pinned-github-cli.sh").read_text(
    encoding="utf-8"
)
_CONSOLE_PUBLISH_WORKFLOW = (_ROOT / ".github/workflows/publish-console.yml").read_text(
    encoding="utf-8"
)
_CONSOLE_REQUEST_WORKFLOW = (_ROOT / ".github/workflows/request-console-publish.yml").read_text(
    encoding="utf-8"
)
_CATALOG_REFRESH = (_ROOT / "scripts/deployment/azure/refresh-authoritative-catalogs.sh").read_text(
    encoding="utf-8"
)
_MODEL_PROPOSAL_HELPER = (
    _ROOT / "scripts/deployment/azure/materialize-model-binding-proposal.sh"
).read_text(encoding="utf-8")
_LEGACY_COMPUTE = (_ROOT / "infra/modules/compute/container-apps/main.tf").read_text(
    encoding="utf-8"
)
_LEGACY_OUTPUTS = (_ROOT / "infra/modules/compute/container-apps/outputs.tf").read_text(
    encoding="utf-8"
)
_LEGACY_ROOT = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
_LEGACY_VARIABLES = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
_LEGACY_OPERATOR_MODULE = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
    encoding="utf-8"
)
_CORE_DOCKERFILE = (_ROOT / "services/core-control-plane/docker/Dockerfile").read_text(
    encoding="utf-8"
)
_LEGACY_INGESTION_MODULE = (
    _ROOT / "infra/modules/ingestion-gateway/container-app/main.tf"
).read_text(encoding="utf-8")
_MATRIX = json.loads(
    (_ROOT / "scripts" / "deployment" / "service" / "service-matrix.json").read_text(
        encoding="utf-8"
    )
)
_MIGRATION = json.loads(
    (_ROOT / "infra" / "services" / "state-migration.json").read_text(encoding="utf-8")
)
_ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}
_GH_CLI_VERSION = "2.97.0"
_GH_CLI_ARCHIVE_SHA256 = "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"


def test_workflow_has_closed_five_service_input_and_runner() -> None:
    services = set(_MATRIX["services"])
    assert len(services) == 5
    assert services == set(_MIGRATION["services"])
    for service in services:
        assert f"          - {service}\n" in _WORKFLOW
    assert "runs-on: [self-hosted, fdai-deploy]" in _WORKFLOW
    assert "group: service-deploy-${{ inputs.service }}-${{ inputs.environment }}" in _WORKFLOW


def test_legacy_platform_cannot_recreate_migrated_core() -> None:
    source_address = _MIGRATION["services"]["core-control-plane"]["moves"][0]["from"]

    assert source_address == "module.compute.azurerm_container_app.core"
    assert 'resource "azurerm_container_app" "core"' not in _LEGACY_COMPUTE
    assert "azurerm_container_app.core" not in _LEGACY_OUTPUTS
    assert "-target=module.compute.azurerm_container_app.core" not in _LEGACY_WORKFLOW
    assert "providers/Microsoft.App/containerApps/${module.compute.core_app_name}" in _LEGACY_ROOT


def test_operator_migration_image_is_independently_pinned() -> None:
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    normalized_root = " ".join(root.split())
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    module = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
        encoding="utf-8"
    )

    assert 'variable "operator_api_migration_image"' in variables
    assert 'regex("@sha256:[0-9a-f]{64}$", var.operator_api_migration_image)' in variables
    assert "migration_image = var.operator_api_migration_image" in normalized_root
    assert 'image   = var.migration_image == "" ? var.image : var.migration_image' in module
    assert "TF_VAR_operator_api_migration_image" in _LEGACY_WORKFLOW


def test_platform_workflow_binds_channel_edge_identity_and_secret_scopes() -> None:
    assert "deploy_operator_channel_edge:" in _LEGACY_WORKFLOW
    assert "TF_VAR_enable_operator_channel_edge: ${{ inputs.deploy_operator_channel_edge }}" in (
        _LEGACY_WORKFLOW
    )
    assert (
        "TF_VAR_operator_channel_edge_secret_ids: "
        "\"${{ vars.OPERATOR_CHANNEL_EDGE_SECRET_IDS_JSON || '[]' }}\""
    ) in _LEGACY_WORKFLOW
    assert "OPERATOR_CHANNEL_EDGE_SECRET_IDS_JSON" in _LEGACY_WORKFLOW
    assert "operator_channel_edge_effective_secret_ids" in _LEGACY_ROOT
    assert "setunion(" in _LEGACY_ROOT
    assert "length(var.operator_channel_edge_secret_ids) >= 2" not in _LEGACY_VARIABLES
    assert 'var.channel_edge.principal_scopes_secret_id != ""' in _OPERATOR_VARIABLES
    assert "one complete Slack or Teams provider contract plus principal scopes" in (
        _OPERATOR_VARIABLES
    )


def test_platform_workflow_exposes_opt_in_monitoring_for_every_environment() -> None:
    assert "deploy_monitoring:" in _LEGACY_WORKFLOW
    assert 'description: "Provision the action group, alerts, and diagnostic settings."' in (
        _LEGACY_WORKFLOW
    )
    assert "TF_VAR_enable_monitoring: ${{ inputs.deploy_monitoring }}" in _LEGACY_WORKFLOW


def test_platform_workflow_stays_within_dispatch_input_limit() -> None:
    inputs = _LEGACY_WORKFLOW.split("workflow_dispatch:\n    inputs:\n", maxsplit=1)[1].split(
        "\npermissions:", maxsplit=1
    )[0]
    names = re.findall(r"^      ([a-z_]+):$", inputs, re.MULTILINE)

    assert len(names) <= 25


def test_platform_protected_source_guard_is_valid_bash() -> None:
    script = _LEGACY_WORKFLOW.split("- name: Verify protected workflow source", maxsplit=1)[
        1
    ].split("- name: Prepare self-hosted runner workspace", maxsplit=1)[0]
    script = script.split("run: |", maxsplit=1)[1]
    bash = shutil.which("bash")

    assert bash is not None

    completed = subprocess.run(  # noqa: S603 - resolved Bash with test-controlled input.
        [bash, "-n"],
        input=textwrap.dedent(script),
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_platform_model_proposal_materializer_is_valid_bash() -> None:
    bash = shutil.which("bash")

    assert bash is not None
    assert "materialize-model-binding-proposal.sh" in _LEGACY_WORKFLOW

    completed = subprocess.run(  # noqa: S603 - resolved Bash with test-controlled input.
        [bash, "-n"],
        input=_MODEL_PROPOSAL_HELPER,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_platform_workflow_isolates_monitoring_plan_changes() -> None:
    target_expression = _LEGACY_WORKFLOW[_LEGACY_WORKFLOW.index("TF_CLI_ARGS_plan:") :]
    target_expression = target_expression[: target_expression.index("\n")]

    assert "inputs.deploy_monitoring && !inputs.deploy_console" in target_expression
    assert "&& '-target=module.monitoring'" in target_expression
    assert target_expression.index("inputs.deploy_monitoring") < target_expression.index(
        "inputs.deploy_dev_operations_gateway"
    )
    assert "MONITORING_ONLY:" in _LEGACY_WORKFLOW
    assert "Monitoring-only plan contains changes outside module.monitoring:" in _PLAN_SCOPE
    assert '.startswith("module.monitoring[")' in _PLAN_SCOPE
    design_mocks_guard = _LEGACY_WORKFLOW[
        _LEGACY_WORKFLOW.index("- name: Validate deployment request") :
    ]
    design_mocks_guard = design_mocks_guard[
        : design_mocks_guard.index("- name: Bind model-binding Terraform target")
    ]
    assert "DEPLOY_MONITORING" in design_mocks_guard
    model_step = _LEGACY_WORKFLOW.split("- name: Resolve and seal model capabilities", maxsplit=1)[
        1
    ].split("- name: Verify protected storage containers", maxsplit=1)[0]
    assert "env.MONITORING_ONLY != 'true'" in model_step
    preflight_step = _LEGACY_WORKFLOW.split(
        "- name: Run complete Azure live preflight", maxsplit=1
    )[1].split("- name: Cleanup expired protected plans", maxsplit=1)[0]
    for resource_type in (
        "azurerm_monitor_action_group",
        "azurerm_monitor_diagnostic_setting",
        "azurerm_monitor_metric_alert",
        "azurerm_monitor_scheduled_query_rules_alert_v2",
    ):
        assert resource_type in preflight_step
    for neutral_type in (
        "action-group",
        "diagnostic-settings",
        "monitor-metric-alert",
        "monitor-log-alert",
    ):
        assert neutral_type in preflight_step


def test_core_service_tolerates_unapplied_optional_observation_output() -> None:
    materialize = _WORKFLOW.split("- name: Materialize selected service inputs", maxsplit=1)[
        1
    ].split("- name: Create and guard service plan", maxsplit=1)[0]

    assert "output -json ohl_observation_context_binding 2>/dev/null || printf 'null" in materialize
    assert 'with_entries(select(.value | type == "string" and length > 0))' in materialize


def test_console_release_publishes_static_content_without_catalog_mutation() -> None:
    assert "- name: Publish and verify Console static content" in _CONSOLE_PUBLISH_WORKFLOW
    assert "CONSOLE_STATIC_WEB_APP_ID" in _CONSOLE_PUBLISH_WORKFLOW
    assert "CONSOLE_DEFAULT_HOSTNAME" in _CONSOLE_PUBLISH_WORKFLOW
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in (
        _CONSOLE_PUBLISH_WORKFLOW
    )
    assert 'hostname="${hostname:-${CONSOLE_DEFAULT_HOSTNAME:-}}"' in (
        _ROOT / "scripts/deployment/azure/publish-console.sh"
    ).read_text(encoding="utf-8")
    assert "- name: Bind exact Core catalog image" not in _CONSOLE_PUBLISH_WORKFLOW
    assert (
        "- name: Refresh and verify authoritative PostgreSQL catalogs"
        not in _CONSOLE_PUBLISH_WORKFLOW
    )
    assert "bootstrap-service-migrations.sh" in _CATALOG_REFRESH
    assert "run_catalog_job" in _CATALOG_REFRESH
    assert '--image "$previous_image"' in _CATALOG_REFRESH
    assert "CATALOG_ROLLBACK_IMAGE" in _CONSOLE_PUBLISH_WORKFLOW or "CATALOG_ROLLBACK_IMAGE" in (
        _ROOT / ".github/workflows/refresh-catalogs.yml"
    ).read_text(encoding="utf-8")
    assert "catalog rollback image must be digest-pinned" in _CATALOG_REFRESH
    assert "az containerapp job update" in _CATALOG_REFRESH
    assert 'if [[ "$CATALOG_IMAGE_PREBOUND" == "false" ]]' in _CATALOG_REFRESH
    assert 'if [[ "$CATALOG_JOB_PRESTARTED" == "false" ]]' in _CATALOG_REFRESH
    assert 'if [[ "$bound_image" != "$TF_VAR_core_image" ]]' in _CATALOG_REFRESH
    assert 'if [[ "$prestarted_status" != "Succeeded" ]]' in _CATALOG_REFRESH
    assert "catalog_job_uri=" in _CATALOG_REFRESH
    assert "az resource show" not in _CATALOG_REFRESH
    assert "${catalog_job_uri}?api-version=2024-03-01" in _CATALOG_REFRESH
    assert "/executions?api-version=2024-03-01" in _CATALOG_REFRESH
    assert 'name  = "PGOPTIONS"' in _LEGACY_OPERATOR_MODULE
    assert 'value = "-c statement_timeout=300000"' in _LEGACY_OPERATOR_MODULE
    assert "CATALOG_IMAGE_PREBOUND" in (_ROOT / ".github/workflows/refresh-catalogs.yml").read_text(
        encoding="utf-8"
    )
    refresh_workflow = (_ROOT / ".github/workflows/refresh-catalogs.yml").read_text(
        encoding="utf-8"
    )
    assert "containerapp --version 1.3.0b4" in refresh_workflow
    assert "CATALOG_JOB_PRESTARTED" in refresh_workflow
    assert "verify-authoritative-catalogs.py" in _CATALOG_REFRESH


def test_console_release_request_uses_bot_as_deployment_requester() -> None:
    assert "actions: write" in _CONSOLE_REQUEST_WORKFLOW
    assert "Verify protected workflow source" in _CONSOLE_REQUEST_WORKFLOW
    assert "Verify required CI" in _CONSOLE_REQUEST_WORKFLOW
    assert "actions/workflows/publish-console.yml/dispatches" in _CONSOLE_REQUEST_WORKFLOW
    assert '"inputs[commit_sha]=$TARGET_COMMIT_SHA"' in _CONSOLE_REQUEST_WORKFLOW


def test_platform_gateway_plan_targets_active_moved_role_collections() -> None:
    target_expression = _LEGACY_WORKFLOW[_LEGACY_WORKFLOW.index("TF_CLI_ARGS_plan:") :]
    target_expression = target_expression[: target_expression.index("\n")]

    for address in (
        "azurerm_role_assignment.command_api_eventhubs_receiver",
        "azurerm_role_assignment.command_api_eventhubs_sender",
        "azurerm_role_assignment.executor_eventhubs_data_owner",
        "module.measurement_runners.azurerm_container_app_job.baseline_regression",
        "module.measurement_runners.azurerm_container_app_job.pattern_growth",
    ):
        assert f"-target={address}" in target_expression


def test_platform_workflow_does_not_expose_completed_event_bus_migration() -> None:
    for retired_token in (
        "EVENT_BUS_TOPIC_MIGRATION",
        "MIGRATE_EVENT_BUS_TOPICS",
        "MIGRATE_EVENT_BUS_JOBS",
        "plan-evh-",
        "apply-evh-",
    ):
        assert retired_token not in _LEGACY_WORKFLOW


def test_platform_destructive_guard_accepts_only_exact_embedding_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    step = _LEGACY_WORKFLOW.split("- name: Reject destructive protected plan", maxsplit=1)[1].split(
        "- name: Run complete Azure live preflight", maxsplit=1
    )[0]
    match = re.search(r"python3 - <<'PY'\n(?P<source>.*?)\n\s+PY", step, re.DOTALL)

    assert match is not None
    source = textwrap.dedent(match.group("source"))
    address = 'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.embedding"]'
    before = {
        "name": "t1.embedding",
        "cognitive_account_id": "same-account",
        "model": [{"format": "OpenAI", "name": "text-embedding-3-small", "version": "1"}],
        "sku": [{"name": "GlobalStandard", "capacity": 1}],
    }
    after = {
        "name": "t1.embedding",
        "cognitive_account_id": "same-account",
        "model": [{"format": "OpenAI", "name": "text-embedding-3-small", "version": None}],
        "sku": [{"name": "Standard", "capacity": 200}],
    }
    exact_change = {
        "address": address,
        "change": {"actions": ["delete", "create"], "before": before, "after": after},
    }
    plan_path = tmp_path / "dev.plan.review.json"
    script_path = tmp_path / "deploy_dev_destructive_guard.py"
    monkeypatch.chdir(tmp_path)
    script_path.write_text(source, encoding="utf-8")
    plan_path.write_text(
        json.dumps({"resource_changes": [exact_change]}),
        encoding="utf-8",
    )
    runpy.run_path(str(script_path), run_name="__main__")

    mutations = (
        ("change", "actions", ["delete"]),
        ("after", "cognitive_account_id", "another-account"),
        ("before", "sku", [{"name": "GlobalStandard", "capacity": 2}]),
        ("after", "sku", [{"name": "Standard", "capacity": 100}]),
        (
            "after",
            "model",
            [{"format": "OpenAI", "name": "text-embedding-3-large", "version": None}],
        ),
    )
    for owner, field, value in mutations:
        changed = json.loads(json.dumps(exact_change))
        target = changed["change"] if owner == "change" else changed["change"][owner]
        target[field] = value
        plan_path.write_text(
            json.dumps({"resource_changes": [changed]}),
            encoding="utf-8",
        )
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError(f"destructive guard accepted drifted model field: {owner}.{field}")


def test_platform_workflow_does_not_require_system_pip() -> None:
    assert "uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990" in _LEGACY_WORKFLOW
    assert 'version: "0.11.32"' in _LEGACY_WORKFLOW
    assert "python3 -m pip" not in _LEGACY_WORKFLOW

    resolver_step = _LEGACY_WORKFLOW.split(
        "- name: Resolve and seal model capabilities", maxsplit=1
    )[1].split("- name: Ensure protected storage containers", maxsplit=1)[0]
    assert "uv run --frozen --package fdai-core-control-plane python" in resolver_step

    readiness_step = _LEGACY_WORKFLOW.split(
        "- name: Verify production architecture-review evidence", maxsplit=1
    )[1].split("- name: Bind production Terraform inputs", maxsplit=1)[0]
    assert "uv run --frozen --package fdai-core-control-plane python" in readiness_step


def test_platform_workflow_plan_metadata_python_is_compilable() -> None:
    step = _LEGACY_WORKFLOW.split("- name: Store protected plan artifact", maxsplit=1)[1].split(
        "- name: Publish sanitized plan metadata", maxsplit=1
    )[0]
    match = re.search(r"python3 - <<'PY'\n(?P<source>.*?)\n\s+PY", step, re.DOTALL)

    assert match is not None
    source = textwrap.dedent(match.group("source"))
    compile(source, "deploy-dev-plan-metadata", "exec")
    assert "from pathlib import Path" in source


def test_platform_workflow_accepts_plans_without_runtime_image_evidence() -> None:
    restore_step = _LEGACY_WORKFLOW.split(
        "- name: Restore and verify exact protected plan", maxsplit=1
    )[1].split("- name: Claim exact plan apply", maxsplit=1)[0]

    assert "if runtime is None:" in restore_step
    assert 'print("- -")' in restore_step
    assert 'if [[ "$runtime_revision" == "-" ]]' in restore_step
    assert '[[ -z "$APPLY_RUNTIME_IMAGE_REVISION" ]]' in restore_step


def test_operator_catalog_materialization_runs_after_schema_migration() -> None:
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    normalized_root = " ".join(root.split())
    outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
    variables = (_ROOT / "infra/modules/operator-api/container-app/variables.tf").read_text(
        encoding="utf-8"
    )

    assert "catalog_image = var.core_image" in normalized_root
    assert 'regex("@sha256:[0-9a-f]{64}$", var.catalog_image)' in variables
    assert 'resource "azurerm_container_app_job" "materialize_catalogs"' in (
        _LEGACY_OPERATOR_MODULE
    )
    assert 'args    = ["/app/scripts/deployment/local/materialize-authoritative-catalogs.py"]' in (
        _LEGACY_OPERATOR_MODULE
    )
    assert 'name        = "FDAI_STATE_STORE_DSN"' in _LEGACY_OPERATOR_MODULE
    assert "operator_api_catalog_job_name" in outputs
    assert "materialize-authoritative-catalogs.py" in _CORE_DOCKERFILE
    assert _LEGACY_WORKFLOW.index("bootstrap-service-migrations.sh") < _LEGACY_WORKFLOW.index(
        "operator_api_catalog_job_name"
    )


def test_console_publish_binds_auth_and_verifies_exact_static_artifact() -> None:
    assert "scripts/deployment/azure/publish-console.sh infra" in _LEGACY_WORKFLOW
    assert "ENTRA_CONSOLE_API_SCOPE" in _LEGACY_WORKFLOW
    assert 'hostname="${hostname:-${CONSOLE_DEFAULT_HOSTNAME:-}}"' in _CONSOLE_PUBLISHER
    assert 'resource_id="${resource_id:-${CONSOLE_STATIC_WEB_APP_ID:-}}"' in _CONSOLE_PUBLISHER
    assert "console Static Web App belongs to a different subscription" in _CONSOLE_PUBLISHER
    assert "console Static Web App hostname does not match its resource id" in _CONSOLE_PUBLISHER
    assert 'npm --prefix "$repo_root/console" run build' in _CONSOLE_PUBLISHER
    assert "SWA_CLI_DEPLOYMENT_TOKEN" in _CONSOLE_PUBLISHER
    assert "sha256sum --check --status" in _CONSOLE_PUBLISHER
    assert '"https://$hostname/ontology"' in _CONSOLE_PUBLISHER


def test_ingestion_migration_image_is_independently_pinned() -> None:
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    module = (_ROOT / "infra/modules/ingestion-gateway/container-app/main.tf").read_text(
        encoding="utf-8"
    )

    assert 'variable "ingestion_migration_image"' in variables
    assert 'regex("@sha256:[0-9a-f]{64}$", var.ingestion_migration_image)' in variables
    assert "migration_image              = var.ingestion_migration_image" in root
    worker = module.split('resource "azurerm_container_app" "worker"', 1)[1].split(
        'resource "azurerm_container_app_job" "migrate"', 1
    )[0]
    migration = module.split('resource "azurerm_container_app_job" "migrate"', 1)[1]
    assert 'image   = var.migration_image == "" ? var.image : var.migration_image' not in worker
    assert 'image   = var.migration_image == "" ? var.image : var.migration_image' in migration
    assert "TF_VAR_ingestion_migration_image" in _LEGACY_WORKFLOW


def test_legacy_executor_uses_independent_service_distribution() -> None:
    module_match = re.search(
        r'module "isolated_executor" \{(?P<body>.*?)\n\}',
        _LEGACY_ROOT,
        re.DOTALL,
    )

    assert module_match is not None
    module_body = module_match.group("body")
    assert re.search(r"^\s*count\s*=\s*0$", module_body, re.MULTILINE)
    assert 'service_distribution         = "fdai-isolated-executor-service"' in module_body
    assert 'service_entrypoint           = "fdai-isolated-executor-service"' in module_body


def test_legacy_platform_disables_all_migrated_service_apps() -> None:
    operator_app = re.search(
        r'resource "azurerm_container_app" "operator_api" \{(?P<body>.*?)\n\}',
        _LEGACY_OPERATOR_MODULE,
        re.DOTALL,
    )
    ingestion_app = re.search(
        r'resource "azurerm_container_app" "ingestion" \{(?P<body>.*?)\n\}',
        _LEGACY_INGESTION_MODULE,
        re.DOTALL,
    )
    ingestion_worker = re.search(
        r'resource "azurerm_container_app" "worker" \{(?P<body>.*?)\n\}',
        _LEGACY_INGESTION_MODULE,
        re.DOTALL,
    )

    for resource_match in (operator_app, ingestion_app, ingestion_worker):
        assert resource_match is not None
        assert re.search(r"^\s*count\s*=\s*0$", resource_match.group("body"), re.MULTILINE)

    assert 'resource "azurerm_container_app_job" "migrate"' in _LEGACY_OPERATOR_MODULE
    assert 'resource "azurerm_container_app_job" "migrate"' in _LEGACY_INGESTION_MODULE
    assert "az containerapp show" in _LEGACY_WORKFLOW
    assert "properties.configuration.ingress.fqdn" in _LEGACY_WORKFLOW
    assert "../scripts/deployment/azure/run_live_preflight.py" in _LEGACY_WORKFLOW
    assert "../.venv/bin/fdaictl deploy preflight" not in _LEGACY_WORKFLOW


def test_workflow_pins_every_action_to_trusted_immutable_commit() -> None:
    uses = re.findall(r"^\s*uses:\s+([^\s#]+)", _WORKFLOW, re.MULTILINE)

    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)
    for action, sha in _ACTION_PINS.items():
        assert f"{action}@{sha}" in uses


def test_workflow_defaults_to_plan_and_requires_exact_apply_coordinates() -> None:
    assert "default: false" in _WORKFLOW
    assert "if: ${{ !inputs.apply && !inputs.migrate_state }}" in _WORKFLOW
    assert "if: ${{ inputs.apply }}" in _WORKFLOW
    assert "apply and migrate_state are mutually exclusive." in _WORKFLOW
    assert "service-state-migration-{0}" in _WORKFLOW
    assert "service-initial-cutover-{0}" in _WORKFLOW
    assert "inputs.apply && format('service-apply-{0}'" in _WORKFLOW
    for coordinate in ("PLAN_RUN_ID", "PLAN_RUN_ATTEMPT", "PLAN_DIGEST", "CONTEXT_DIGEST"):
        assert f'[[ "${coordinate}" =~' in _WORKFLOW
    assert "migrate_state and initial_cutover are mutually exclusive." in _WORKFLOW
    assert "options: [none, enable, disable]" in _WORKFLOW
    assert "operator channel-edge transitions are valid only for operator-service." in _WORKFLOW
    assert (
        _WORKFLOW.count(
            "OPERATOR_CHANNEL_EDGE_TRANSITION: ${{ inputs.operator_channel_edge_transition }}"
        )
        == 4
    )
    assert (
        _WORKFLOW.count('--operator-channel-edge-transition "$OPERATOR_CHANNEL_EDGE_TRANSITION"')
        == 4
    )
    assert "PREVIOUS_CHANNEL_EDGE_REVISION" in _WORKFLOW
    assert '.operator_channel_edge.service_resource_id // ""' in _WORKFLOW
    assert "planned channel edge is missing before a non-enable transition." in _WORKFLOW


def test_health_verifier_checks_channel_edge_revision_or_removal() -> None:
    assert '.operator_channel_edge.state // "enabled"' in _HEALTH_SCRIPT
    assert "disabled channel edge still exists after protected apply." in _HEALTH_SCRIPT
    assert _HEALTH_SCRIPT.index("disabled channel edge route removal verified.") < (
        _HEALTH_SCRIPT.index("health_deadline=$((SECONDS + 1200))")
    )
    assert "channel edge revision does not match the exact protected image." in _HEALTH_SCRIPT
    assert "del(.operator_channel_edge)" in _HEALTH_SCRIPT
    assert 'deployment_recovery.py" verify' in _HEALTH_SCRIPT
    assert "terraform output -json channel_edge_health_contract" in _HEALTH_SCRIPT


def test_failed_channel_edge_enable_has_guarded_disabled_state_rollback() -> None:
    assert "Prepare disabled channel-edge rollback inputs" in _WORKFLOW
    assert "--operator-channel-edge-enabled false" in _WORKFLOW
    assert "Remove failed newly enabled channel edge" in _WORKFLOW
    assert '-out="$rollback_dir/edge-disable.plan"' in _WORKFLOW
    assert "--operator-channel-edge-transition disable" in _WORKFLOW
    assert '"$rollback_dir/edge-disable.plan"' in _WORKFLOW
    assert "channel edge still exists after automatic disabled-state rollback." in _WORKFLOW
    assert "steps.edge_rollback.outcome" in _WORKFLOW
    assert _WORKFLOW.index("Remove failed newly enabled channel edge") < _WORKFLOW.index(
        "Roll back unhealthy service revision"
    )


def test_workflow_uses_protected_controls_and_protected_commit_ancestry() -> None:
    assert "path: trusted-controls" in _WORKFLOW
    assert "ref: main" in _WORKFLOW
    assert "path: target" not in _WORKFLOW
    assert "TARGET_ROOT" not in _WORKFLOW
    assert '"+refs/heads/main:refs/remotes/origin/main"' in _WORKFLOW
    assert 'git -C "$TRUSTED_CONTROLS" merge-base --is-ancestor' in _WORKFLOW
    assert '"$COMMIT_SHA" refs/remotes/origin/main' in _WORKFLOW
    assert 'git -C "$guard_repo" merge-base --is-ancestor "$TARGET_COMMIT_SHA"' in _WORKFLOW
    assert "TARGET_COMMIT_SHA:$PROTECTED_WORKFLOW_PATH" not in _WORKFLOW
    assert 'TRUSTED_CONTROLS="$GITHUB_WORKSPACE/trusted-controls"' in _WORKFLOW
    assert (
        "TERRAFORM_ROOT=$TRUSTED_CONTROLS/${{ steps.contract.outputs.terraform_root }}" in _WORKFLOW
    )
    for script in ("service_contract.py", "guard_plan.py", "plan_bundle.py", "peer_state.py"):
        assert f'"$TRUSTED_CONTROLS/scripts/deployment/service/{script}"' in _WORKFLOW


def test_workflow_binds_image_attestation_to_source_and_signer() -> None:
    assert "install-pinned-github-cli.sh" in _WORKFLOW
    assert f'version="{_GH_CLI_VERSION}"' in _GH_INSTALLER
    assert f'archive_sha256="{_GH_CLI_ARCHIVE_SHA256}"' in _GH_INSTALLER
    assert "sha256sum --check --strict" in _GH_INSTALLER
    assert '>> "$GITHUB_PATH"' in _GH_INSTALLER
    assert _WORKFLOW.count('--source-digest "$COMMIT_SHA"') == 3
    assert _WORKFLOW.count('--signer-workflow "$ATTESTATION_SIGNER_WORKFLOW"') == 3
    assert '--predicate-type "https://slsa.dev/provenance/v1"' in _WORKFLOW
    assert '--predicate-type "https://spdx.dev/Document/v2.3"' in _WORKFLOW
    assert "container-supply-chain.yml" in _WORKFLOW
    assert "attestations/resolved-models/v1" in _WORKFLOW
    assert "Core image must have one canonical resolved-models digest." in _WORKFLOW
    assert _WORKFLOW.count('--resolved-models-digest "$RESOLVED_MODELS_DIGEST"') == 4


def test_legacy_platform_imports_the_service_specific_core_image() -> None:
    assert 'source_repository="${GITHUB_REPOSITORY,,}/fdai-core-control-plane"' in _IMAGE_BINDER
    assert 'source_repository="${GITHUB_REPOSITORY,,}"' not in _IMAGE_BINDER
    assert '"https://ghcr.io/v2/${source_repository}/manifests/sha-${revision}"' in (_IMAGE_BINDER)
    assert '"registryUri": "ghcr.io"' in _IMAGE_BINDER
    assert '"registryUri": "https://ghcr.io"' not in _IMAGE_BINDER


def test_workflow_validates_source_run_and_actual_plan_controls_checkout() -> None:
    assert 'gh api "repos/$GITHUB_REPOSITORY/actions/runs/$PLAN_RUN_ID"' in _WORKFLOW
    for field in (".id", ".run_attempt", ".conclusion", ".event", ".head_sha", ".path"):
        assert field in _WORKFLOW
    assert '"success"' in _WORKFLOW
    assert '"workflow_dispatch"' in _WORKFLOW
    assert '".github/workflows/service-deploy.yml"' in _WORKFLOW
    assert "-${{ inputs.plan_run_attempt }}" in _WORKFLOW
    assert "merge-base --is-ancestor" in _WORKFLOW
    assert '"$source_head_sha" "$CONTROLS_COMMIT_SHA"' in _WORKFLOW
    assert ".github/workflows/service-deploy.yml" in _WORKFLOW
    comparator = "scripts/deployment/service/deployment_inputs.py"
    assert _WORKFLOW.count(comparator) == 2
    assert _WORKFLOW.count('--repository "$TRUSTED_CONTROLS"') == 2
    assert '--before "$source_head_sha"' in _WORKFLOW
    assert '--before "$plan_controls_commit_sha"' in _WORKFLOW
    assert _WORKFLOW.count('--after "$CONTROLS_COMMIT_SHA"') == 2
    assert 'echo "SOURCE_PLAN_HEAD_SHA=$source_head_sha"' in _WORKFLOW
    assert "Verify plan controls checkout provenance" in _WORKFLOW
    assert 'plan_controls_commit_sha="$(jq -er \'.controls_commit_sha\' "$metadata")"' in _WORKFLOW
    assert '"$SOURCE_PLAN_HEAD_SHA" "$plan_controls_commit_sha"' in _WORKFLOW
    assert '"$plan_controls_commit_sha" "$CONTROLS_COMMIT_SHA"' in _WORKFLOW
    assert 'echo "PLAN_CONTROLS_COMMIT_SHA=$plan_controls_commit_sha"' in _WORKFLOW
    assert _WORKFLOW.index("Download exact protected service plan") < _WORKFLOW.index(
        "Verify plan controls checkout provenance"
    )
    assert _WORKFLOW.count('--controls-commit-sha "$CONTROLS_COMMIT_SHA"') == 1
    assert _WORKFLOW.count('--controls-commit-sha "$PLAN_CONTROLS_COMMIT_SHA"') == 1
    assert _WORKFLOW.index('--controls-commit-sha "$CONTROLS_COMMIT_SHA"') < _WORKFLOW.index(
        '--controls-commit-sha "$PLAN_CONTROLS_COMMIT_SHA"'
    )


def test_workflow_uses_per_service_backend_and_never_platform_root() -> None:
    assert "STATE_RESOURCE_GROUP: ${{ vars.STATE_RESOURCE_GROUP }}" in _WORKFLOW
    assert '-backend-config="resource_group_name=$STATE_RESOURCE_GROUP"' in _WORKFLOW
    assert '-backend-config="key=$BACKEND_KEY"' in _WORKFLOW
    assert "steps.contract.outputs.terraform_root" in _WORKFLOW
    assert 'terraform -chdir="infra"' not in _WORKFLOW
    assert "deploy-dev.yml" in _WORKFLOW
    for service, metadata in _MATRIX["services"].items():
        assert metadata["backend_key_template"] == f"services/{service}/{{environment}}.tfstate"
        assert metadata["terraform_root"] == f"infra/services/{service}"
        assert metadata["allowed_resource_address"] in {
            move["to"] for move in _MIGRATION["services"][service]["moves"]
        }


def test_plan_and_apply_both_verify_image_and_guard_exact_binary_plan() -> None:
    assert _WORKFLOW.count("gh attestation verify") == 3
    assert "manifests/sha-${COMMIT_SHA}" in _WORKFLOW
    assert '[[ "$commit_digest" == "$IMAGE_DIGEST" ]]' in _WORKFLOW
    assert "scripts/deployment/service/service_contract.py" in _WORKFLOW
    assert _WORKFLOW.count("scripts/deployment/service/guard_plan.py") == 3
    assert '--plan-json "$rollback_dir/edge-disable-plan.json"' in _WORKFLOW
    assert 'scripts/deployment/service/plan_bundle.py" create' in _WORKFLOW
    assert 'scripts/deployment/service/plan_bundle.py" verify' in _WORKFLOW
    assert 'cmp "$bundle/service-plan.json" "$RUNNER_TEMP/replayed-service-plan.json"' in _WORKFLOW
    assert '"$RUNNER_TEMP/service-plan-bundle/service.plan"' in _WORKFLOW
    assert _WORKFLOW.count("INITIAL_CUTOVER: ${{ inputs.initial_cutover }}") == 5
    assert _WORKFLOW.count("cutover_args+=(--initial-cutover)") == 3
    assert _WORKFLOW.count('"${cutover_args[@]}"') == 4
    for argument in (
        "--workflow-run-attempt",
        "--tenant-id",
        "--subscription-id",
        "--backend-resource-group",
        "--backend-storage-account",
        "--backend-container",
        "--controls-commit-sha",
        "--attestation-signer-workflow",
    ):
        expected_count = 4 if argument == "--workflow-run-attempt" else 2
        assert _WORKFLOW.count(argument) == expected_count


def test_service_workflow_does_not_expose_completed_event_bus_migration() -> None:
    for retired_token in (
        "event_bus_topic_migration",
        "EVENT_BUS_TOPIC_MIGRATION",
        "event-bus-topic-migration",
    ):
        assert retired_token not in _WORKFLOW


def test_service_workflow_seals_database_host_binding_mode() -> None:
    assert "database_host_binding:" in _WORKFLOW
    assert (
        "Database host binding cannot be combined with state migration, initial cutover, "
        "or channel-edge transition." in _WORKFLOW
    )
    assert _WORKFLOW.count("DATABASE_HOST_BINDING: ${{ inputs.database_host_binding }}") == 4
    assert _WORKFLOW.count("database_args+=(--database-host-binding)") == 3
    assert _WORKFLOW.count('"${database_args[@]}"') == 4
    assert "database-host-binding+model-binding" in _WORKFLOW
    assert "database-host-binding" in _WORKFLOW
    assert 'terraform -chdir="$TRUSTED_CONTROLS/infra" output -raw postgres_fqdn' in _WORKFLOW
    assert "scripts/deployment/service/hydrate_database_host.py" in _WORKFLOW
    assert '--database-host "$database_host"' in _WORKFLOW
    assert "Platform state returned an invalid database hostname." in _WORKFLOW
    assert "output -json event_bus_topics" in _WORKFLOW
    assert 'select(. == "fdai.change.events")' in _WORKFLOW
    assert "scripts/deployment/service/hydrate_event_topic.py" in _WORKFLOW
    assert '--event-topic "$event_topic"' in _WORKFLOW
    assert "output -json event_bus_auxiliary_topics" in _WORKFLOW
    assert 'select(. == "fdai.pipeline.stages")' in _WORKFLOW
    assert 'select(. == "fdai.pantheon.objects")' in _WORKFLOW
    assert '--pipeline-stage-topic "$pipeline_stage_topic"' in _WORKFLOW
    assert '--pantheon-object-topic "$pantheon_object_topic"' in _WORKFLOW


def test_service_workflow_seals_core_model_binding_transition() -> None:
    assert "model_binding_transition:" in _WORKFLOW
    assert "Model binding transition is valid only for core-control-plane." in _WORKFLOW
    assert "Model binding transition can combine only with database host binding." in _WORKFLOW
    assert _WORKFLOW.count("MODEL_BINDING_TRANSITION: ${{ inputs.model_binding_transition }}") == 4
    assert "RESOLVED_MODELS_JSON: ${{ vars.RESOLVED_MODELS_JSON }}" in _WORKFLOW
    assert '[[ "$SERVICE" == "core-control-plane" ]]' in _WORKFLOW
    assert "resolved_model_args+=(--model-binding-transition)" in _WORKFLOW
    assert '"${resolved_model_args[@]}"' in _WORKFLOW
    assert "--model-binding-transition" in _WORKFLOW
    assert _WORKFLOW.count('--resolved-models-digest "$RESOLVED_MODELS_DIGEST"') >= 4
    assert "service-model-binding-apply-{0}" in _WORKFLOW
    assert "database-host-binding+model-binding" in _WORKFLOW
    assert 'name = "LLM_RESOLVED_MODELS_PATH"' in _CORE_TERRAFORM
    assert 'name = "LLM_RESOLVED_MODELS_SHA256"' in _CORE_TERRAFORM
    assert 'name = "FDAI_MODEL_ENDPOINTS_JSON"' in _CORE_TERRAFORM
    assert "var.llm.resolved_models_digest" in _CORE_TERRAFORM
    assert "output -json llm_model_endpoints" in _WORKFLOW


def test_apply_has_post_apply_health_and_no_destroy_command() -> None:
    assert "Verify post-apply service health" in _WORKFLOW
    assert "scripts/deployment/service/verify_health.sh" in _WORKFLOW
    assert "Capture pre-apply rollback snapshot" in _WORKFLOW
    assert "Roll back unhealthy service revision" in _WORKFLOW
    assert "verify-rollback" in _WORKFLOW
    assert "Fail deployment after automatic rollback" in _WORKFLOW
    assert "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER=0" not in _WORKFLOW
    assert '"$rollback_dir/snapshot.json"' in _WORKFLOW
    assert ".planned_values.outputs.rollback_contract.value" in _WORKFLOW
    assert "output -json rollback_contract" not in _WORKFLOW
    assert "authority was unchanged" in _WORKFLOW
    assert "protected platform rollback is required" in _WORKFLOW
    assert '--revision-suffix "r${GITHUB_RUN_ID}"' in _WORKFLOW
    assert "failed-revisions-before.json" in _WORKFLOW
    assert "rollback revision inventory has invalid primary container layout" in _WORKFLOW
    assert '--arg image "${{ inputs.image_ref }}"' in _WORKFLOW
    assert (
        "rollback requires exactly one active revision for the failed protected image" in _WORKFLOW
    )
    assert "az containerapp revision deactivate" in _WORKFLOW
    assert (
        "[[ \"$(jq -r '.properties.active' "
        '"$rollback_dir/failed-revision-after.json")" == "false" ]]' in _WORKFLOW
    )
    assert "rollback-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" not in _WORKFLOW
    assert "terraform destroy" not in _WORKFLOW
    assert "max_inactive_revisions       = 1" in _SERVICE_CONTAINER_APP


def test_core_startup_probe_uses_the_operational_event_bus() -> None:
    assert (
        '{ name = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", '
        "value = var.platform.operational_kafka_bootstrap_servers }" in _CORE_TERRAFORM
    )
    assert (
        '{ name = "FDAI_STARTUP_KAFKA_PROBE_TOPIC", value = var.event_topics.startup_probe }'
        in _CORE_TERRAFORM
    )


def test_service_deploy_bootstraps_service_migrations() -> None:
    migration_index = _WORKFLOW.index("Apply service-owned database migrations")
    snapshot_index = _WORKFLOW.index("Capture pre-apply rollback snapshot")
    apply_index = _WORKFLOW.index("Apply exact protected service plan")
    assert migration_index < snapshot_index < apply_index
    assert "migration_dsn_secret_name" in _WORKFLOW
    assert "az keyvault secret show" in _WORKFLOW
    assert _WORKFLOW.count("migration_deadline=$((SECONDS + 1200))") == 1
    assert "remaining=$((migration_deadline - SECONDS))" in _WORKFLOW
    assert 'timeout --kill-after=30s "${remaining}s" "$@"' in _WORKFLOW
    assert 'export FDAI_DATABASE_URL="$migration_dsn"' in _WORKFLOW
    assert "run_migration env FDAI_DATABASE_URL=" not in _WORKFLOW
    assert "service migration exceeded its 20-minute stage deadline" in _WORKFLOW
    assert 'if [[ "$INITIAL_CUTOVER" == "true" ]]' in _WORKFLOW
    legacy_upgrade = "alembic upgrade head"
    assert legacy_upgrade in _WORKFLOW
    assert 'cd "$TRUSTED_CONTROLS"' in _WORKFLOW
    service_bootstrap = '"$migration_command" bootstrap'
    assert _WORKFLOW.index(legacy_upgrade) < _WORKFLOW.index(service_bootstrap)
    assert "prepare-adoption" not in _WORKFLOW
    assert "stamp-baseline" not in _WORKFLOW
    assert "Upload service migration adoption evidence" in _WORKFLOW
    assert "service-migration-adoption-${{ inputs.service }}" in _WORKFLOW
    assert "if-no-files-found: ignore" in _WORKFLOW
    assert "retention-days: 90" in _WORKFLOW
    assert "-destroy" not in _WORKFLOW
    assert "az containerapp secret set" in _WORKFLOW
    assert "previous_secrets[]" in _WORKFLOW
    assert "sleep 5" in _WORKFLOW
    assert ".properties.latestRevisionName" in _HEALTH_SCRIPT
    assert ".latest_revision_name" not in _HEALTH_SCRIPT
    assert "health_deadline=$((SECONDS + 1200))" in _HEALTH_SCRIPT
    assert "while ((SECONDS < health_deadline))" in _HEALTH_SCRIPT
    assert ".target.image_ref" in _HEALTH_SCRIPT
    assert '"$revision_name" != "$previous_revision"' in _HEALTH_SCRIPT
    assert '"$observed_image" == "$expected_image"' in _HEALTH_SCRIPT
    assert "az containerapp revision activate" in _HEALTH_SCRIPT


def test_health_poll_reports_progress_and_fails_on_its_own_deadline() -> None:
    assert "health poll: revision=" in _HEALTH_SCRIPT
    assert _HEALTH_SCRIPT.index("health poll: revision=") < _HEALTH_SCRIPT.index("  sleep 5")
    assert "health_converged=true" in _HEALTH_SCRIPT
    assert 'if [[ "$health_converged" != true ]]; then' in _HEALTH_SCRIPT
    assert "within its 1200s health deadline" in _HEALTH_SCRIPT


def test_every_deploy_command_declares_a_budget() -> None:
    """The six-hour runner default cannot tell a stalled provider from a slow apply."""
    assert "timeout 120s python3" in _HEALTH_SCRIPT
    assert "timeout 30s python3 -c" in _HEALTH_SCRIPT
    assert "\n    timeout-minutes: 180\n" in _LEGACY_WORKFLOW
    assert "\n    timeout-minutes: 120\n" in _WORKFLOW


def test_apply_failure_uses_the_same_verified_rollback_path() -> None:
    rollback_condition = (
        "if: ${{ inputs.apply && (steps.apply.outcome == 'failure' || "
        "steps.health.outcome == 'failure') }}"
    )
    final_failure_condition = (
        "if: ${{ always() && inputs.apply && (steps.apply.outcome == 'failure' || "
        "steps.health.outcome == 'failure') }}"
    )
    assert "id: apply\n        continue-on-error: true" in _WORKFLOW
    assert "if: ${{ inputs.apply && steps.apply.outcome == 'success' }}" in _WORKFLOW
    assert _WORKFLOW.count(rollback_condition) == 1
    assert "id: rollback\n        continue-on-error: true" in _WORKFLOW
    assert _WORKFLOW.count(final_failure_condition) == 1
    assert '[[ "${{ steps.rollback.outcome }}" != "success" ]]' in _WORKFLOW
    assert "rollback_health_deadline=$((SECONDS + 1200))" in _WORKFLOW
    assert 'if [[ "$rollback_health_converged" != true ]]; then' in _WORKFLOW


def test_service_and_legacy_workflows_enforce_state_cutover_fence() -> None:
    assert "Verify service state cutover ownership" in _WORKFLOW
    assert 'state_migration.py" verify' in _WORKFLOW
    assert "--phase post" in _WORKFLOW
    assert "Guard migrated runtimes from legacy recreation" in _LEGACY_WORKFLOW
    assert "scripts/deployment/service/state_migration.py guard-legacy-plan" in _LEGACY_WORKFLOW


def test_state_migration_uses_remote_legacy_backend_and_verified_restore_helper() -> None:
    assert 'backend "azurerm" {}' in _WORKFLOW
    assert '-backend-config="key=fdai-${ENVIRONMENT}.tfstate"' in _WORKFLOW
    assert "Migrate service state ownership" in _WORKFLOW
    assert 'migrate_state.sh"' in _WORKFLOW
    assert '"$backup_dir" \\' in _WORKFLOW
    assert "            --execute" in _WORKFLOW
    assert "Verify migrated service state ownership" in _WORKFLOW
    assert 'terraform -chdir="$TRUSTED_CONTROLS/infra" state pull' in _WORKFLOW
    assert 'terraform -chdir="$TERRAFORM_ROOT" state pull' in _WORKFLOW
    assert "terraform show -json" not in _WORKFLOW


def test_plan_and_apply_capture_four_peer_states_and_upload_sealed_receipts() -> None:
    assert "Capture peer states before deployment" in _WORKFLOW
    assert "Capture peer states after plan" in _WORKFLOW
    assert "Capture peer states after apply" in _WORKFLOW
    assert _WORKFLOW.count("capture_peer_states.sh") == 3
    assert "Verify peer isolation and seal receipt" in _WORKFLOW
    assert 'peer_state.py" verify' in _WORKFLOW
    assert '--mode "$DEPLOYMENT_MODE"' in _WORKFLOW
    assert '--plan-digest "$PLAN_DIGEST"' in _WORKFLOW
    assert '--context-digest "$CONTEXT_DIGEST"' in _WORKFLOW
    assert "Upload peer isolation receipt" in _WORKFLOW
    assert "service-peer-isolation-${{ inputs.service }}" in _WORKFLOW
    assert "retention-days: 90" in _WORKFLOW
    assert "service-peer-state-before" in _WORKFLOW
    assert "service-peer-state-after" in _WORKFLOW
    assert "service-peer-isolation-receipt.json" in _WORKFLOW
    assert "Seal live service observations" in _WORKFLOW
    assert 'live_observation.py"' in _WORKFLOW


def test_peer_capture_reads_exact_isolated_backend_blobs() -> None:
    assert "az storage blob download" in _PEER_CAPTURE
    assert '--name "$backend_key"' in _PEER_CAPTURE
    assert "--auth-mode login" in _PEER_CAPTURE
    assert "terraform -chdir" not in _PEER_CAPTURE
    assert "timeout 60s" in _PEER_CAPTURE
    assert "Upload live service observations" in _WORKFLOW
    assert "service-live-observations-${{ inputs.service }}" in _WORKFLOW

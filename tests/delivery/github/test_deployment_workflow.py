"""GitHub Actions deployment workflow transport tests."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import yaml

from fdai.delivery.github.deployment_workflow import (
    GitHubActionsDeploymentTransport,
    GitHubDeploymentWorkflowConfig,
)
from fdai.deployment_cli.remote import (
    DeploymentPlanContext,
    PlanStatus,
    RemoteDeploymentError,
    deployment_context_digest,
)

_TENANT = UUID("00000000-0000-0000-0000-000000000001")
_SUBSCRIPTION = UUID("00000000-0000-0000-0000-000000000002")


def _context() -> DeploymentPlanContext:
    return DeploymentPlanContext(
        tenant_id=_TENANT,
        subscription_id=_SUBSCRIPTION,
        environment="dev",
        bundle_digest="a" * 64,
        commit_sha="b" * 40,
        backend_ref="backend:dev",
        runner_ref="runner:private",
        deploy_console=True,
        deploy_design_mocks=False,
        deploy_operator_api=True,
        deploy_dev_operations_gateway=True,
        deploy_document_ingestion=True,
    )


async def _token() -> str:
    return "test-token"  # noqa: S105 - deterministic fake


def _transport(handler: httpx.MockTransport) -> GitHubActionsDeploymentTransport:
    return GitHubActionsDeploymentTransport(
        config=GitHubDeploymentWorkflowConfig(repository="example/fdai"),
        http_client=httpx.AsyncClient(transport=handler),
        token_provider=_token,
    )


async def test_submit_plan_dispatches_hashed_plan_only_context() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/actions/workflows/deploy-dev.yml/dispatches")
        assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
        payload = request.read().decode("utf-8")
        assert str(_TENANT) not in payload
        assert str(_SUBSCRIPTION) not in payload
        assert "backend:dev" not in payload
        assert "runner:private" not in payload
        parsed = json.loads(payload)
        assert parsed["inputs"]["apply"] is False
        assert parsed["inputs"]["commit_sha"] == "b" * 40
        assert parsed["inputs"]["deploy_console"] is True
        assert parsed["inputs"]["deploy_design_mocks"] is False
        assert parsed["inputs"]["deploy_operator_api"] is True
        assert parsed["inputs"]["deploy_dev_operations_gateway"] is True
        assert parsed["inputs"]["deploy_document_ingestion"] is True
        assert len(parsed["inputs"]["context_digest"]) == 64
        return httpx.Response(
            200,
            json={
                "workflow_run_id": 123,
                "html_url": "https://github.com/example/fdai/actions/runs/123",
            },
        )

    submission = await _transport(httpx.MockTransport(handle)).submit_plan(_context())

    assert submission.submission_id == "123"
    assert submission.workflow_url.endswith("/actions/runs/123")


async def test_dispatch_error_is_sanitized() -> None:
    transport = _transport(
        httpx.MockTransport(lambda _request: httpx.Response(403, text="token detail"))
    )

    with pytest.raises(RemoteDeploymentError, match="HTTP 403") as error:
        await transport.submit_plan(_context())

    assert "token detail" not in str(error.value)


async def test_invalid_plan_id_fails_closed() -> None:
    transport = _transport(httpx.MockTransport(lambda _request: httpx.Response(500)))

    with pytest.raises(RemoteDeploymentError, match="plan_id is invalid"):
        await transport.get_plan("plan-1")


async def test_submit_apply_dispatches_exact_opaque_plan_context() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["inputs"]["apply"] is True
        assert payload["inputs"]["plan_id"] == "plan-123-1"
        assert payload["inputs"]["plan_digest"] == "c" * 64
        assert payload["inputs"]["request_id"].startswith("apply-")
        assert payload["inputs"]["deploy_console"] is True
        assert payload["inputs"]["deploy_design_mocks"] is False
        assert payload["inputs"]["deploy_operator_api"] is True
        assert payload["inputs"]["deploy_dev_operations_gateway"] is True
        assert payload["inputs"]["deploy_document_ingestion"] is True
        assert payload["inputs"]["resume_verification"] is False
        serialized = json.dumps(payload)
        assert str(_TENANT) not in serialized
        assert str(_SUBSCRIPTION) not in serialized
        assert "backend:dev" not in serialized
        assert "runner:private" not in serialized
        return httpx.Response(
            200,
            json={
                "workflow_run_id": 124,
                "html_url": "https://github.com/example/fdai/actions/runs/124",
            },
        )

    submission = await _transport(httpx.MockTransport(handle)).submit_apply(
        plan_id="plan-123-1",
        plan_digest="c" * 64,
        context=_context(),
    )

    assert submission.submission_id == "124"


async def test_submit_apply_dispatches_verification_resume() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["inputs"]["apply"] is True
        assert payload["inputs"]["resume_verification"] is True
        return httpx.Response(
            200,
            json={
                "workflow_run_id": 125,
                "html_url": "https://github.com/example/fdai/actions/runs/125",
            },
        )

    submission = await _transport(httpx.MockTransport(handle)).submit_apply(
        plan_id="plan-123-1",
        plan_digest="c" * 64,
        context=_context(),
        resume_verification=True,
    )

    assert submission.submission_id == "125"


def _metadata_archive(metadata: dict[str, object]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("plan-metadata.json", json.dumps(metadata))
    return output.getvalue()


async def test_get_plan_reads_bounded_digest_only_metadata() -> None:
    now = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    metadata = {
        "schema_version": "fdai.deployment-plan.v1",
        "plan_id": "plan-123-1",
        "plan_digest": "c" * 64,
        "context_digest": deployment_context_digest(_context()),
        "commit_sha": "b" * 40,
        "request_id": "plan-request",
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "status": "ready",
        "workflow_run_id": "123",
    }
    archive = _metadata_archive(metadata)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs/123/artifacts"):
            assert request.url.params["name"] == "deployment-plan-plan-123-1"
            return httpx.Response(
                200,
                json={
                    "artifacts": [
                        {
                            "id": 42,
                            "name": "deployment-plan-plan-123-1",
                            "expired": False,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/actions/artifacts/42/zip"):
            return httpx.Response(200, content=archive)
        if request.url.path.endswith("/actions/artifacts"):
            return httpx.Response(200, json={"artifacts": []})
        return httpx.Response(404)

    record = await _transport(httpx.MockTransport(handle)).get_plan("plan-123-1")

    assert record.context is None
    assert record.context_digest == deployment_context_digest(_context())
    assert record.plan_digest == "c" * 64
    assert record.status is PlanStatus.READY


async def test_get_plan_rejects_expired_metadata_artifact() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "artifacts": [
                    {
                        "id": 42,
                        "name": "deployment-plan-plan-123-1",
                        "expired": True,
                    }
                ]
            },
        )

    with pytest.raises(RemoteDeploymentError, match="has expired"):
        await _transport(httpx.MockTransport(handle)).get_plan("plan-123-1")


@pytest.mark.parametrize(
    ("artifact_name", "expected"),
    (
        ("deployment-apply-claim-plan-123-1", PlanStatus.APPLYING),
        ("deployment-apply-receipt-plan-123-1", PlanStatus.APPLIED),
    ),
)
async def test_get_plan_projects_apply_status(
    artifact_name: str,
    expected: PlanStatus,
) -> None:
    now = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    metadata = {
        "schema_version": "fdai.deployment-plan.v1",
        "plan_id": "plan-123-1",
        "plan_digest": "c" * 64,
        "context_digest": deployment_context_digest(_context()),
        "commit_sha": "b" * 40,
        "request_id": "plan-request",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "status": "ready",
        "workflow_run_id": "123",
    }
    archive = _metadata_archive(metadata)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs/123/artifacts"):
            return httpx.Response(
                200,
                json={
                    "artifacts": [
                        {
                            "id": 42,
                            "name": "deployment-plan-plan-123-1",
                            "expired": False,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/actions/artifacts/42/zip"):
            return httpx.Response(200, content=archive)
        if request.url.path.endswith("/actions/artifacts"):
            requested = request.url.params["name"]
            artifacts = (
                [{"id": 43, "name": requested, "expired": False}]
                if requested == artifact_name
                else []
            )
            return httpx.Response(200, json={"artifacts": artifacts})
        return httpx.Response(404)

    record = await _transport(httpx.MockTransport(handle)).get_plan("plan-123-1")

    assert record.status is expected


def test_config_rejects_unsafe_repository_ref_and_endpoint() -> None:
    with pytest.raises(ValueError):
        GitHubDeploymentWorkflowConfig(repository="not-a-repository")
    with pytest.raises(ValueError):
        GitHubDeploymentWorkflowConfig(repository="example/fdai", ref="../main")
    with pytest.raises(ValueError):
        GitHubDeploymentWorkflowConfig(
            repository="example/fdai",
            api_base="http://api.github.com",
        )


def test_runner_workflow_declares_and_validates_dispatch_context() -> None:
    workflow = (
        Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
    ).read_text(encoding="utf-8")

    for field in (
        "request_id:",
        "context_digest:",
        "commit_sha:",
        "plan_id:",
        "plan_digest:",
    ):
        assert field in workflow
    assert "Validate remote plan request" in workflow
    assert "Prepare self-hosted runner workspace" in workflow
    assert 'legacy_cache="$GITHUB_WORKSPACE/infra/None"' in workflow
    assert 'sudo -n rm -rf -- "$legacy_cache"' in workflow
    assert 'azure_config_dir="$RUNNER_TEMP/azure-cli"' in workflow
    assert 'echo "AZURE_CONFIG_DIR=$azure_config_dir" >> "$GITHUB_ENV"' in workflow
    assert "resume_verification:" in workflow
    assert "deploy_isolated_executor:" in workflow
    assert "TF_VAR_enable_isolated_executor: ${{ inputs.deploy_isolated_executor }}" in workflow
    assert "DEPLOY_ISOLATED_EXECUTOR: ${{ inputs.deploy_isolated_executor }}" in workflow
    assert '|| "$DEPLOY_ISOLATED_EXECUTOR" == "true"' in workflow
    assert "ref: ${{ inputs.commit_sha != '' && inputs.commit_sha || github.sha }}" in workflow
    assert '"$PLAN_COMMIT_SHA" != "$(git rev-parse HEAD)"' in workflow
    assert '"$APPLY_COMMIT_SHA" != "$(git rev-parse HEAD)"' in workflow
    assert "--name deployment-plans" in workflow
    assert "sha256sum dev.plan" in workflow
    assert "TF_CLI_ARGS_plan:" in workflow
    assert "-target=azurerm_function_app_flex_consumption.dev_gateway[0]" in workflow
    assert "-target=module.compute.azurerm_container_app.core" in workflow
    assert "-target=module.compute.azurerm_container_app_job.canary[0]" in workflow
    assert "-target=module.compute.azurerm_container_app_job.inventory[0]" in workflow
    assert "-target=module.operator_api[0]" in workflow
    assert "-target=module.ingestion_gateway[0]" in workflow
    assert "-target=module.isolated_executor[0]" in workflow
    assert "-target=azurerm_role_assignment.inventory_eventhubs_raw_sender" in workflow
    assert (
        "-target=azurerm_eventgrid_system_topic_event_subscription.inventory_resource_changes[0]"
        in workflow
    )
    for moved_target in (
        "azurerm_role_assignment.operator_api_acr_pull",
        "azurerm_role_assignment.operator_api_kv_secrets_user",
        "azurerm_role_assignment.operator_api_reader",
        "azurerm_role_assignment.read_api_acr_pull",
        "azurerm_role_assignment.read_api_kv_secrets_user",
        "azurerm_role_assignment.read_api_reader",
        "module.operator_api_identity[0].azurerm_user_assigned_identity.primary",
        "module.read_api[0].azurerm_container_app.read_api",
        "module.read_api[0].azurerm_container_app_job.migrate",
        "module.read_api_identity[0].azurerm_user_assigned_identity.primary",
        "module.llm_azure_openai[0].azurerm_cognitive_account.primary",
        "module.llm_azure_openai[0].azurerm_role_assignment.additional_openai_user",
        "azurerm_role_assignment.runtime_startup_probe_eventhubs_owner",
    ):
        assert f"-target={moved_target}" in workflow
    assert "Build development operations gateway source artifact" in workflow
    assert 'source = Path("../delivery/dev_operations_gateway")' in workflow
    assert "source_artifact_digest" in workflow
    assert "source-artifact.zip" in workflow
    assert "module.console[0].azurerm_static_web_app.console" in workflow
    assert 'az resource show --ids "$static_site_id"' in workflow
    assert "Verify existing exact apply claim" in workflow
    assert "existing apply claim does not match the exact plan" in workflow
    assert "inputs.apply && !inputs.resume_verification" in workflow
    assert "--source-artifact fdai-dev-operations-gateway.zip" in workflow
    assert "check-runner-egress.py" in workflow
    assert "PREFLIGHT_NETWORK_CHECKS_JSON" in workflow
    assert "check-network-connectivity.py" in workflow
    assert "--profile custom" in workflow
    assert "--redact" in workflow
    assert 'egress["network_connectivity"] = network' in workflow
    for output_name in (
        "event_bus_kafka_bootstrap",
        "event_bus_operational_kafka_bootstrap",
        "postgres_fqdn",
        "key_vault_uri",
        "container_registry_login_server",
        "llm_endpoint",
    ):
        assert f'terraform output -raw "{output_name}"' in workflow
    assert "preflight_evidence_digest" in workflow
    assert "DEPLOY_PREFLIGHT_INPUT_JSON is required for protected plans" in workflow
    assert "TF_VAR_stewardship_maintainers" in workflow
    assert "TF_VAR_stewardship_agent_bindings" in workflow
    assert "runner preflight profile must require all Azure live categories" in workflow
    assert "Run complete Azure live preflight" in workflow
    assert "latest revision is not healthy" in workflow
    assert "Provisioned:Healthy" in workflow
    health_step = workflow[workflow.index("- name: Verify deployed health endpoints") :]
    health_step = health_step[: health_step.index("- name: Run canary publisher smoke")]
    assert "if: ${{ inputs.apply && !inputs.deploy_design_mocks }}" in health_step
    assert 'apps=("$(terraform output -raw core_app_name)")' in health_step
    assert 'apps+=("$(terraform output -raw operator_api_name)")' in health_step
    assert "terraform output -json isolated_executor_shadow" in health_step
    assert 'apps+=("$executor_app")' in health_step
    assert 'apps+=("$(terraform output -raw ingestion_gateway_name)")' in health_step
    assert "Reject destructive protected plan" in workflow
    assert 'if "delete" in change.get("change", {}).get("actions", [])' in workflow
    assert "Protected plans reject delete or replacement actions" in workflow
    assert "uv sync --locked" in workflow
    assert "fdaictl deploy preflight" in workflow
    assert "azure_preflight_evidence_digest" in workflow
    assert "azure-preflight-evidence.json" in workflow
    assert '"preflight_blocks": False' in workflow
    assert "preflight-evidence.json" in workflow
    assert "--overwrite false" in workflow
    assert '"expires_at": os.environ["EXPIRES_AT"]' in workflow
    assert "actions/upload-artifact@v7.0.1" in workflow
    assert "path: infra/plan-metadata.json" in workflow
    assert "path: infra/dev.plan" not in workflow
    assert "cleanup-deployment-plans.py" in workflow
    assert "--num-results 1001" in workflow
    assert "xargs -r -P 8" in workflow
    assert "--container-name deployment-plans --name '{}'" in workflow
    assert "< expired-plan-blobs.txt" in workflow
    assert "Validate exact apply request" in workflow
    assert workflow.index("az account clear") < workflow.index(
        "az login --identity --allow-no-subscriptions"
    )
    assert "Restore and verify exact protected plan" in workflow
    assert "verify-deployment-plan.py" in workflow
    assert "--azure-preflight-evidence plan-azure-preflight-evidence.json" in workflow
    assert "Claim exact plan apply" in workflow
    assert "apply-claim.json" in workflow
    assert "Record exact plan apply receipt" in workflow
    assert "apply-receipt.json" in workflow
    assert "deployment-apply-claim-${{ inputs.plan_id }}" in workflow
    assert "deployment-apply-receipt-${{ inputs.plan_id }}" in workflow
    assert "path: infra/apply-claim.json" in workflow
    assert "path: infra/apply-receipt.json" in workflow
    assert workflow.count("--overwrite false") >= 4
    assert "environment: ${{ inputs.apply && inputs.environment || 'plan-only' }}" in workflow
    assert "if: ${{ !inputs.apply }}\n        run: terraform plan" in workflow
    assert "Verify Terraform convergence" in workflow
    assert "TF_VAR_operator_api_web_search_enabled" in workflow
    assert "TF_VAR_operator_api_web_search_allowed_domains" in workflow
    assert "vars.ENABLE_LLM == 'true' || vars.OPERATOR_API_WEB_SEARCH_ENABLED == 'true'" in workflow
    assert "Reconcile Foundry web-search agent" in workflow
    assert "foundry_web_search_project_endpoint" in workflow
    assert "fdai.delivery.azure.foundry_agent_reconciler" in workflow
    assert workflow.index("Verify Terraform convergence") < workflow.index(
        "Reconcile Foundry web-search agent"
    )
    assert "-detailed-exitcode" in workflow
    assert "Prepare exact development operations gateway source" in workflow
    assert "Publish exact development operations gateway source" in workflow
    assert "Verify exact development operations gateway source" in workflow
    assert "dev_operations_gateway_app_name" in workflow
    assert "uses: Azure/functions-action@v1.5.6" in workflow
    assert "remote-build: true" in workflow
    assert "functions?api-version=2024-04-01" in workflow
    assert "az functionapp function list" not in workflow
    assert "Verify deployed health endpoints" in workflow
    assert "continue-on-error: true" not in workflow
    assert workflow.index("Verify deployed health endpoints") < workflow.index(
        "Record exact plan apply receipt"
    )


def test_gateway_source_deployment_is_owned_by_the_workflow() -> None:
    root = Path(__file__).resolve().parents[3]
    terraform = (root / "infra" / "main.tf").read_text(encoding="utf-8")
    requirements = (root / "delivery" / "dev_operations_gateway" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    workflow = (root / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")

    assert "azure-functions==1.24.0" in requirements.splitlines()
    assert 'data "archive_file" "dev_gateway"' not in terraform
    assert "zip_deploy_file" not in terraform
    assert "AzureWebJobsStorage__accountName" in terraform
    assert "AzureWebJobsStorage__clientId" in terraform
    assert 'resource "azurerm_role_assignment" "dev_gateway_storage_host"' in terraform
    assert 'role_definition_name = "Storage Blob Data Owner"' in terraform
    assert 'resource "azurerm_storage_container" "dev_gateway_idempotency"' in terraform
    assert "FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL" in terraform
    assert 'module "event_bus_auxiliary"' in terraform
    assert "defender_storage_data_scanner" in terraform
    assert "Microsoft.Security/datascanners/StorageDataScanner" in terraform
    postgres = (root / "infra" / "modules" / "state-store" / "postgres-flex" / "main.tf").read_text(
        encoding="utf-8"
    )
    assert 'value     = "VECTOR,PG_TRGM"' in postgres
    assert re.search(
        r"topics\s*=\s*\[local\.canary_topic, local\.startup_probe_topic, "
        r"local\.executor_command_topic\]",
        terraform,
    )
    assert re.search(
        r"auxiliary_topics\s*=\s*\[local\.inventory_raw_topic, "
        r"local\.executor_receipt_topic\]",
        terraform,
    )
    assert "module.event_bus_auxiliary.kafka_bootstrap" in terraform
    assert 'resource "azurerm_eventgrid_system_topic" "inventory_resource_changes"' in terraform
    assert re.search(r'topic_type\s*=\s*"microsoft.resources.subscriptions"', terraform)
    assert re.search(r'location\s*=\s*"global"', terraform)
    assert "source_resource_id" in terraform
    assert "source_arm_resource_id" not in terraform
    assert 'data "azurerm_resources" "eventgrid_system_topics"' in terraform
    assert "tracked_subscription_system_topics" in terraform
    assert "multiple tracked Event Grid system topics" in terraform
    assert "to = azurerm_eventgrid_system_topic.inventory_resource_changes[0]" in terraform
    assert "identity_ids = [module.inventory_identity.resource_id]" in terraform
    assert 'resource "azurerm_eventgrid_system_topic_event_subscription"' in terraform
    assert "system_topic          = azurerm_eventgrid_system_topic" in terraform
    assert "module.event_bus_auxiliary.topic_ids[local.canary_topic]" in terraform
    assert (
        terraform.count("module.event_bus_auxiliary.auxiliary_topic_ids[local.inventory_raw_topic]")
        >= 2
    )
    assert "module.event_bus.auxiliary_topic_ids[local.inventory_raw_topic]" not in terraform
    gateway_resource = terraform.split(
        'resource "azurerm_function_app_flex_consumption" "dev_gateway"',
        maxsplit=1,
    )[1]
    gateway_app_settings = gateway_resource.split("app_settings = {", maxsplit=1)[1].split(
        "\n  }", maxsplit=1
    )[0]
    assert re.search(
        r'FDAI_DEV_GATEWAY_MUTATIONS_ENABLED\s*=\s*"1"',
        gateway_app_settings,
    )
    assert re.search(
        r'AzureWebJobsStorage__credential\s*=\s*"managedidentity"',
        gateway_app_settings,
    )
    assert "allowed_applications = [module.identity.client_id]" in gateway_resource
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in gateway_app_settings
    assert workflow.index("Restore and verify exact protected plan") < workflow.index(
        "Terraform apply"
    )
    assert workflow.index("Verify Terraform convergence") < workflow.index(
        "Prepare exact development operations gateway source"
    )
    deploy_step = workflow.index("Prepare exact development operations gateway source")
    stale_setting_cleanup = workflow.index(
        "--setting-names AzureWebJobsStorage DEPLOYMENT_STORAGE_CONNECTION_STRING"
    )
    publish_step = workflow.index("Publish exact development operations gateway source")
    verify_step = workflow.index("Verify exact development operations gateway source")
    assert workflow.index("verify-deployment-plan.py", deploy_step) < publish_step
    assert deploy_step < stale_setting_cleanup < publish_step < verify_step
    assert workflow.index("az functionapp restart", stale_setting_cleanup) < publish_step
    assert "uses: Azure/functions-action@v1.5.6" in workflow[publish_step:verify_step]
    assert "remote-build: true" in workflow[publish_step:verify_step]
    assert "json.JSONDecoder().raw_decode" in workflow[verify_step:]
    assert 're.sub(r"(\\.\\d{6})\\d+"' in workflow[verify_step:]
    assert "Function triggers synchronization failed" in workflow[verify_step:]
    assert "/syncfunctiontriggers?api-version=2024-04-01" in workflow[verify_step:]
    assert 'if [ "$triggers_registered" != "true" ]' in workflow[verify_step:]
    assert (
        "inputs.apply && inputs.deploy_dev_operations_gateway" in workflow[deploy_step:publish_step]
    )


def test_repository_root_scripts_resolve_from_the_workspace() -> None:
    """The terraform job defaults to `infra`, so a bare root script path breaks.

    `bash scripts/...` inside that job resolves to `infra/scripts/...` and exits
    127 at deploy time, after the runner has already started. A step that
    invokes a repository-root script MUST either reach it with `../scripts/` or
    override the working directory.
    """
    workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["terraform"]
    assert job["defaults"]["run"]["working-directory"] == "infra"

    bare_reference = re.compile(r"(?<!\.\./)(?<![\w./$-])scripts/")
    offenders = [
        step.get("name")
        for step in job["steps"]
        if "working-directory" not in step and bare_reference.search(str(step.get("run", "")))
    ]

    assert offenders == [], (
        f"steps invoke a repository-root script from the infra directory: {offenders}"
    )


def test_runner_live_preflight_workflow_is_structurally_executable() -> None:
    workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["terraform"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Validate remote plan request") < names.index("Terraform init")
    assert names.index("Terraform plan") < names.index("Run complete Azure live preflight")
    assert names.index("Run complete Azure live preflight") < names.index(
        "Store protected plan artifact"
    )
    step = next(item for item in steps if item.get("name") == "Run complete Azure live preflight")
    request_step = next(
        item for item in steps if item.get("name") == "Validate remote plan request"
    )
    assert "DEPLOY_PREFLIGHT_INPUT_JSON is required for protected plans" in request_step["run"]
    script = step["run"]
    assert "Azure live preflight sanitized report" in script
    assert "Azure live preflight incomplete" in script
    subprocess.run(  # noqa: S603 - static repository-owned script
        ["/usr/bin/bash", "-n"],
        input=script,
        text=True,
        check=True,
    )
    marker = "python3 - <<'PY'\n"
    sections = script.split(marker)
    assert len(sections) == 3
    for index, section in enumerate(sections[1:], start=1):
        source, separator, _remaining = section.partition("\nPY\n")
        assert separator, index
        compile(source, f"<runner-preflight-{index}>", "exec")

    destructive_step = next(
        item for item in steps if item.get("name") == "Reject destructive protected plan"
    )
    assert names.index("Terraform plan") < names.index("Reject destructive protected plan")
    assert names.index("Reject destructive protected plan") < names.index(
        "Run complete Azure live preflight"
    )
    subprocess.run(  # noqa: S603 - static repository-owned script
        ["/usr/bin/bash", "-n"],
        input=destructive_step["run"],
        text=True,
        check=True,
    )
    destructive_source = destructive_step["run"].split(marker, maxsplit=1)[1].partition("\nPY\n")[0]
    compile(destructive_source, "<protected-plan-delete-gate>", "exec")


@pytest.mark.parametrize(
    ("resource_changes", "expected_exit"),
    (
        (
            [
                {
                    "address": (
                        "module.state_store.azurerm_postgresql_flexible_server_firewall_rule."
                        "allow_azure_services[0]"
                    ),
                    "change": {"actions": ["delete"]},
                }
            ],
            0,
        ),
        (
            [
                {
                    "address": "module.compute.azurerm_container_app.core",
                    "change": {"actions": ["delete"]},
                }
            ],
            1,
        ),
        (
            [
                {
                    "address": (
                        "module.state_store.azurerm_postgresql_flexible_server_firewall_rule."
                        "allow_azure_services[0]"
                    ),
                    "change": {"actions": ["delete", "create"]},
                }
            ],
            1,
        ),
        (
            [
                {
                    "address": "azurerm_role_assignment.ingestion_eventhubs_receiver[0]",
                    "change": {"actions": ["delete"]},
                },
                {
                    "address": ("azurerm_role_assignment.ingestion_worker_pantheon_receiver[0]"),
                    "change": {"actions": ["create"]},
                },
            ],
            0,
        ),
        (
            [
                {
                    "address": "azurerm_role_assignment.ingestion_eventhubs_receiver[0]",
                    "change": {"actions": ["delete"]},
                }
            ],
            1,
        ),
        (
            [
                {
                    "address": ("azurerm_role_assignment.ingestion_worker_eventhubs_receiver[0]"),
                    "change": {"actions": ["delete"]},
                },
                {
                    "address": ("azurerm_role_assignment.ingestion_worker_pantheon_receiver[0]"),
                    "change": {"actions": ["create"]},
                },
            ],
            0,
        ),
        (
            [
                {
                    "address": ("azurerm_role_assignment.ingestion_worker_pantheon_receiver[0]"),
                    "change": {"actions": ["delete"]},
                },
                {
                    "address": "azurerm_role_assignment.ingestion_eventhubs_receiver[0]",
                    "change": {"actions": ["create"]},
                },
            ],
            0,
        ),
        (
            [
                {
                    "address": "azurerm_role_assignment.ingestion_kv_secrets_user[0]",
                    "change": {"actions": ["delete"]},
                },
                {
                    "address": "azurerm_role_assignment.ingestion_api_kv_secrets_user[0]",
                    "change": {"actions": ["create"]},
                },
            ],
            0,
        ),
        (
            [
                {
                    "address": (
                        "module.llm_azure_openai[0].azurerm_role_assignment."
                        'additional_openai_user["ingestion"]'
                    ),
                    "change": {"actions": ["delete"]},
                },
                {
                    "address": (
                        "module.llm_azure_openai[0].azurerm_role_assignment."
                        'additional_openai_user["ingestion_api"]'
                    ),
                    "change": {"actions": ["create"]},
                },
                {
                    "address": (
                        "module.llm_azure_openai[0].azurerm_role_assignment."
                        'additional_openai_user["ingestion_worker"]'
                    ),
                    "change": {"actions": ["create"]},
                },
            ],
            0,
        ),
    ),
)
def test_protected_plan_delete_gate_allows_only_bounded_security_retirement(
    tmp_path: Path,
    resource_changes: list[dict[str, object]],
    expected_exit: int,
) -> None:
    workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["terraform"]["steps"]
        if item.get("name") == "Reject destructive protected plan"
    )
    marker = "python3 - <<'PY'\n"
    source = step["run"].split(marker, maxsplit=1)[1].partition("\nPY\n")[0]
    plan = {"resource_changes": resource_changes}
    (tmp_path / "dev.plan.review.json").write_text(json.dumps(plan), encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - static repository-owned script
        [sys.executable, "-c", source],
        cwd=tmp_path,
        check=False,
    )

    assert completed.returncode == expected_exit


def test_gateway_source_workflow_steps_are_structurally_executable() -> None:
    workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["terraform"]["steps"]
    build_step = next(
        item
        for item in steps
        if item.get("name") == "Build development operations gateway source artifact"
    )
    prepare_step = next(
        item
        for item in steps
        if item.get("name") == "Prepare exact development operations gateway source"
    )
    publish_step = next(
        item
        for item in steps
        if item.get("name") == "Publish exact development operations gateway source"
    )
    verify_step = next(
        item
        for item in steps
        if item.get("name") == "Verify exact development operations gateway source"
    )

    for step in (build_step, prepare_step, verify_step):
        subprocess.run(  # noqa: S603 - static repository-owned script
            ["/usr/bin/bash", "-n"],
            input=step["run"],
            text=True,
            check=True,
        )
    marker = "python3 - <<'PY'\n"
    source, separator, _remaining = (
        build_step["run"].split(marker, maxsplit=1)[1].partition("\nPY\n")
    )
    assert separator
    compile(source, "<gateway-source-artifact>", "exec")
    assert publish_step["uses"] == "Azure/functions-action@v1.5.6"
    assert publish_step["with"]["remote-build"] is True

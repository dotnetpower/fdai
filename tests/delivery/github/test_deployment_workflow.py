"""GitHub Actions deployment workflow transport tests."""

from __future__ import annotations

import io
import json
import subprocess
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
        payload = request.read().decode("utf-8")
        assert str(_TENANT) not in payload
        assert str(_SUBSCRIPTION) not in payload
        assert "backend:dev" not in payload
        assert "runner:private" not in payload
        parsed = json.loads(payload)
        assert parsed["inputs"]["apply"] is False
        assert parsed["inputs"]["commit_sha"] == "b" * 40
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
    assert '"$PLAN_COMMIT_SHA" != "$GITHUB_SHA"' in workflow
    assert "--name deployment-plans" in workflow
    assert "sha256sum dev.plan" in workflow
    assert "check-runner-egress.py" in workflow
    assert "preflight_evidence_digest" in workflow
    assert "DEPLOY_PREFLIGHT_INPUT_JSON is required for protected plans" in workflow
    assert "runner preflight profile must require all Azure live categories" in workflow
    assert "Run complete Azure live preflight" in workflow
    assert "uv sync --locked" in workflow
    assert "fdaictl deploy preflight" in workflow
    assert "azure_preflight_evidence_digest" in workflow
    assert "azure-preflight-evidence.json" in workflow
    assert '"preflight_blocks": False' in workflow
    assert "preflight-evidence.json" in workflow
    assert "--overwrite false" in workflow
    assert '"expires_at": os.environ["EXPIRES_AT"]' in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "path: infra/plan-metadata.json" in workflow
    assert "path: infra/dev.plan" not in workflow
    assert "cleanup-deployment-plans.py" in workflow
    assert "--num-results 1001" in workflow
    assert '--container-name deployment-plans --name "$blob_name"' in workflow
    assert "Validate exact apply request" in workflow
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
    assert "-detailed-exitcode" in workflow
    assert "Verify deployed health endpoints" in workflow
    assert "continue-on-error: true" not in workflow
    assert workflow.index("Verify deployed health endpoints") < workflow.index(
        "Record exact plan apply receipt"
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

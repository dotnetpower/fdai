"""Azure Managed Run Command VM task adapter tests."""

from __future__ import annotations

import httpx
import pytest
from fdai.delivery.azure.vm_task import AzureVmTaskRunner, AzureVmTaskRunnerConfig
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskRequest,
    VmTaskRunnerError,
    VmTaskStatus,
    VmTaskTarget,
)

_AUDIENCE = "https://management.azure.com/.default"
_TOKEN = "test-token"  # noqa: S105 - deterministic fake
_VM = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
    "rg-example/providers/Microsoft.Compute/virtualMachines/gpu-worker"
)


def _request(*, dry_run: bool = False) -> VmTaskRequest:
    task = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(
            PythonTaskFile(
                path="main.py",
                content="import torch\nprint(torch.cuda.is_available())\n",
            ),
            PythonTaskFile(path="config/default.json", content='{"batch":4}\n'),
        ),
        required_modules=("torch",),
        capabilities=frozenset({PythonTaskCapability.GPU}),
        timeout_seconds=300,
    )
    return VmTaskRequest(
        idempotency_key="event-1:gpu-health",
        task=task,
        target=VmTaskTarget(
            resource_ref="resource:compute/vm/gpu-worker",
            provider_ref=_VM,
            capabilities=frozenset({PythonTaskCapability.GPU}),
            location="koreacentral",
        ),
        inputs={"model": "example/model"},
        dry_run=dry_run,
    )


def _adapter(client: httpx.AsyncClient) -> AzureVmTaskRunner:
    return AzureVmTaskRunner(
        identity=StaticWorkloadIdentity(
            audience=_AUDIENCE,
            token=_TOKEN,
        ),
        http_client=client,
        config=AzureVmTaskRunnerConfig(endpoint="https://mock-arm.local"),
    )


async def test_dry_run_sends_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _adapter(client).run(_request(dry_run=True))

    assert receipt.status is VmTaskStatus.PLANNED
    assert calls == []


async def test_submit_checks_idempotency_then_creates_hash_verified_command() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"error": {"code": "NotFound"}})
        return httpx.Response(201, json={"properties": {"provisioningState": "Creating"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _adapter(client).run(_request())

    assert receipt.status is VmTaskStatus.SUBMITTED
    assert [request.method for request in calls] == ["GET", "PUT"]
    put = calls[1]
    assert put.headers["Authorization"] == f"Bearer {_TOKEN}"
    assert put.url.params["api-version"] == "2024-07-01"
    body = __import__("json").loads(put.content)
    assert body["properties"]["runAsUser"] == "root"
    script = body["properties"]["source"]["script"]
    assert script.count("sha256sum -c") == 4
    assert script.rfind("sha256sum -c") > script.index('test "$(cat "$task_dir/.fdai-artifact")"')
    assert "nvidia-smi -L" in script
    assert "/usr/local/bin/fdai-task-launch" in script
    assert "/.runs/" in script
    assert "fdai-task" in script
    assert "import torch" not in script


async def test_existing_command_is_returned_without_rerun() -> None:
    request = _request()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tags": {"fdai-artifact-sha256": request.task.artifact_hash},
                "properties": {
                    "instanceView": {
                        "executionState": "Succeeded",
                        "exitCode": 0,
                        "output": "ok",
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _adapter(client).run(request)

    assert receipt.status is VmTaskStatus.SUCCEEDED
    assert receipt.already_existed is True
    assert receipt.stdout_tail == "ok"


async def test_status_and_cancel_validate_run_ref_and_delete_resource() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={"properties": {"instanceView": {"executionState": "Running"}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = _adapter(client)
        submitted = await adapter.run(_request())
        status = await adapter.status(submitted.run_ref)
        cancelled = await adapter.cancel(submitted.run_ref)

    assert status.status is VmTaskStatus.RUNNING
    assert cancelled.status is VmTaskStatus.CANCELLED
    assert "DELETE" in methods
    with pytest.raises(VmTaskRunnerError, match="host does not match"):
        await adapter.status("https://example.com/subscriptions/x/runCommands/bad")

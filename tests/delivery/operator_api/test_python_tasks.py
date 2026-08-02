"""Governed Python task authoring and run-request routes."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.python_tasks import (
    PythonTaskRoutesConfig,
    PythonTaskRunSubmitter,
)
from fdai.shared.contracts.models import (
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.testing import InMemoryEventBus
from fdai.shared.providers.testing.python_task_author import TemplatePythonTaskAuthor
from fdai.shared.providers.testing.vm_task import (
    InMemoryPythonTaskArtifactStore,
    InMemoryVmTaskRunner,
    InMemoryVmTaskTargetResolver,
)
from fdai.shared.providers.vm_task import PythonTaskCapability, VmTaskTarget


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_OPERATOR_API_DEV_MODE", "1")


def _task() -> dict:
    return {
        "task_id": "gpu.health-check",
        "version": "1.0.0",
        "entrypoint": "main.py",
        "files": [
            {
                "path": "main.py",
                "content": "import torch\nprint(torch.cuda.is_available())\n",
            }
        ],
        "required_modules": ["torch"],
        "capabilities": ["gpu"],
        "timeout_seconds": 300,
    }


def _client() -> tuple[TestClient, InMemoryEventBus]:
    bus = InMemoryEventBus()
    group_mapping = GroupMapping(
        reader_group_id="readers",
        contributor_group_id="contributors",
        approver_group_id="approvers",
        owner_group_id="owners",
        break_glass_group_id="break-glass",
    )
    auth = build_authenticator(
        verifier=lambda token: {"oid": "operator"},
        resolver=RoleResolver(group_mapping=group_mapping),
    )
    artifacts = InMemoryPythonTaskArtifactStore()
    workflow = Workflow(
        schema_version="1.0.0",
        name="scheduled-gpu-python-task",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SCHEDULE, schedule="0 2 * * *"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=30,
            min_accuracy=0.99,
            max_policy_escapes=0,
        ),
        steps=[WorkflowStep(id="run", action_type_ref="tool.run-python-on-vm")],
    )
    targets = InMemoryVmTaskTargetResolver(
        (
            VmTaskTarget(
                resource_ref="resource:compute/vm/gpu-worker",
                capabilities=frozenset({PythonTaskCapability.GPU}),
            ),
        )
    )
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(
            dev_mode=True,
            python_tasks=PythonTaskRoutesConfig(
                artifacts=artifacts,
                targets=targets,
                runner=InMemoryVmTaskRunner(),
                submitter=PythonTaskRunSubmitter(event_bus=bus, topic="aw.events"),
                schedule_store=InMemoryScheduleStore(),
                workflows=(workflow,),
                author=TemplatePythonTaskAuthor(),
            ),
        ),
    )
    return TestClient(app), bus


def test_validate_stage_and_shadow_test() -> None:
    client, _ = _client()

    validation = client.post("/python-tasks/validate", json=_task())
    staged = client.post("/python-tasks/stage", json=_task())
    planned = client.post(
        "/python-tasks/test",
        json={"task": _task(), "target_resource_ref": "resource:compute/vm/gpu-worker"},
    )

    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert staged.status_code == 200
    assert staged.json()["artifact_ref"].startswith("python-task:gpu.health-check@")
    assert planned.status_code == 200
    assert planned.json()["plan"]["status"] == "planned"
    assert planned.json()["plan"]["files_would_copy"] == 1


def test_capabilities_report_wired_operations() -> None:
    client, _ = _client()

    response = client.get("/python-tasks/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "operations": {
            "generate": True,
            "validate": True,
            "stage": True,
            "test": True,
            "request_run": True,
            "schedule": True,
        },
    }


def test_author_generates_editable_validated_draft() -> None:
    client, _ = _client()

    response = client.post(
        "/python-tasks/generate",
        json={
            "intent": "Write a Python task that reports CUDA availability.",
            "task_id_hint": "gpu.generated-health",
            "target_resource_ref": "resource:compute/vm/gpu-worker",
            "allowed_modules": ["torch"],
        },
    )

    assert response.status_code == 200
    assert response.json()["validation"]["valid"] is True
    assert response.json()["task"]["task_id"] == "gpu.generated-health"
    assert "torch.cuda" in response.json()["task"]["files"][0]["content"]


async def test_request_run_publishes_reference_only_proposal() -> None:
    client, bus = _client()
    staged = client.post("/python-tasks/stage", json=_task()).json()

    response = client.post(
        "/python-tasks/request-run",
        json={
            "artifact_ref": staged["artifact_ref"],
            "target_resource_ref": "resource:compute/vm/gpu-worker",
            "reason": "Run the validated GPU health task.",
            "idempotency_key": "gpu-health-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["submitted"] is True
    published = [event async for event in bus.subscribe("aw.events", "test-observer")]
    assert published[0].payload["action_type"] == "tool.run-python-on-vm"
    assert "content" not in str(published[0].payload)


def test_invalid_source_cannot_stage_or_test() -> None:
    client, _ = _client()
    task = _task()
    task["files"][0]["content"] = "exec('print(1)')\n"

    staged = client.post("/python-tasks/stage", json=task)

    assert staged.status_code == 422
    assert staged.json()["valid"] is False
    assert staged.json()["issues"][0]["code"] == "dynamic_code"


def test_process_task_cannot_validate_stage_or_plan() -> None:
    client, _ = _client()
    task = _task()
    task["files"][0]["content"] = (
        "import subprocess\nsubprocess.run(['az', 'account', 'show'], check=True)\n"
    )
    task["required_modules"] = []
    task["capabilities"] = ["process"]

    validation = client.post("/python-tasks/validate", json=task)
    staged = client.post("/python-tasks/stage", json=task)
    planned = client.post(
        "/python-tasks/test",
        json={"task": task, "target_resource_ref": "resource:compute/vm/gpu-worker"},
    )

    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert staged.status_code == 422
    assert planned.status_code == 422
    assert "process_capability_forbidden" in {issue["code"] for issue in staged.json()["issues"]}


def test_staged_task_can_bind_to_custom_cron_schedule() -> None:
    client, _ = _client()
    artifact_ref = client.post("/python-tasks/stage", json=_task()).json()["artifact_ref"]

    response = client.post(
        "/python-tasks/schedule",
        json={
            "artifact_ref": artifact_ref,
            "target_resource_ref": "resource:compute/vm/gpu-worker",
            "workflow_ref": "scheduled-gpu-python-task",
            "cron_expression": "30 4 * * 1-5",
        },
    )

    assert response.status_code == 201
    assert response.json()["scheduled"] is True
    assert response.json()["cron_expression"] == "30 4 * * 1-5"

"""Authoritative operator proposal routing into the VM task executor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import ResourceLockManager
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.tool_call import ToolCallShadowExecutor
from fdai.core.hil_resume import HilResumeCoordinator, ResolveOutcome
from fdai.core.risk_gate.gate import (
    ActionPromotionRegistry,
    PromotionMetrics,
    RiskGate,
)
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.vm_task import VmPythonToolExecutor
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.stage_publisher import RecordingStagePublisher
from fdai.shared.providers.testing.vm_task import (
    InMemoryPythonTaskArtifactStore,
    InMemoryVmTaskRunner,
    InMemoryVmTaskTargetResolver,
)
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
    VmTaskTarget,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RISK_TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


async def test_raw_proposal_reaches_vm_runner_after_owner_approval() -> None:
    action_type = next(
        item
        for item in load_action_type_catalog(
            ACTION_TYPES_ROOT,
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == "tool.run-python-on-vm"
    )
    promotion = ActionPromotionRegistry(allow_legacy_metrics=True)
    promotion.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=14,
            samples=30,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )

    task = PythonTaskSpec(
        task_id="gpu.health-check",
        version="1.0.0",
        entrypoint="main.py",
        files=(PythonTaskFile(path="main.py", content="print('ok')\n"),),
        capabilities=frozenset({PythonTaskCapability.GPU}),
    )
    artifacts = InMemoryPythonTaskArtifactStore()
    await artifacts.put(task, created_by="operator-1")
    target_ref = "resource:compute/vm/gpu-worker"
    targets = InMemoryVmTaskTargetResolver(
        (
            VmTaskTarget(
                resource_ref=target_ref,
                capabilities=frozenset({PythonTaskCapability.GPU}),
            ),
        )
    )
    runner = InMemoryVmTaskRunner()
    state = InMemoryStateStore()
    tool_executor = ToolCallShadowExecutor(
        executor=VmPythonToolExecutor(
            artifacts=artifacts,
            targets=targets,
            runner=runner,
        ),
        audit_store=state,
        resource_lock=ResourceLockManager(),
        enforce=True,
    )
    channel = InMemoryHilChannel()
    stages = RecordingStagePublisher()
    pr_executor = MagicMock()
    coordinator = HilResumeCoordinator(
        state_store=state,
        executor=pr_executor,
        hil_channel=channel,
        rules_by_id={},
        tool_executor=tool_executor,
        action_types_by_name={action_type.name: action_type},
    )
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )

    async def inventory_context(_resource_ref: str):  # type: ignore[no-untyped-def]
        return {
            "resource_id": target_ref,
            "resource_type": "compute.vm",
            "props": {"tags": {"environment": "dev"}},
        }

    async def inventory_age(_resource_ref: str) -> int:
        return 0

    loop = ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=ActionBuilder(action_types_by_name={action_type.name: action_type}),
        executor=pr_executor,
        audit_store=state,
        rules_by_id={},
        risk_table=load_risk_table(RISK_TABLE_PATH),
        action_types_by_name={action_type.name: action_type},
        risk_gate=RiskGate(registry=promotion),
        tool_executor=tool_executor,
        hil_resume_coordinator=coordinator,
        inventory_age_provider=inventory_age,
        inventory_context_provider=inventory_context,
        stage_publisher=stages,
    )
    proposal = {
        "idempotency_key": "operator-1::run-1",
        "correlation_id": "vm-task-example",
        "initiator_principal": "operator-1",
        "operator_initiated": True,
        "action_type": action_type.name,
        "resource_id": target_ref,
        "event_type": "operator_request",
        "params": {
            "artifact_ref": task.artifact_ref,
            "target_resource_ref": target_ref,
            "reason": "Run the governed GPU health check.",
        },
    }

    result = await loop.process(proposal)

    assert result.outcome is ControlLoopOutcome.HIL
    assert stages.events[-1].stage.value == "audit"
    assert stages.events[-1].detail["outcome"] == ControlLoopOutcome.HIL.value
    assert len(channel.sent) == 1
    approval_id = channel.sent[0].approval_id
    parked = await state.read_state(f"hil_park:{approval_id}")
    assert parked is not None
    assert parked["submitter_oid"] == "operator-1"
    assert parked["action"]["mode"] == Mode.ENFORCE.value

    resolved = await coordinator.resolve(
        approval_id=approval_id,
        decision=HilDecision.APPROVE,
        approver_oid="owner-approver",
    )

    assert resolved.outcome is ResolveOutcome.EXECUTED
    assert len(runner.requests) == 1
    vm_request = runner.requests[0]
    assert vm_request.task.artifact_ref == task.artifact_ref
    assert vm_request.target.resource_ref == target_ref
    assert vm_request.dry_run is False

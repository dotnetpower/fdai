"""Local authoritative consumer for operator ActionProposal demos."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdai.core.control_loop import ControlLoop, ControlLoopResult
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.tool_call import ToolCallShadowExecutor
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.risk_gate.gate import (
    ActionPromotionRegistry,
    PromotionMetrics,
    RiskGate,
)
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.trust_router import TrustRouter
from fdai.delivery.vm_task import VmPythonToolExecutor
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import StagePublisher
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.vm_task import (
    PythonTaskArtifactStore,
    VmTaskRunner,
    VmTaskTargetResolver,
)

_ACTION_TYPE = "tool.run-python-on-vm"
_GROUP_ID = "fdai-dev-control-loop"


@dataclass(slots=True)
class LocalOperatorRuntime:
    """Run one authoritative ControlLoop consumer over a local EventBus."""

    bus: EventBus
    topic: str
    control_loop: ControlLoop
    coordinator: HilResumeCoordinator
    hil_channel: InMemoryHilChannel
    state_store: InMemoryStateStore
    results: list[ControlLoopResult] = field(default_factory=list)
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _result_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._consume(), name="local-operator-control-loop")
        await asyncio.sleep(0)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def wait_for_result(self, *, timeout_seconds: float = 2.0) -> ControlLoopResult:
        await asyncio.wait_for(self._result_event.wait(), timeout=timeout_seconds)
        return self.results[-1]

    async def _consume(self) -> None:
        async for envelope in self.bus.subscribe(self.topic, _GROUP_ID):
            try:
                result = await self.control_loop.process(envelope.payload)
            except Exception as exc:  # noqa: BLE001 - preserve the local consumer
                await self.bus.dead_letter(
                    self.topic,
                    envelope.key,
                    envelope.payload,
                    f"{type(exc).__name__}:{exc}",
                )
                continue
            self.results.append(result)
            self._result_event.set()


def build_local_operator_runtime(
    *,
    bus: EventBus,
    topic: str,
    repo_root: Path,
    action_types: Sequence[OntologyActionType],
    artifacts: PythonTaskArtifactStore,
    targets: VmTaskTargetResolver,
    runner: VmTaskRunner,
    stage_publisher: StagePublisher,
) -> LocalOperatorRuntime | None:
    """Compose the real operator authority with local in-memory delivery."""
    action_type = next((item for item in action_types if item.name == _ACTION_TYPE), None)
    if action_type is None:
        return None
    action_types_by_name = {item.name: item for item in action_types}
    promotion = ActionPromotionRegistry()
    gate = action_type.promotion_gate
    promotion.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=gate.min_shadow_days,
            samples=gate.min_samples,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    state_store = InMemoryStateStore()
    tool_executor = ToolCallShadowExecutor(
        executor=VmPythonToolExecutor(
            artifacts=artifacts,
            targets=targets,
            runner=runner,
        ),
        audit_store=state_store,
        resource_lock=ResourceLockManager(),
        enforce=True,
    )
    pr_executor = ShadowExecutor(
        publisher=RecordingRemediationPrPublisher(),
        audit_store=state_store,
        renderer=TemplateRenderer(remediation_root=repo_root / "rule-catalog" / "remediation"),
        resource_lock=ResourceLockManager(),
    )
    hil_channel = InMemoryHilChannel()
    coordinator = HilResumeCoordinator(
        state_store=state_store,
        executor=pr_executor,
        hil_channel=hil_channel,
        rules_by_id={},
        tool_executor=tool_executor,
        action_types_by_name=action_types_by_name,
    )
    index = RuleIndex.build(())
    schema_registry = PackageResourceSchemaRegistry()

    async def inventory_context(resource_ref: str) -> Mapping[str, Any]:
        return {
            "resource_id": resource_ref,
            "resource_type": "compute.vm",
            "props": {"tags": {"environment": "dev"}},
        }

    async def inventory_age(_resource_ref: str) -> int:
        return 0

    control_loop = ControlLoop(
        event_ingest=EventIngest(
            validator=JsonSchemaEventValidator(JsonSchemaContractValidator(schema_registry))
        ),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name=action_types_by_name),
        executor=pr_executor,
        audit_store=state_store,
        rules_by_id={},
        risk_table=load_risk_table(repo_root / "rule-catalog" / "risk-classification.yaml"),
        action_types_by_name=action_types_by_name,
        risk_gate=RiskGate(registry=promotion),
        tool_executor=tool_executor,
        hil_resume_coordinator=coordinator,
        inventory_age_provider=inventory_age,
        inventory_context_provider=inventory_context,
        stage_publisher=stage_publisher,
    )
    return LocalOperatorRuntime(
        bus=bus,
        topic=topic,
        control_loop=control_loop,
        coordinator=coordinator,
        hil_channel=hil_channel,
        state_store=state_store,
    )


__all__ = ["LocalOperatorRuntime", "build_local_operator_runtime"]

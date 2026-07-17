"""Safety-critical control-loop composition.

The public :class:`ControlLoop` owns injected pipeline state while focused
mixins implement RCA, fallback, execution-authority, and boundary stages.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import timedelta
from typing import Any

from fdai.core.control_loop._boundary import ControlLoopBoundaryMixin
from fdai.core.control_loop._execution import ControlLoopExecutionMixin
from fdai.core.control_loop._fallback import ControlLoopFallbackMixin
from fdai.core.control_loop._process import process_event
from fdai.core.control_loop._rca import ControlLoopRcaMixin
from fdai.core.control_loop.models import ControlLoopResult
from fdai.core.event_ingest import EventCorrelator, EventIngest
from fdai.core.executor import ShadowExecutor
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.direct_api import DirectApiShadowExecutor
from fdai.core.executor.tool_call import ToolCallShadowExecutor
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.router import NotificationRouter
from fdai.core.rca import IncidentMemberSource, RcaCoordinator
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t1_lightweight.tier import T1Tier
from fdai.core.tiers.t2_reasoning import T2Tier
from fdai.core.trust_router import TrustRouter
from fdai.core.verticals.change_safety.detector import ChangeSafetyDetector
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.rule_catalog.schema.assignment import Assignment
from fdai.shared.contracts.models import Event, OntologyActionType, Rule
from fdai.shared.providers.cost_estimator import CostEstimator
from fdai.shared.providers.stage_publisher import NullStagePublisher, StagePublisher
from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience import DegradationController, KillSwitch

_LOGGER = logging.getLogger(__name__)


class ControlLoop(
    ControlLoopBoundaryMixin,
    ControlLoopRcaMixin,
    ControlLoopExecutionMixin,
    ControlLoopFallbackMixin,
):
    """One-call orchestrator for the P1 pipeline."""

    def __init__(
        self,
        *,
        event_ingest: EventIngest,
        trust_router: TrustRouter,
        t0_engine: T0Engine,
        action_builder: ActionBuilder,
        executor: ShadowExecutor,
        audit_store: StateStore,
        rules_by_id: Mapping[str, Rule],
        change_safety_detector: ChangeSafetyDetector | None = None,
        risk_table: RiskTable | None = None,
        action_types_by_name: Mapping[str, OntologyActionType] | None = None,
        risk_gate: RiskGate | None = None,
        cost_estimator: CostEstimator | None = None,
        direct_api_executor: DirectApiShadowExecutor | None = None,
        tool_executor: ToolCallShadowExecutor | None = None,
        t1_engine: T1Tier | None = None,
        t2_engine: T2Tier | None = None,
        stage_publisher: StagePublisher | None = None,
        notification_router: NotificationRouter | None = None,
        hil_resume_coordinator: HilResumeCoordinator | None = None,
        rca_coordinator: RcaCoordinator | None = None,
        event_correlator: EventCorrelator | None = None,
        incident_member_source: IncidentMemberSource | None = None,
        causal_chain_window: timedelta | None = None,
        resource_dependency_graph: Mapping[str, Iterable[str]] | None = None,
        workflow_coordinator: WorkflowTriggerCoordinator | None = None,
        degradation: DegradationController | None = None,
        kill_switch: KillSwitch | None = None,
        governance_assignments: Iterable[Assignment] = (),
        inventory_age_provider: Callable[[str], Awaitable[int | None]] | None = None,
        inventory_context_provider: (
            Callable[[str], Awaitable[Mapping[str, Any] | None]] | None
        ) = None,
        promotion_state_refresher: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._event_ingest = event_ingest
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._executor = executor
        self._audit_store = audit_store
        self._rules_by_id = dict(rules_by_id)
        self._change_safety_detector = change_safety_detector
        self._risk_table = risk_table
        self._action_types_by_name = (
            dict(action_types_by_name) if action_types_by_name is not None else {}
        )
        self._risk_gate = risk_gate
        self._degradation = degradation
        self._kill_switch = kill_switch
        self._governance_assignments = tuple(governance_assignments)
        self._inventory_age_provider = inventory_age_provider
        self._inventory_context_provider = inventory_context_provider
        self._promotion_state_refresher = promotion_state_refresher
        self._cost_estimator = cost_estimator
        self._direct_api_executor = direct_api_executor
        self._tool_executor = tool_executor
        self._t1_engine = t1_engine
        self._t2_engine = t2_engine
        self._stage_publisher: StagePublisher = stage_publisher or NullStagePublisher()
        self._notification_router = notification_router
        self._hil_resume_coordinator = hil_resume_coordinator
        self._rca_coordinator = rca_coordinator
        self._event_correlator = event_correlator
        self._incident_member_source = incident_member_source
        self._causal_chain_window = causal_chain_window or timedelta(minutes=15)
        self._resource_dependency_graph = (
            dict(resource_dependency_graph) if resource_dependency_graph is not None else None
        )
        self._workflow_coordinator = workflow_coordinator

    async def _maybe_fire_workflows(self, event: Event) -> None:
        """Fire matched shadow Workflows without changing the primary decision."""
        if self._workflow_coordinator is None:
            return
        try:
            await self._workflow_coordinator.on_event(event)
        except Exception as exc:  # noqa: BLE001 - side-consumer never breaks the loop
            _LOGGER.warning(
                "workflow_coordinator_failed",
                extra={"event_type": event.event_type, "error": type(exc).__name__},
            )

    async def process(self, raw_event: Event | Mapping[str, Any]) -> ControlLoopResult:
        """Process one raw or normalized event through the control loop."""
        return await process_event(self, raw_event)


__all__ = ["ControlLoop"]

"""Boundary adapters used by the control-loop orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai.core.control_loop._audit_helpers import (
    record_unhandled_failure as _record_unhandled_failure,
)
from fdai.core.control_loop._audit_helpers import (
    write_abstain_audit,
    write_governance_assignment_audit,
    write_t1_audit,
    write_t2_audit,
)
from fdai.core.control_loop._notification_helpers import (
    notify_decision,
    request_hil_approval,
)
from fdai.core.control_loop._stage_helpers import emit_stage
from fdai.core.control_loop.models import ControlLoopOutcome
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.router import NotificationRouter
from fdai.core.tiers.t1_lightweight.tier import T1Decision
from fdai.core.tiers.t2_reasoning import T2Decision
from fdai.core.trust_router import RoutingDecision
from fdai.rule_catalog.schema.assignment import AssignmentResolution
from fdai.shared.contracts.models import Action, Event, Rule
from fdai.shared.providers.stage_publisher import StageName, StagePhase, StagePublisher
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")

_HIL_SYSTEM_SUBMITTER = "system:control-loop"


class ControlLoopBoundaryMixin:
    """Adapt orchestration decisions to audit, notification, and stage seams."""

    _audit_store: StateStore
    _stage_publisher: StagePublisher
    _notification_router: NotificationRouter | None
    _hil_resume_coordinator: HilResumeCoordinator | None

    async def _write_governance_assignment_audit(
        self,
        *,
        event: Event,
        resource_id: str,
        resolution: AssignmentResolution,
    ) -> None:
        await write_governance_assignment_audit(
            self._audit_store,
            event=event,
            resource_id=resource_id,
            resolution=resolution,
        )

    async def _notify_decision(
        self,
        *,
        event: Event,
        correlation_id: str,
        overall: ControlLoopOutcome,
        decision_word: str,
        resource_type: str | None,
        citing_rule_ids: tuple[str, ...],
    ) -> None:
        """Push one outbound operational alert for a terminal decision."""
        await notify_decision(
            self._notification_router,
            _LOGGER,
            event=event,
            correlation_id=correlation_id,
            overall=overall,
            decision_word=decision_word,
            resource_type=resource_type,
            citing_rule_ids=citing_rule_ids,
        )

    async def _request_hil_approval(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str,
        submitter_oid: str = _HIL_SYSTEM_SUBMITTER,
    ) -> None:
        """Park a HIL-routed action and push an approval card."""
        await request_hil_approval(
            self._hil_resume_coordinator,
            _LOGGER,
            action=action,
            rule=rule,
            correlation_id=correlation_id,
            submitter_oid=submitter_oid,
        )

    async def _emit_stage(
        self,
        *,
        event_id: str,
        correlation_id: str,
        stage: StageName,
        phase: StagePhase,
        detail: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Construct and emit one stage event without raising."""
        await emit_stage(
            self._stage_publisher,
            event_id=event_id,
            correlation_id=correlation_id,
            stage=stage,
            phase=phase,
            detail=detail,
            error=error,
        )

    async def _write_abstain_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        reason: str,
        stage: str,
    ) -> None:
        await write_abstain_audit(
            self._audit_store,
            event=event,
            decision=decision,
            reason=reason,
            stage=stage,
        )

    async def record_unhandled_failure(
        self,
        *,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Record an unexpected process-boundary failure without raw payload data."""
        await _record_unhandled_failure(
            self._audit_store,
            payload=payload,
            reason=reason,
        )

    async def _write_t1_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t1: T1Decision,
    ) -> None:
        await write_t1_audit(
            self._audit_store,
            event=event,
            decision=decision,
            t1=t1,
        )

    async def _write_t2_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t2: T2Decision,
    ) -> None:
        await write_t2_audit(
            self._audit_store,
            event=event,
            decision=decision,
            t2=t2,
        )


__all__ = ["ControlLoopBoundaryMixin"]

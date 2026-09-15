"""Canonical Process creation and retained-lineage reads for alert workflows.

The coordinator inherits these helpers so its injected stores and overridable methods
remain on the same instance. No alternate Process state machine is introduced.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fdai_service_contracts.alert_noise_plan import AlertChangePlan

from fdai.core.detection.alert_noise.execution_models import AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow_binding import _AlertWorkflowBindingSupport
from fdai.core.detection.alert_noise.workflow_catalog import workflow_binding_key
from fdai.core.detection.alert_noise.workflow_decision_case import _proposal_payload
from fdai.core.detection.alert_noise.workflow_models import (
    AlertWorkflowBinding,
    AlertWorkflowResolution,
)
from fdai.core.workflow.workflow_resume import build_resume_payload, load_resume_envelope
from fdai.core.workflow.workflow_runtime import event_id
from fdai.shared.contracts.models import Workflow
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)


class _AlertWorkflowProcessSupport(_AlertWorkflowBindingSupport):
    """Preserve creation and proposal lineage through the canonical Process store."""

    _processes: ProcessRuntimeStore

    async def _create_process(
        self,
        binding: AlertWorkflowBinding,
        workflow: Workflow,
        plan: AlertChangePlan,
        now: datetime,
    ) -> None:
        snapshot, _ = await self._processes.create(
            snapshot=ProcessSnapshot(
                process_id=binding.process_id,
                workflow_ref=workflow.name,
                workflow_version=workflow.version,
                status=ProcessStatus.PENDING,
                current_step="",
                target_resource_id=binding.target_resource_id,
                started_at=now,
                updated_at=now,
                correlation_id=binding.correlation_id,
            ),
            event=ProcessEvent(
                event_id=event_id(binding.process_id, "created"),
                process_id=binding.process_id,
                kind=ProcessEventKind.PROCESS_CREATED,
                idempotency_key=f"{binding.process_id}:created",
                recorded_at=now,
                correlation_id=binding.correlation_id,
                payload=self._creation_payload(binding, workflow),
            ),
        )
        events = await self._processes.events(binding.process_id)
        created = self._check_creation(binding, workflow, snapshot, events)
        child_key = f"{binding.process_id}:alert-noise:proposal-ready"
        prior = tuple(item for item in events if item.idempotency_key == child_key)
        recorded_at = prior[0].recorded_at if prior else self._clock()
        if not created.recorded_at <= recorded_at <= self._clock():
            raise AlertExecutionHeld("workflow_proposal_time_mismatch")
        child = ProcessEvent(
            event_id=event_id(binding.process_id, "alert-noise:proposal-ready"),
            process_id=binding.process_id,
            kind=ProcessEventKind.PLANNING_PHASE_RECORDED,
            idempotency_key=child_key,
            recorded_at=recorded_at,
            correlation_id=binding.correlation_id,
            causation_id=created.event_id,
            payload=_proposal_payload(binding, plan),
        )
        if prior:
            if prior != (child,):
                raise AlertExecutionHeld("workflow_proposal_event_conflict")
        elif snapshot.status.terminal:
            raise AlertExecutionHeld("workflow_proposal_event_missing")
        else:
            await self._processes.append_event(child)

    def _creation_payload(
        self, binding: AlertWorkflowBinding, workflow: Workflow
    ) -> dict[str, object]:
        return {
            "workflow_ref": workflow.name,
            "workflow_version": workflow.version,
            "resume": build_resume_payload(
                workflow=workflow,
                action_types=self._action_types,
                trigger_ts=binding.trigger_ts,
                mode=binding.mode,
                context=binding.context,
            ),
        }

    def _check_creation(
        self,
        binding: AlertWorkflowBinding,
        workflow: Workflow,
        snapshot: ProcessSnapshot,
        events: tuple[ProcessEvent, ...],
    ) -> ProcessEvent:
        created = tuple(item for item in events if item.kind is ProcessEventKind.PROCESS_CREATED)
        if (
            len(created) != 1
            or not events
            or events[0] != created[0]
            or snapshot.process_id != binding.process_id
            or snapshot.target_resource_id != binding.target_resource_id
            or snapshot.correlation_id != binding.correlation_id
        ):
            raise AlertExecutionHeld("workflow_process_lineage_mismatch")
        first = created[0]
        if (
            first.event_id != event_id(binding.process_id, "created")
            or first.process_id != binding.process_id
            or first.attempt != 1
            or first.correlation_id != binding.correlation_id
            or first.idempotency_key != f"{binding.process_id}:created"
            or first.recorded_at != snapshot.started_at
            or first.step_id is not None
            or first.causation_id is not None
            or first.payload != self._creation_payload(binding, workflow)
        ):
            raise AlertExecutionHeld("workflow_creation_evidence_mismatch")
        load_resume_envelope(workflow=workflow, snapshot=snapshot, created_event=first)
        return first

    async def resolve(self, *, process_id: str) -> AlertWorkflowResolution:
        """Re-read exact private inputs and canonical lineage without advancing a Process.

        Historical evidence may be needed by separately authorized recovery. Callers of
        a forward path must additionally call ``require_current`` and check promotion.
        """
        async with asyncio.timeout(15):
            raw = await self._store.read_state(workflow_binding_key(process_id))
            if raw is None:
                raise AlertExecutionHeld("workflow_binding_not_retained")
            binding = self._decode(raw)
            plan, evidence, workflow, target, principal = await self._read_plan(binding.plan_digest)
            expected = self._binding(
                plan,
                workflow,
                target,
                principal,
                correlation_id=binding.correlation_id,
                mode=binding.mode,
            )
            if binding != expected or binding.process_id != process_id:
                raise AlertExecutionHeld("workflow_invocation_conflict")
            snapshot = await self._processes.get(process_id)
            if snapshot is None:
                raise AlertExecutionHeld("workflow_process_not_found")
            events = await self._processes.events(process_id)
            created = self._check_creation(binding, workflow, snapshot, events)
            proposals = tuple(
                item
                for item in events
                if item.idempotency_key == f"{process_id}:alert-noise:proposal-ready"
            )
            if (
                len(proposals) != 1
                or proposals[0].kind is not ProcessEventKind.PLANNING_PHASE_RECORDED
                or proposals[0].event_id != event_id(process_id, "alert-noise:proposal-ready")
                or proposals[0].process_id != process_id
                or proposals[0].correlation_id != binding.correlation_id
                or proposals[0].causation_id != created.event_id
                or not created.recorded_at <= proposals[0].recorded_at <= self._clock()
                or proposals[0].attempt != 1
                or proposals[0].step_id is not None
                or proposals[0].payload != _proposal_payload(binding, plan)
            ):
                raise AlertExecutionHeld("workflow_proposal_evidence_mismatch")
            return AlertWorkflowResolution(binding, plan, workflow, evidence, snapshot, events)

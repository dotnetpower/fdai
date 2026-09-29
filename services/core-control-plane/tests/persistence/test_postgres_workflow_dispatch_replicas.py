"""PostgreSQL multi-replica workflow dispatch idempotency tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.core.workflow.orchestrator import WorkflowOrchestrator, derive_process_id
from fdai.core.workflow.trigger_index import WorkflowTriggerIndex
from fdai.core.workflow.workflow_runtime import WorkflowVerifiedOutcome
from fdai.delivery.persistence import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingByTier,
    CeilingRole,
    Event,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[4]
_BUNDLE_DIGEST = "sha256:" + "c" * 64


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled test subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _action() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.replica-dispatch",
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        description="Test-only action.",
        ceiling_by_tier=CeilingByTier(
            t0=TierCeiling(
                max_autonomy=Autonomy.ENFORCE_AUTO,
                min_role=CeilingRole.CONTRIBUTOR,
            ),
        ),
    )


_ACTION_TYPES = {_action().name: _action()}


def _workflow(name: str) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="apply",
                action_type_ref="ops.replica-dispatch",
                params={"reason": "replica dispatch proof"},
            )
        ],
    )


def _planner() -> WorkflowApprovalPlanner:
    return WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=GroupMapping(
            reader_group_id="grp-readers",
            contributor_group_id="grp-contributors",
            approver_group_id="grp-approvers",
            owner_group_id="grp-owners",
            break_glass_group_id="grp-break-glass",
        ),
        matrix=load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": "a1_hil_approval",
                            "primary": "teams-hil-prd",
                            "fallback": ["slack-hil-prd"],
                        }
                    },
                }
            }
        ),
    )


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.proposals: list[str] = []

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        target_resource_id: str,
        params: Mapping[str, object],
        context: Mapping[str, str],
        attempt: int = 1,
    ) -> str:
        del correlation_id, target_resource_id, params, context
        proposal_ref = f"{process_id}:step:{step.id}:attempt:{attempt}"
        self.proposals.append(proposal_ref)
        return proposal_ref


class _SucceededVerifier:
    async def resolve(
        self,
        *,
        process_id: str,
        step_id: str,
        proposal_ref: str,
    ) -> WorkflowVerifiedOutcome | None:
        del process_id, step_id, proposal_ref
        return WorkflowVerifiedOutcome(
            outcome="succeeded",
            receipt_ref="receipt:workflow-replica-dispatch",
            safeguard_bundle_digest=_BUNDLE_DIGEST,
        )

    async def verify(
        self,
        *,
        process_id: str,
        step_id: str,
        proposal_ref: str,
        outcome: str,
        receipt_ref: str,
    ) -> bool:
        del process_id, step_id, proposal_ref, receipt_ref
        return outcome == "succeeded"


class _CancelAfterClaimStore:
    def __init__(self, inner: PostgresProcessRuntimeStore) -> None:
        self._inner = inner
        self.cancelled = False

    async def create(
        self,
        *,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> tuple[ProcessSnapshot, bool]:
        return await self._inner.create(snapshot=snapshot, event=event)

    async def transition(
        self,
        *,
        process_id: str,
        expected_revision: int,
        status: ProcessStatus,
        current_step: str,
        event: ProcessEvent,
    ) -> ProcessSnapshot:
        return await self._inner.transition(
            process_id=process_id,
            expected_revision=expected_revision,
            status=status,
            current_step=current_step,
            event=event,
        )

    async def get(self, process_id: str) -> ProcessSnapshot | None:
        return await self._inner.get(process_id)

    async def events(self, process_id: str) -> tuple[ProcessEvent, ...]:
        return await self._inner.events(process_id)

    async def append_event(self, event: ProcessEvent) -> bool:
        created = await self._inner.append_event(event)
        if created and event.kind is ProcessEventKind.ACTION_DISPATCH_CLAIMED:
            self.cancelled = True
            raise asyncio.CancelledError
        return created

    async def list(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[ProcessSnapshot, ...]:
        return await self._inner.list(workflow_ref=workflow_ref, status=status, limit=limit)


@dataclass(frozen=True, slots=True)
class _Replica:
    store: ProcessRuntimeStore
    dispatcher: _RecordingDispatcher
    orchestrator: WorkflowOrchestrator
    coordinator: WorkflowTriggerCoordinator


def _replica(
    dsn: str,
    workflow: Workflow,
    *,
    verifier: _SucceededVerifier | None = None,
    store: ProcessRuntimeStore | None = None,
) -> _Replica:
    process_store = store or PostgresProcessRuntimeStore(
        config=PostgresProcessRuntimeStoreConfig(dsn=dsn)
    )
    dispatcher = _RecordingDispatcher()
    orchestrator = WorkflowOrchestrator(
        planner=_planner(),
        action_types=_ACTION_TYPES,
        audit_store=InMemoryStateStore(),
        process_store=process_store,
        action_dispatcher=dispatcher,
        outcome_verifier=verifier,
        action_dispatch_claim_lease=timedelta(milliseconds=25),
    )
    coordinator = WorkflowTriggerCoordinator(
        index=WorkflowTriggerIndex.build([workflow]),
        orchestrator=orchestrator,
    )
    return _Replica(
        store=process_store,
        dispatcher=dispatcher,
        orchestrator=orchestrator,
        coordinator=coordinator,
    )


async def _run_from_event(replica: _Replica, workflow: Workflow, event: Event) -> None:
    await replica.coordinator.runtime.run(
        workflow,
        target_resource_id=event.resource_ref or "event:object.drift",
        trigger_ts=event.detected_at,
        context={"event.event_type": event.event_type},
        correlation_id=event.correlation_id or str(event.event_id),
        mode=Mode.ENFORCE,
    )


def _event(*, resource_ref: str, detected_at: datetime) -> Event:
    return Event(
        schema_version="1.0.0",
        event_id=uuid.uuid4(),
        idempotency_key=f"idem-{uuid.uuid4().hex}",
        source="test",
        event_type="object.drift",
        resource_ref=resource_ref,
        payload={},
        detected_at=detected_at,
        ingested_at=detected_at,
        mode=Mode.SHADOW,
    )


def _event_counts(events: tuple[ProcessEvent, ...]) -> dict[ProcessEventKind, int]:
    return {kind: sum(event.kind is kind for event in events) for kind in ProcessEventKind}


async def test_postgres_workflow_replicas_dispatch_once_per_step_attempt() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    workflow = _workflow(f"replica-dispatch-{uuid.uuid4().hex}")
    trigger_ts = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    event = _event(resource_ref=f"res-{uuid.uuid4().hex}", detected_at=trigger_ts)
    first = _replica(dsn, workflow)
    second = _replica(dsn, workflow)

    await asyncio.gather(
        _run_from_event(first, workflow, event),
        _run_from_event(second, workflow, event),
    )

    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id=event.resource_ref or "event:object.drift",
        trigger_ts=trigger_ts,
    )
    reader = PostgresProcessRuntimeStore(config=PostgresProcessRuntimeStoreConfig(dsn=dsn))
    events = await reader.events(process_id)
    counts = _event_counts(events)
    assert counts[ProcessEventKind.ACTION_DISPATCH_CLAIMED] == 1
    assert counts[ProcessEventKind.ACTION_DISPATCHED] == 1
    assert sum(len(replica.dispatcher.proposals) for replica in (first, second)) == 1
    assert counts[ProcessEventKind.PROCESS_COMPLETED] == 0

    completer = _replica(dsn, workflow, verifier=_SucceededVerifier())
    await _run_from_event(completer, workflow, event)
    completed = await reader.events(process_id)
    completed_counts = _event_counts(completed)
    assert completed_counts[ProcessEventKind.ACTION_DISPATCHED] == 1
    assert completed_counts[ProcessEventKind.STEP_COMPLETED] == 1
    assert completed_counts[ProcessEventKind.PROCESS_COMPLETED] == 1
    assert (
        sum(
            1
            for item in completed
            if item.attempt == 1
            and item.kind in {ProcessEventKind.PROCESS_COMPLETED, ProcessEventKind.PROCESS_FAILED}
        )
        == 1
    )


async def test_postgres_workflow_replica_claim_crash_redelivery_takes_over_once() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    workflow = _workflow(f"replica-claim-restart-{uuid.uuid4().hex}")
    trigger_ts = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)
    event = _event(resource_ref=f"res-{uuid.uuid4().hex}", detected_at=trigger_ts)
    crashing_store = _CancelAfterClaimStore(
        PostgresProcessRuntimeStore(config=PostgresProcessRuntimeStoreConfig(dsn=dsn))
    )
    crashing = _replica(dsn, workflow, store=crashing_store)

    with pytest.raises(asyncio.CancelledError):
        await _run_from_event(crashing, workflow, event)
    assert crashing_store.cancelled is True
    assert crashing.dispatcher.proposals == []
    await asyncio.sleep(0.05)

    restarted = _replica(dsn, workflow, verifier=_SucceededVerifier())
    await _run_from_event(restarted, workflow, event)
    await _run_from_event(restarted, workflow, event)

    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id=event.resource_ref or "event:object.drift",
        trigger_ts=trigger_ts,
    )
    reader = PostgresProcessRuntimeStore(config=PostgresProcessRuntimeStoreConfig(dsn=dsn))
    events = await reader.events(process_id)
    claims = [event for event in events if event.kind is ProcessEventKind.ACTION_DISPATCH_CLAIMED]
    dispatches = [event for event in events if event.kind is ProcessEventKind.ACTION_DISPATCHED]
    terminal = [event for event in events if event.kind is ProcessEventKind.PROCESS_COMPLETED]

    assert [claim.payload["generation"] for claim in claims] == [1, 2]
    assert len(dispatches) == 1
    assert dispatches[0].causation_id == claims[1].event_id
    assert len(restarted.dispatcher.proposals) == 1
    assert terminal and len(terminal) == 1
    assert (
        sum(
            1
            for item in events
            if item.attempt == 1
            and item.kind in {ProcessEventKind.PROCESS_COMPLETED, ProcessEventKind.PROCESS_FAILED}
        )
        == 1
    )

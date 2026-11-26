"""Full-migration safety lifecycle with a test-only PR sink; no real Azure or Git publication."""

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from fdai.agents import InMemoryBus, load_pantheon
from fdai.core.detection.alert_noise.outcomes import alert_effect_deadline
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.core.event_ingest import EventIngest
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguards import (
    SafeguardReceipt,
    evaluate_pre_dispatch,
    full_action_digest,
)
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.core.workflow.outcome_verification import StateStoreWorkflowOutcomeLedger
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.delivery.alert_noise_workflow import (
    StateStoreAlertActionBinder,
    StateStoreAlertWorkflowPromotionReader,
)
from fdai.delivery.persistence.postgres_audit_intent import (
    PostgresAuditIntentStore,
    PostgresAuditIntentStoreConfig,
)
from fdai.delivery.persistence.postgres_idempotency_reservation import (
    PostgresIdempotencyReservationStore,
    PostgresIdempotencyReservationStoreConfig,
)
from fdai.delivery.persistence.postgres_post_release_closure import (
    PostgresPostReleaseClosureStore,
    PostgresPostReleaseClosureStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_safeguard_dispatch import (
    PostgresSafeguardDispatchEvidenceStore,
    PostgresSafeguardDispatchEvidenceStoreConfig,
)
from fdai.delivery.persistence.postgres_target_dispatch_fence import (
    PostgresTargetDispatchFenceStore,
    PostgresTargetDispatchFenceStoreConfig,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.runtime.alert_noise_effects import bind_alert_effect_runtime
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import Action, ExecutionPath, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.core.detection.alert_noise import conftest as fixtures
from tests.core.detection.alert_noise import test_workflow as workflows
from tests.delivery.test_alert_noise_evidence import SOURCE
from tests.persistence.test_alert_noise_lifecycle_postgres import (
    _processes,
    _state,
)
from tests.persistence.test_alert_noise_lifecycle_postgres import (
    complete_database as complete_database,
)
from tests.runtime.test_alert_noise_effects_runtime import (
    _admit_workflow,
    _environment,
    _execute_publication,
    _independent,
    _signal,
)

pytestmark = pytest.mark.integration


class ObservedClock:
    """Follow real database I/O time; explicit later values model the effect deadline only."""

    def __init__(self, minimum):
        self.minimum = minimum

    def __getitem__(self, index):
        assert index == 0
        return max(self.minimum, datetime.now(UTC))

    def __setitem__(self, index, value):
        assert index == 0
        self.minimum = value


class RealtimeClock(ObservedClock):
    """Ignore unit-helper clock advances when another real PostgreSQL dispatch must follow."""

    def __setitem__(self, index, value):
        assert index == 0


async def real_observation(h, **changes):
    """Observe one actual second instead of mixing virtual future time with DB lock receipts."""
    await asyncio.sleep(1.1)
    at = datetime.now(UTC)
    await _independent(
        h,
        window_start=h.context.execution.source_event.terminal_at,
        window_end=at,
        recorded_at=at,
        **changes,
    )


@pytest.mark.parametrize(
    "effect",
    ["missing", "verified", "adverse", "recovered", "recovery-missing", "recovery-adverse"],
)
async def test_real_generation_closure_and_effect_survive_restart(
    complete_database, monkeypatch, effect
):
    db = complete_database
    # A postgres login followed by SET ROLE hides backend_start from that role;
    # it is not the direct service-login identity used for lock-session evidence.
    with psycopg.connect(db.core) as connection:
        assert connection.execute(
            "SELECT backend_start IS NULL FROM pg_stat_activity WHERE pid = pg_backend_pid()"
        ).fetchone() == (True,)
    # Only this disposable server gets a generated runtime-login credential. No grant
    # changes, pg_read_all_stats or superuser privilege is added to the service role.
    with psycopg.connect(db.admin, autocommit=True) as connection:
        connection.execute(
            sql.SQL("ALTER ROLE fdai_core LOGIN PASSWORD {}").format(
                sql.Literal(os.environ["PGPASSWORD"])
            )
        )
    db.core = make_conninfo(db.core, user="fdai_core", options="")
    with psycopg.connect(db.core) as connection:
        assert connection.execute(
            "SELECT backend_start IS NOT NULL FROM pg_stat_activity WHERE pid = pg_backend_pid()"
        ).fetchone() == (True,)
    at = datetime.now(UTC)
    monkeypatch.setattr(workflows, "InMemoryStateStore", lambda **kwargs: _state(db.core))
    monkeypatch.setattr(workflows, "InMemoryProcessRuntimeStore", lambda: _processes(db.core))
    h = await workflows.workflow_harness.__wrapped__(
        at, fixtures.evidence.__wrapped__(at), SimpleNamespace()
    )
    recovery_case = effect in {"recovered", "recovery-missing", "recovery-adverse"}
    h.plan = AlertChangePlan.model_validate(
        {**h.plan.model_dump(mode="python"), "max_observation_seconds": 1 if recovery_case else 60}
    )
    h.inputs["plan_digest"] = digest_record(h.plan)
    await h.store.write_state(
        "alert-noise:plan:" + digest_record(h.plan), h.plan.model_dump(mode="json")
    )
    h.admissions = StateStoreDecisionEvidenceAdmissionProvider(
        store=h.store, clock=lambda: h.clock[0]
    )
    h.promotions = StateStoreAlertWorkflowPromotionReader(
        store=h.store,
        admission_provider=h.admissions,
        source_revision=SOURCE,
        clock=lambda: h.clock[0],
    )

    class WorkflowClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return h.clock[0].astimezone(tz)

    for module in ("orchestrator", "workflow_step_executor", "compensation"):
        monkeypatch.setattr(f"fdai.core.workflow.{module}.datetime", WorkflowClock)
    h.orchestrator = WorkflowOrchestrator(
        planner=h.planner,
        action_types=h.actions,
        audit_store=h.store,
        process_store=h.processes,
        approval_provider=h.approvals,
        approval_decision_evidence_provider=h.admissions,
        outcome_verifier=StateStoreWorkflowOutcomeLedger(h.store, h.admissions, lambda: h.clock[0]),
        action_dispatcher=EventBusWorkflowActionDispatcher(h.bus, "test:operator-request"),
    )
    h.coordinator = AlertWorkflowCoordinator(
        **{
            **h.options,
            "orchestrator": h.orchestrator,
            "promotions": h.promotions,
            "clock": lambda: h.clock[0],
        }
    )
    action, event = await workflows._dispatched(h)
    binder = StateStoreAlertActionBinder(
        workflows=h.coordinator,
        registered_actions=h.registered,
        store=h.store,
        clock=lambda: h.clock[0],
    )
    bound = await binder.bind(action, event)
    # Approval fixtures and their coordinator share the frozen decision cutoff. Only
    # actual dispatch/recording and later observation follow elapsed database I/O.
    h.clock = RealtimeClock(at) if recovery_case else ObservedClock(at)
    h.action = Action.model_validate(
        {
            **bound.model_dump(mode="python"),
            "mode": Mode.ENFORCE,
            "executor_identity_ref": "executor:example",
        }
    )
    policy = EffectSinkContinuityPolicy.create(
        sink_id="test-only-alert-pr",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )
    h.dispatches = PostgresSafeguardDispatchEvidenceStore(
        config=PostgresSafeguardDispatchEvidenceStoreConfig(dsn=db.core)
    )
    h.closures = PostgresPostReleaseClosureStore(
        config=PostgresPostReleaseClosureStoreConfig(dsn=db.core)
    )
    h.executor = SafeguardLifecycleCoordinator(
        resource_lock=PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(dsn=db.core, continuity_policy=policy)
        ),
        reservation_store=PostgresIdempotencyReservationStore(
            config=PostgresIdempotencyReservationStoreConfig(dsn=db.core)
        ),
        audit_intent_store=PostgresAuditIntentStore(
            config=PostgresAuditIntentStoreConfig(dsn=db.core)
        ),
        fence_store=PostgresTargetDispatchFenceStore(
            config=PostgresTargetDispatchFenceStoreConfig(dsn=db.core)
        ),
        evidence_store=h.dispatches,
        closure_store=h.closures,
        denial_audit_store=h.store,
        commitment_store=ProcessRuntimeSafeguardCommitmentStore(h.processes),
        continuity_policy=policy,
        config=SafeguardLifecycleCoordinatorConfig(
            source_revision=SOURCE,
            producer_id="fdai.core.executor",
            producer_version="1.0.0",
            actor="Thor",
            expected_lock_verifier_id="postgres-pg-locks-readback",
            expected_lock_verifier_version="1.0.0",
            expected_lock_trust_anchor_id="postgres:primary",
        ),
        clock=lambda: datetime.now(UTC),
    )
    await _execute_publication(h)
    assert h.port.calls == 1 and h.context.execution.dispatch_generation == 1
    safety = evaluate_pre_dispatch(
        h.action,
        execution_path=ExecutionPath.PR_MANUAL,
        plan_digest=digest_record(h.plan),
        plan_kind="alert_noise_manual_pr",
    )
    assert isinstance(safety, SafeguardReceipt)
    duplicate = await h.executor.dispatch(
        action=h.action,
        safeguard_receipt=safety,
        dispatch_port=h.port,
        correlation_id=h.inputs["correlation_id"],
    )
    assert not duplicate.dispatch_performed and h.port.calls == 1
    h.pantheon = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    environment = {**_environment(), "FDAI_STATE_STORE_DSN": db.core}

    def restart():
        return bind_alert_effect_runtime(
            environment=environment,
            store=_state(db.core),
            processes=_processes(db.core),
            workflows=h.coordinator,
            admissions=h.admissions,
            publish=h.pantheon.publish,
            clock=lambda: h.clock[0],
        )

    h.runtime = restart()
    assert h.runtime is not None
    assert await h.runtime.tick() == 0
    if effect == "missing":
        h.clock[0] = alert_effect_deadline(h.context)
    elif recovery_case:
        await real_observation(h)
    else:
        # Independent receipt values are explicit test-only detector observations.
        await _independent(h, missed_incidents=1 if effect == "adverse" else 0)
    signal = await _signal(h)
    if recovery_case:
        await _admit_workflow(h, signal)
        forward_port = h.port
        cancelled = await h.orchestrator.cancel(
            process_id=signal["process_id"],
            workflows=h.workflows,
            actor_oid=str(UUID(int=1)),
            now=h.clock[0],
        )
        assert cancelled.status is ProcessStatus.COMPENSATING
        messages = [row async for row in h.bus.subscribe("test:operator-request", "test:binder")]
        assert len(messages) == 1
        validator = JsonSchemaEventValidator(
            JsonSchemaContractValidator(PackageResourceSchemaRegistry())
        )
        event = EventIngest(validator=validator).ingest(messages[0].payload)
        assert event is not None
        proposed, _ = h.builder.build_from_operator_request(event=event)
        bound = await binder.bind(proposed, event)
        h.action = Action.model_validate(
            {
                **bound.model_dump(mode="python"),
                "mode": Mode.ENFORCE,
                "executor_identity_ref": "executor:example",
            }
        )
        assert h.action.action_type == "ops.restore-alert-configuration"
        await _execute_publication(h)
        assert forward_port.calls == 1 and h.port.calls == 1
        h.runtime = restart()
        reader = h.runtime._readers[(h.plan.tenant_ref, h.plan.scope_ref)][1]
        assert await reader.read_context(action_digest=full_action_digest(h.action)) is not None
        assert await h.runtime.tick() == 0
        if effect == "recovery-missing":
            h.clock = ObservedClock(alert_effect_deadline(h.context))
        else:
            await real_observation(h, missed_incidents=1 if effect == "recovery-adverse" else 0)
        recovery = await _signal(h)
        if effect == "recovered":
            await _admit_workflow(h, recovery)
        result = await h.runtime.plan(recovery)
        replay = restart()
        if effect == "recovered":
            assert recovery["effect_outcome"] == "recovered"
            assert result.get("process_status") == "compensated", result
            assert (await replay.plan(recovery))["status"] == "already_terminal"
            assert (
                await _processes(db.core).get(recovery["process_id"])
            ).status is ProcessStatus.COMPENSATED
        else:
            assert result["recovery_required"]
            assert recovery["effect_outcome"] == "recovery_incomplete"
            for target in h.plan.lock_refs:
                assert await replay._holds.is_held(target_ref=target)
        assert not await _state(db.core).read_states(
            "workflow:automation-hold-release-intent:", limit=10
        )
        assert forward_port.calls == 1 and h.port.calls == 1
        return
    if effect == "verified":
        await _admit_workflow(h, signal)
    result = await h.runtime.plan(signal)
    restarted = restart()
    for target in h.plan.lock_refs:
        assert await restarted._holds.is_held(target_ref=target) is (effect != "verified")
    journal = await _state(db.core).read_state(signal["outcome_ref"])
    if effect == "missing":
        assert journal["evidence_status"] == "unknown" and journal["response_outcome"] is None
        assert journal["receipt_digest"] is None
    elif effect == "verified":
        assert journal["response_outcome"]["verification_status"] == "verified"
        assert result.get("process_status") == "succeeded", result
        assert (await restarted.plan(signal))["status"] == "already_terminal"
    else:
        assert result["recovery_required"]
        assert journal["response_outcome"]["verification_status"] == "mismatch"
    assert h.port.calls == 1

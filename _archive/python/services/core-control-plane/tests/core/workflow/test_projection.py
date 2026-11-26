"""Process runtime to ontology instance projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.workflow.projection import (
    ProcessOntologyProjector,
    ProcessProjectionWorker,
    ProjectingProcessRuntimeStore,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import (
    InMemoryOntologyInstanceStore,
    InMemoryProcessRuntimeStore,
)

_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _object_type(name: str, properties: dict[str, PropertyDecl]) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties=properties,
    )


def _ontology_store() -> InMemoryOntologyInstanceStore:
    common = {"id": PropertyDecl(type=PropertyType.STRING, required=True)}
    process = {
        **common,
        "workflow_ref": PropertyDecl(type=PropertyType.STRING, required=True),
        "workflow_version": PropertyDecl(type=PropertyType.STRING, required=True),
        "status": PropertyDecl(type=PropertyType.STRING, required=True),
        "current_step": PropertyDecl(type=PropertyType.STRING, required=True),
        "target_resource_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "started_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "updated_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "correlation_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "revision": PropertyDecl(type=PropertyType.INTEGER, required=True),
    }
    return InMemoryOntologyInstanceStore(
        object_types=(
            _object_type("Process", process),
            _object_type("Resource", common),
        ),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="targets",
                version="1.0.0",
                from_type="Process",
                to_type="Resource",
                cardinality=LinkCardinality.MANY_TO_ONE,
            ),
        ),
    )


def _snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id="process-1",
        workflow_ref="architecture-review",
        workflow_version="1.0.0",
        status=ProcessStatus.PENDING,
        current_step="",
        target_resource_id="resource-1",
        started_at=_NOW,
        updated_at=_NOW,
        correlation_id="corr-1",
    )


def _event() -> ProcessEvent:
    return ProcessEvent(
        event_id="event-1",
        process_id="process-1",
        kind=ProcessEventKind.PROCESS_CREATED,
        idempotency_key="process-1:create",
        recorded_at=_NOW,
        correlation_id="corr-1",
    )


async def test_projecting_store_materializes_process_and_target_link() -> None:
    ontology = _ontology_store()
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="resource-1",
            object_type="Resource",
            properties={"id": "resource-1"},
        )
    )
    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=ProcessOntologyProjector(ontology),
    )

    stored, created = await runtime.create(snapshot=_snapshot(), event=_event())
    graph = await ontology.traverse(root_ids=(stored.process_id,), max_depth=1)

    assert created is True
    process = await ontology.get_object("process-1")
    assert process is not None
    assert process.properties["workflow_ref"] == "architecture-review"
    assert {item.id for item in graph.objects} == {"process-1", "resource-1"}
    assert [link.link_type for link in graph.links] == ["targets"]


async def test_projection_is_refreshed_after_transition() -> None:
    ontology = _ontology_store()
    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=ProcessOntologyProjector(ontology),
    )
    stored, _ = await runtime.create(snapshot=_snapshot(), event=_event())
    await runtime.transition(
        process_id=stored.process_id,
        expected_revision=stored.revision,
        status=ProcessStatus.WAITING,
        current_step="collect-evidence",
        event=ProcessEvent(
            event_id="event-2",
            process_id="process-1",
            kind=ProcessEventKind.STEP_WAITING,
            idempotency_key="process-1:wait",
            recorded_at=_NOW,
            correlation_id="corr-1",
            step_id="collect-evidence",
        ),
    )
    process = await ontology.get_object("process-1")
    assert process is not None
    assert process.properties["status"] == "waiting"
    assert process.properties["current_step"] == "collect-evidence"


class _FlakyProjector:
    def __init__(self) -> None:
        self.fail = True
        self.calls: list[str] = []

    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None:
        assert event is not None
        self.calls.append(event.event_id)
        if self.fail:
            raise RuntimeError("projection unavailable")


async def test_projection_failure_is_retried_without_masking_runtime_commit() -> None:
    store = InMemoryProcessRuntimeStore()
    projector = _FlakyProjector()
    runtime = ProjectingProcessRuntimeStore(runtime=store, projector=projector)

    stored, created = await runtime.create(snapshot=_snapshot(), event=_event())

    assert created is True
    assert stored.revision == 1
    assert await store.get(stored.process_id) == stored
    worker = ProcessProjectionWorker(
        runtime=store,
        outbox=store,
        projector=projector,
        retry_delay_seconds=30,
        clock=lambda: _NOW,
    )
    first = await worker.run_once()
    assert first.claimed == 1
    assert first.deferred == 1

    projector.fail = False
    retry = ProcessProjectionWorker(
        runtime=store,
        outbox=store,
        projector=projector,
        clock=lambda: _NOW + timedelta(seconds=30),
    )
    second = await retry.run_once()
    drained = await retry.run_once()

    assert second.completed == 1
    assert drained.claimed == 0
    assert projector.calls == ["event-1", "event-1", "event-1"]


async def test_healthy_transition_drains_due_projection_backlog() -> None:
    store = InMemoryProcessRuntimeStore()
    projector = _FlakyProjector()
    runtime = ProjectingProcessRuntimeStore(
        runtime=store,
        projector=projector,
        retry_clock=lambda: _NOW + timedelta(seconds=31),
    )
    stored, _ = await runtime.create(snapshot=_snapshot(), event=_event())
    projector.fail = False

    await runtime.transition(
        process_id=stored.process_id,
        expected_revision=stored.revision,
        status=ProcessStatus.RUNNING,
        current_step="collect-evidence",
        event=ProcessEvent(
            event_id="event-2",
            process_id=stored.process_id,
            kind=ProcessEventKind.STEP_STARTED,
            idempotency_key="process-1:start",
            recorded_at=_NOW + timedelta(seconds=31),
            correlation_id=stored.correlation_id,
            step_id="collect-evidence",
        ),
    )

    assert projector.calls == ["event-1", "event-2", "event-1"]
    assert (await runtime.retry_pending()).claimed == 0


async def test_projector_links_workflow_definition_and_invokes_domain_projector() -> None:
    common = {"id": PropertyDecl(type=PropertyType.STRING, required=True)}
    process_props = {
        **common,
        "workflow_ref": PropertyDecl(type=PropertyType.STRING, required=True),
        "workflow_version": PropertyDecl(type=PropertyType.STRING, required=True),
        "status": PropertyDecl(type=PropertyType.STRING, required=True),
        "current_step": PropertyDecl(type=PropertyType.STRING, required=True),
        "target_resource_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "started_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "updated_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "correlation_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "revision": PropertyDecl(type=PropertyType.INTEGER, required=True),
    }
    wf_def_props = {
        **common,
        "workflow_name": PropertyDecl(type=PropertyType.STRING, required=True),
        "workflow_version": PropertyDecl(type=PropertyType.STRING, required=True),
    }
    ontology = InMemoryOntologyInstanceStore(
        object_types=(
            _object_type("Process", process_props),
            _object_type("Resource", common),
            _object_type("WorkflowDefinition", wf_def_props),
        ),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="targets",
                version="1.0.0",
                from_type="Process",
                to_type="Resource",
                cardinality=LinkCardinality.MANY_TO_ONE,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="instantiates_workflow",
                version="1.0.0",
                from_type="Process",
                to_type="WorkflowDefinition",
                cardinality=LinkCardinality.MANY_TO_ONE,
            ),
        ),
    )
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="wf-def-1",
            object_type="WorkflowDefinition",
            properties={
                "id": "wf-def-1",
                "workflow_name": "architecture-review",
                "workflow_version": "1.0.0",
            },
        )
    )
    domain_calls: list[str] = []

    class _DomainProjector:
        async def project(
            self,
            snapshot: ProcessSnapshot,
            *,
            event: ProcessEvent | None = None,
        ) -> None:
            domain_calls.append(snapshot.process_id)

    projector = ProcessOntologyProjector(
        ontology,
        domain_projectors={"architecture-review": _DomainProjector()},
    )
    await projector.project(_snapshot(), event=_event())
    graph = await ontology.traverse(root_ids=("process-1",), max_depth=1)
    assert [link.link_type for link in graph.links] == ["instantiates_workflow"]
    assert domain_calls == ["process-1"]


async def test_projecting_store_validation_and_delegated_methods() -> None:
    import pytest

    ontology = _ontology_store()
    projector = ProcessOntologyProjector(ontology)

    with pytest.raises(TypeError, match="ProcessProjectionOutbox"):
        ProjectingProcessRuntimeStore(runtime=object(), projector=projector)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retry_batch_size"):
        ProjectingProcessRuntimeStore(
            runtime=InMemoryProcessRuntimeStore(),
            projector=projector,
            retry_batch_size=0,
        )

    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=projector,
    )
    stored, _ = await runtime.create(snapshot=_snapshot(), event=_event())
    assert await runtime.get(stored.process_id) == stored
    assert len(await runtime.events(stored.process_id)) == 1
    assert len(await runtime.list(workflow_ref="architecture-review")) == 1

    step_event = ProcessEvent(
        event_id="event-append-1",
        process_id=stored.process_id,
        kind=ProcessEventKind.STEP_STARTED,
        idempotency_key="process-1:step-append",
        recorded_at=_NOW,
        correlation_id=stored.correlation_id,
        step_id="step-1",
    )
    assert await runtime.append_event(step_event) is True
    assert await runtime.append_event(step_event) is False


async def test_projection_worker_validation_missing_snapshot_and_retry_error() -> None:
    import pytest
    from fdai.shared.providers.process_projection import ProcessProjectionJob

    store = InMemoryProcessRuntimeStore()
    projector = _FlakyProjector()

    with pytest.raises(ValueError, match="batch_size"):
        ProcessProjectionWorker(runtime=store, outbox=store, projector=projector, batch_size=0)
    with pytest.raises(ValueError, match="lease_seconds"):
        ProcessProjectionWorker(runtime=store, outbox=store, projector=projector, lease_seconds=0)
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        ProcessProjectionWorker(
            runtime=store, outbox=store, projector=projector, retry_delay_seconds=0
        )

    class _StubOutbox:
        def __init__(self, jobs: tuple[ProcessProjectionJob, ...], fail_retry: bool) -> None:
            self.jobs = jobs
            self.fail_retry = fail_retry
            self.completed_ids: list[str] = []

        async def claim_projections(
            self, *, now: datetime, limit: int = 100, lease_seconds: int = 30
        ) -> tuple[ProcessProjectionJob, ...]:
            return self.jobs

        async def complete_projection(self, event_id: str) -> None:
            self.completed_ids.append(event_id)

        async def retry_projection(
            self, event_id: str, *, available_at: datetime, last_error: str
        ) -> None:
            if self.fail_retry:
                raise RuntimeError("outbox update failed")

    missing_job = ProcessProjectionJob(
        event=ProcessEvent(
            event_id="ev-missing",
            process_id="non-existent",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="non-existent:create",
            recorded_at=_NOW,
            correlation_id="corr-missing",
        ),
        attempts=1,
        available_at=_NOW,
    )
    outbox_missing = _StubOutbox((missing_job,), fail_retry=False)
    worker_missing = ProcessProjectionWorker(
        runtime=store,
        outbox=outbox_missing,
        projector=projector,
        clock=lambda: _NOW,
    )
    res_missing = await worker_missing.run_once()
    assert res_missing.completed == 1
    assert outbox_missing.completed_ids == ["ev-missing"]

    await store.create(snapshot=_snapshot(), event=_event())
    existing_job = ProcessProjectionJob(
        event=_event(),
        attempts=2,
        available_at=_NOW,
    )
    outbox_fail_retry = _StubOutbox((existing_job,), fail_retry=True)
    worker_fail_retry = ProcessProjectionWorker(
        runtime=store,
        outbox=outbox_fail_retry,
        projector=projector,
        clock=lambda: _NOW,
    )
    res_fail = await worker_fail_retry.run_once()
    assert res_fail.deferred == 1


async def test_recovery_coordinator_records_keys_identities_and_codecs() -> None:
    from dataclasses import replace

    from fdai.core.workflow.recovery_admission import (
        WorkflowRecoveryAdmissionAssessment,
        WorkflowRecoveryAdmissionRejectionReason,
    )
    from fdai.core.workflow.recovery_attempt import (
        RecoveryAttemptIdentity,
        RecoveryAttemptRejectionReason,
        RecoveryDispatchOutcome,
        RecoveryDispatchResult,
        RecoveryPreDispatchClaim,
        recovery_attempt_idempotency_key,
        recovery_attempt_step_id,
    )
    from fdai.core.workflow.recovery_coordinator_records import (
        active_hold_revision,
        admission_reason,
        approval_digest,
        approver_identity,
        attempt_from_record,
        attempt_key,
        aware_or_none,
        claim_from_mapping,
        claim_from_record,
        claim_key,
        claim_records,
        claim_to_record,
        dispatch_from_record,
        effect_key,
        int_or_none,
        lookup_from_record,
        lookup_key,
        observation_records,
        outbox_key,
        read_recovery_attempt,
        recovery_action_id,
        target_evidence_digest,
        terminal_reason,
    )
    from fdai.core.workflow.recovery_effect_claim import EffectCompletionClaim
    from fdai.core.workflow.recovery_terminalization import (
        ReleaseReceiptLookup,
        TerminalTransitionRejection,
    )
    from fdai.core.workflow.workflow_runtime import (
        WorkflowApprovalDecision,
        WorkflowApprovalSnapshot,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    digest = "sha256:" + "d" * 64
    target_ref = "resource:example/rg/rec-1"
    tdigest = target_evidence_digest(target_ref)
    attempt = RecoveryAttemptIdentity.create(
        process_id="proc-rec-1",
        failed_compensation_proposal_digest="sha256:" + "b" * 64,
        hold_revision=1,
        recovery_action_type="workflow.recovery.reconcile",
        recovery_payload_digest=digest,
        target_digest=tdigest,
        source_revision="commit:" + "a" * 40,
        attempt_number=1,
    )
    step_id = recovery_attempt_step_id(attempt)
    store = InMemoryStateStore(linearization_clock=lambda: _NOW)
    raw_attempt = {
        "process_id": attempt.process_id,
        "recovery_step_id": step_id,
        "attempt_identity_digest": attempt.identity_digest,
        "failed_compensation_proposal_digest": attempt.failed_compensation_proposal_digest,
        "hold_revision": attempt.hold_revision,
        "recovery_action_type": attempt.recovery_action_type,
        "recovery_payload_digest": attempt.recovery_payload_digest,
        "target_digest": attempt.target_digest,
        "source_revision": attempt.source_revision,
        "attempt_number": attempt.attempt_number,
        "execution_authority": False,
        "revision": 1,
    }
    await store.write_state(attempt_key(attempt), raw_attempt)
    assert (
        await read_recovery_attempt(store, process_id="proc-rec-1", recovery_step_id=step_id)
        == attempt
    )
    assert await read_recovery_attempt(store, process_id="other", recovery_step_id=step_id) is None
    assert (
        await read_recovery_attempt(store, process_id="proc-rec-1", recovery_step_id="missing")
        is None
    )

    empty_assess = object.__new__(WorkflowRecoveryAdmissionAssessment)
    object.__setattr__(empty_assess, "rejection_reasons", ())
    assert admission_reason(empty_assess) == RecoveryAttemptRejectionReason.APPROVAL_MISSING
    ranked_assess = WorkflowRecoveryAdmissionAssessment(
        eligible=False,
        evidence_digest=digest,
        scope_digest=digest,
        source_revision="commit:" + "a" * 40,
        rejection_reasons=(
            WorkflowRecoveryAdmissionRejectionReason.APPROVAL_REJECTED,
            WorkflowRecoveryAdmissionRejectionReason.QUORUM_NOT_MET,
        ),
    )
    assert admission_reason(ranked_assess) == "approval_rejected"

    eff_claim = EffectCompletionClaim.create_success(
        attempt_identity_digest=attempt.identity_digest,
        action_digest=digest,
        safeguard_bundle_digest=digest,
        provider_receipt_digest=digest,
        target_digest=attempt.target_digest,
        expected_effect_digest=digest,
        approved_envelope_digest=digest,
        source_revision="commit:" + "a" * 40,
        evidence_window_start=_NOW - timedelta(minutes=2),
        evidence_window_end=_NOW - timedelta(minutes=1),
        effect_evidence_digest=digest,
        validity_start=_NOW,
        validity_end=_NOW + timedelta(minutes=10),
        watermark_set_digest=digest,
        hold_revision=1,
        admission_digest=digest,
        generation=1,
    )
    assert claim_key(attempt, 1).endswith(":1")
    assert effect_key(attempt).startswith("workflow:recovery-effect:")
    assert lookup_key(attempt, eff_claim, 1).startswith("workflow:recovery-release-lookup:")
    assert outbox_key(digest, "process_event").endswith(":process_event")
    assert recovery_action_id(attempt).startswith("workflow-recovery:")

    snap_approved = WorkflowApprovalSnapshot(
        process_id="proc-rec-1",
        step_id=step_id,
        requester_principal="req@example.com",
        revision=1,
        requested_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
        decisions=(WorkflowApprovalDecision("Alice@Example.com", "approved", "r1"),),
    )
    snap_pending = replace(snap_approved, decisions=())
    assert approval_digest(snap_approved).startswith("sha256:")
    assert approver_identity(snap_approved) == "alice@example.com"
    assert approver_identity(snap_pending) == "req@example.com"

    assert active_hold_revision(None, process_id="proc-rec-1") is None
    assert (
        active_hold_revision(
            {"state": "active", "process_id": "other", "revision": 2},
            process_id="proc-rec-1",
        )
        is None
    )
    assert (
        active_hold_revision(
            {"state": "active", "process_id": "proc-rec-1", "revision": 2},
            process_id="proc-rec-1",
        )
        == 2
    )
    assert int_or_none(3) == 3
    assert int_or_none(True) is None
    assert aware_or_none(123) is None
    assert aware_or_none("bad") is None
    assert aware_or_none("2026-09-11T12:00:00") is None
    assert aware_or_none(_NOW.isoformat()) == _NOW

    assert attempt_from_record(raw_attempt) == attempt
    assert attempt_from_record({}) is None
    assert attempt_from_record({**raw_attempt, "attempt_identity_digest": digest}) is None

    pre_claim = RecoveryPreDispatchClaim.create(
        attempt_identity_digest=attempt.identity_digest,
        hold_revision=1,
        claim_revision=1,
        idempotency_key=recovery_attempt_idempotency_key(attempt),
        claimed_at=_NOW,
    )
    raw_pre_claim = {
        "attempt_identity_digest": pre_claim.attempt_identity_digest,
        "hold_revision": 1,
        "claim_revision": 1,
        "idempotency_key": pre_claim.idempotency_key,
        "claimed_at": _NOW.isoformat(),
        "claim_digest": pre_claim.claim_digest,
    }
    assert claim_from_record(raw_pre_claim, attempt=attempt, hold_revision=1) == pre_claim
    assert claim_from_record({}, attempt=attempt, hold_revision=1) is None
    assert claim_from_record(raw_pre_claim, attempt=attempt, hold_revision=2) is None

    disp = RecoveryDispatchResult.create(
        attempt_identity_digest=attempt.identity_digest,
        claim_digest=pre_claim.claim_digest,
        outcome=RecoveryDispatchOutcome.DISPATCHED,
        provider_receipt_digest=digest,
        recorded_at=_NOW,
    )
    raw_disp = {
        "dispatch_outcome": disp.outcome,
        "dispatch_recorded_at": _NOW.isoformat(),
        "provider_receipt_digest": digest,
        "dispatch_result_digest": disp.result_digest,
    }
    assert dispatch_from_record(None, claim=pre_claim) is None
    assert dispatch_from_record({}, claim=pre_claim) is None
    assert dispatch_from_record({**raw_disp, "dispatch_outcome": "bad"}, claim=pre_claim) is None
    assert (
        dispatch_from_record({**raw_disp, "dispatch_result_digest": digest}, claim=pre_claim)
        is None
    )
    assert dispatch_from_record(raw_disp, claim=pre_claim) == disp

    assert claim_records({"claims": "bad"}) == ()
    assert claim_records({"claims": [{"a": 1}, "skip"]}) == ({"a": 1},)
    assert observation_records({"observations": "bad"}) == ()
    assert observation_records({"observations": [{"b": 2}, 5]}) == ({"b": 2},)

    rec_claim = claim_to_record(eff_claim)
    assert claim_from_mapping(rec_claim) == eff_claim
    assert claim_from_mapping({**rec_claim, "superseded_by": digest}) is None
    assert claim_from_mapping({}) is None

    lookup = ReleaseReceiptLookup.create(
        recovery_attempt_digest=attempt.identity_digest,
        effect_claim_digest=eff_claim.claim_digest,
        hold_revision=1,
        release_receipt_digest=digest,
    )
    raw_lookup = {
        "recovery_attempt_digest": lookup.recovery_attempt_digest,
        "effect_claim_digest": lookup.effect_claim_digest,
        "hold_revision": 1,
        "release_receipt_digest": digest,
        "lookup_digest": lookup.lookup_digest,
    }
    assert lookup_from_record(None) is None
    assert lookup_from_record({}) is None
    assert lookup_from_record({**raw_lookup, "lookup_digest": digest}) is None
    assert lookup_from_record(raw_lookup) == lookup
    assert terminal_reason(()) == TerminalTransitionRejection.ALREADY_TERMINAL.value
    assert terminal_reason((TerminalTransitionRejection.CLAIM_EXPIRED,)) == "claim_expired"

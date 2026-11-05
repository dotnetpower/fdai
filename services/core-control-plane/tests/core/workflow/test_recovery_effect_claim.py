"""Focused deterministic tests for recovery effect completion claims (#656)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.dispatch_claim import (
    DEFAULT_ACTION_DISPATCH_CLAIM_LEASE,
    claim_action_dispatch,
    claim_expired,
    claim_generation,
    claim_is_current,
    dispatch_event,
    latest_dispatch_claim,
    record_action_dispatched,
)
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
)
from fdai.core.workflow.recovery_coordinator_effect import RecoveryEffectCoordinator
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryCoordinatorConfig,
    RecoveryEffectObservation,
)
from fdai.core.workflow.recovery_coordinator_records import claim_to_record, effect_key
from fdai.core.workflow.recovery_coordinator_support import (
    RecoveryAdmissionGate,
    RecoveryEvidenceJournal,
)
from fdai.core.workflow.recovery_effect_claim import (
    CompletionClaimRejectionReason,
    EffectCompletionClaim,
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
    is_current_success,
    supersede_claim,
    verify_effect_evidence,
)
from fdai.core.workflow.schedule import scheduled_task_from_workflow
from fdai.core.workflow.workflow_runtime import (
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
)
from fdai.shared.contracts.models import (
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowStepKind,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.ontology_query import content_digest

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_ATTEMPT_DIGEST = "sha256:" + "a" * 64
_ACTION_DIGEST = "sha256:" + "b" * 64
_SAFEGUARD_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64
_TARGET_DIGEST = "sha256:" + "e" * 64
_EFFECT_DIGEST = "sha256:" + "f" * 64
_ENVELOPE_DIGEST = "sha256:" + "1" * 64
_EVIDENCE_DIGEST = "sha256:" + "2" * 64
_WATERMARK_DIGEST = "sha256:" + "3" * 64
_ADMISSION_DIGEST = "sha256:" + "4" * 64


def _make_claim(
    *,
    success: bool = True,
    generation: int = 1,
    provider_receipt_digest: str = _RECEIPT_DIGEST,
) -> EffectCompletionClaim:
    factory = (
        EffectCompletionClaim.create_success
        if success
        else EffectCompletionClaim.create_non_success
    )
    return factory(
        attempt_identity_digest=_ATTEMPT_DIGEST,
        action_digest=_ACTION_DIGEST,
        safeguard_bundle_digest=_SAFEGUARD_DIGEST,
        provider_receipt_digest=provider_receipt_digest,
        target_digest=_TARGET_DIGEST,
        expected_effect_digest=_EFFECT_DIGEST,
        approved_envelope_digest=_ENVELOPE_DIGEST,
        source_revision="commit:" + "0" * 40,
        evidence_window_start=_NOW - timedelta(minutes=5),
        evidence_window_end=_NOW,
        effect_evidence_digest=_EVIDENCE_DIGEST,
        validity_start=_NOW,
        validity_end=_NOW + timedelta(hours=1),
        watermark_set_digest=_WATERMARK_DIGEST,
        hold_revision=1,
        admission_digest=_ADMISSION_DIGEST,
        generation=generation,
    )


def _make_evidence(
    *,
    authority_class: EffectEvidenceClass = EffectEvidenceClass.AUTHORITATIVE_EXTERNAL,
    observer_identity: str = "observer@monitor.example.com",
    synthetic: bool = False,
    completeness: bool = True,
    conflict_status: str = "none",
) -> EffectEvidenceRecord:
    digest = content_digest(
        {
            "observer_identity": observer_identity,
            "observer_authority_class": authority_class.value,
        }
    )
    return EffectEvidenceRecord(
        observer_identity=observer_identity,
        observer_authority_class=authority_class,
        purpose_version="1.0",
        method_version="1.0",
        event_time=_NOW - timedelta(minutes=1),
        recorded_time=_NOW,
        freshness_policy_seconds=300,
        completeness=completeness,
        provenance="external_monitor",
        conflict_status=conflict_status,
        synthetic=synthetic,
        evidence_digest=digest,
    )


class TestEffectCompletionClaim:
    def test_create_success_and_non_success(self) -> None:
        claim = _make_claim(success=True)
        assert claim.success is True and claim.generation == 1 and claim.superseded_by is None
        assert claim.execution_authority is False and claim.claim_digest.startswith("sha256:")
        non_success = _make_claim(success=False)
        assert non_success.success is False and non_success.execution_authority is False

    def test_deterministic_and_generation_digests(self) -> None:
        assert _make_claim().claim_digest == _make_claim().claim_digest
        assert _make_claim(generation=1).claim_digest != _make_claim(generation=2).claim_digest

    def test_reject_execution_authority(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="execution authority"):
            replace(claim, execution_authority=True)  # type: ignore[arg-type]

    def test_reject_zero_generation(self) -> None:
        with pytest.raises(ValueError, match="generation"):
            _make_claim(generation=0)

    def test_reject_tampered_digest(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="mismatched"):
            replace(claim, claim_digest="sha256:" + "9" * 64)


class TestSupersession:
    def test_supersede_changes_digest(self) -> None:
        claim = _make_claim()
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        assert superseded.superseded_by == "sha256:" + "5" * 64
        assert superseded.claim_digest != claim.claim_digest

    def test_cannot_supersede_twice(self) -> None:
        claim = _make_claim()
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        with pytest.raises(ValueError, match="already superseded"):
            supersede_claim(superseded, superseding_digest="sha256:" + "6" * 64)

    def test_reject_invalid_superseding_digest(self) -> None:
        claim = _make_claim()
        with pytest.raises(ValueError, match="superseding_digest"):
            supersede_claim(claim, superseding_digest="bad")


class TestIsCurrentSuccess:
    def test_current_success(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW + timedelta(minutes=30)) is True

    def test_non_success(self) -> None:
        claim = _make_claim(success=False)
        assert is_current_success(claim, now=_NOW + timedelta(minutes=30)) is False

    def test_expired(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW + timedelta(hours=2)) is False

    def test_not_yet_valid(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=_NOW - timedelta(minutes=10)) is False

    def test_superseded(self) -> None:
        claim = _make_claim(success=True)
        superseded = supersede_claim(claim, superseding_digest="sha256:" + "5" * 64)
        assert is_current_success(superseded, now=_NOW + timedelta(minutes=30)) is False

    def test_naive_datetime_returns_false(self) -> None:
        claim = _make_claim(success=True)
        assert is_current_success(claim, now=datetime(2026, 9, 11, 0, 30)) is False


def _verify(evidence: EffectEvidenceRecord) -> tuple[bool, tuple[object, ...]]:
    return verify_effect_evidence(
        evidence=evidence,
        executor_identity="executor@example.com",
        provider_identity="provider@cloud.example.com",
    )


class TestVerifyEffectEvidence:
    def test_eligible(self) -> None:
        eligible, reasons = _verify(_make_evidence())
        assert eligible is True and reasons == ()

    def test_executor_controlled_provenance(self) -> None:
        eligible, reasons = _verify(
            _make_evidence(authority_class=EffectEvidenceClass.EXECUTOR_CONTROLLED)
        )
        assert eligible is False and CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE in reasons

    def test_identity_separation_executor(self) -> None:
        eligible, reasons = _verify(_make_evidence(observer_identity="executor@example.com"))
        assert (
            eligible is False
            and CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION in reasons
        )

    def test_identity_separation_provider(self) -> None:
        eligible, reasons = _verify(_make_evidence(observer_identity="provider@cloud.example.com"))
        assert (
            eligible is False
            and CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION in reasons
        )

    def test_synthetic_evidence_rejected(self) -> None:
        with pytest.raises(ValueError, match="synthetic"):
            _make_evidence(synthetic=True)

    def test_incomplete_evidence(self) -> None:
        eligible, reasons = _verify(_make_evidence(completeness=False))
        assert eligible is False and CompletionClaimRejectionReason.FINALITY_INCOMPLETE in reasons

    def test_conflicting_evidence(self) -> None:
        eligible, reasons = _verify(_make_evidence(conflict_status="conflicting"))
        assert eligible is False and CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE in reasons

    def test_stale_evidence_class(self) -> None:
        assert _verify(_make_evidence(authority_class=EffectEvidenceClass.STALE))[0] is False

    def test_missing_evidence_class(self) -> None:
        assert _verify(_make_evidence(authority_class=EffectEvidenceClass.MISSING))[0] is False

    def test_out_of_envelope(self) -> None:
        assert (
            _verify(_make_evidence(authority_class=EffectEvidenceClass.OUT_OF_ENVELOPE))[0] is False
        )

    def test_censored_evidence(self) -> None:
        assert _verify(_make_evidence(authority_class=EffectEvidenceClass.CENSORED))[0] is False


class TestEffectReceiptSubstitution:
    def test_different_receipt_different_claim(self) -> None:
        a = _make_claim()
        b = _make_claim(provider_receipt_digest="sha256:" + "9" * 64)
        assert a.claim_digest != b.claim_digest


class TestFinalizedWatermark:
    def test_create(self) -> None:
        wm = FinalizedWatermark(
            source_id="monitor-1", watermark=_NOW, final=True, watermark_digest="sha256:" + "7" * 64
        )
        assert wm.final is True

    def test_reject_empty_source(self) -> None:
        with pytest.raises(ValueError, match="source_id"):
            FinalizedWatermark(
                source_id="", watermark=_NOW, final=True, watermark_digest="sha256:" + "7" * 64
            )

    def test_reject_naive_watermark(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            FinalizedWatermark(
                source_id="monitor-1",
                watermark=datetime(2026, 1, 1),
                final=True,
                watermark_digest="sha256:" + "7" * 64,
            )

    def test_reject_bad_digest(self) -> None:
        with pytest.raises(ValueError, match="digest"):
            FinalizedWatermark(
                source_id="monitor-1", watermark=_NOW, final=True, watermark_digest="bad"
            )


def _sched_wf(
    *,
    kind: WorkflowTriggerKind = WorkflowTriggerKind.SCHEDULE,
    steps: list[WorkflowStep] | None = None,
) -> Workflow:
    trigger = (
        WorkflowTrigger(kind=WorkflowTriggerKind.SCHEDULE, schedule="0 2 * * *")
        if kind is WorkflowTriggerKind.SCHEDULE
        else WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="sig.drift")
    )
    return Workflow(
        schema_version="1.0.0",
        name="scheduled-gpu-task",
        version="1.0.0",
        trigger=trigger,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=30, min_accuracy=0.99, max_policy_escapes=0
        ),
        steps=steps
        if steps is not None
        else [
            WorkflowStep(id="gate", kind=WorkflowStepKind.GATE, gate_ref="g1"),
            WorkflowStep(id="run", action_type_ref="ops.gated"),
        ],
    )


class TestScheduledTaskFromWorkflow:
    def test_schedule_validation_and_materialization(self) -> None:
        with pytest.raises(ValueError, match="trigger.kind=schedule"):
            scheduled_task_from_workflow(
                _sched_wf(kind=WorkflowTriggerKind.SIGNAL),
                target_resource_ref="res-1",
                artifact_ref="art-1",
                created_by="op-1",
            )
        wf = _sched_wf()
        for target_ref, art_ref, match in (
            ("", "art-1", "target_resource_ref"),
            ("res-1", "", "artifact_ref"),
        ):
            with pytest.raises(ValueError, match=match):
                scheduled_task_from_workflow(
                    wf, target_resource_ref=target_ref, artifact_ref=art_ref, created_by="op-1"
                )
        multi = _sched_wf(
            steps=[
                WorkflowStep(id="a1", action_type_ref="ops.a"),
                WorkflowStep(id="a2", action_type_ref="ops.b"),
            ]
        )
        with pytest.raises(ValueError, match="exactly one action step"):
            scheduled_task_from_workflow(
                multi, target_resource_ref="res-1", artifact_ref="art-1", created_by="op-1"
            )
        task = scheduled_task_from_workflow(
            wf, target_resource_ref="res-1", artifact_ref="art-1", created_by="op-1"
        )
        assert task.cron_expression == "0 2 * * *" and task.resource_ref == "res-1"
        override = scheduled_task_from_workflow(
            wf,
            target_resource_ref="res-1",
            artifact_ref="art-1",
            created_by="op-1",
            cron_expression="*/15 * * * *",
        )
        assert override.cron_expression == "*/15 * * * *" and override.task_id == task.task_id


class _RejectingAppendStore(InMemoryProcessRuntimeStore):
    def __init__(self, *, swallow: bool = False) -> None:
        super().__init__()
        self._swallow = swallow

    async def append_event(self, event: ProcessEvent) -> bool:
        if not self._swallow:
            return False
        del event
        return True


class TestActionDispatchClaim:
    def test_claim_generation_and_expiry_edges(self) -> None:
        assert claim_generation(None) == 0
        for gen, lease_raw, exp_gen in (
            (-1, 123, 0),
            (2, "not-an-iso-timestamp", 2),
        ):
            ev = ProcessEvent(
                event_id=f"e-{gen}",
                process_id="p-1",
                kind=ProcessEventKind.ACTION_DISPATCH_CLAIMED,
                idempotency_key=f"k-{gen}",
                recorded_at=_NOW,
                correlation_id="c-1",
                payload={"generation": gen, "lease_expires_at": lease_raw},
            )
            assert claim_generation(ev) == exp_gen and claim_expired(ev, _NOW) is True

    @pytest.mark.asyncio
    async def test_claim_lifecycle_and_fencing(self) -> None:
        store = InMemoryProcessRuntimeStore()
        step = RunbookStep(id="step-1", action_type="ops.restart", params={"p": 1})
        await store.create(
            snapshot=ProcessSnapshot(
                process_id="p-1",
                workflow_ref="wf",
                workflow_version="1",
                status=ProcessStatus.RUNNING,
                current_step="step-1",
                target_resource_id="res-1",
                started_at=_NOW,
                updated_at=_NOW,
                correlation_id="c-1",
            ),
            event=ProcessEvent(
                event_id="e-0",
                process_id="p-1",
                kind=ProcessEventKind.PROCESS_CREATED,
                idempotency_key="p-1:created",
                recorded_at=_NOW,
                correlation_id="c-1",
            ),
        )

        async def _claim(target_store: InMemoryProcessRuntimeStore, at: datetime):
            return await claim_action_dispatch(
                target_store,
                process_id="p-1",
                step=step,
                attempt=1,
                correlation_id="c-1",
                proposal_ref="prop-1",
                lease=DEFAULT_ACTION_DISPATCH_CLAIM_LEASE,
                now=at,
            )

        first = await _claim(store, _NOW)
        assert first is not None and claim_generation(first) == 1
        assert await _claim(store, _NOW + timedelta(seconds=5)) is None
        expired_now = _NOW + DEFAULT_ACTION_DISPATCH_CLAIM_LEASE + timedelta(seconds=1)
        second = await _claim(store, expired_now)
        assert second is not None and claim_generation(second) == 2
        assert latest_dispatch_claim(await store.events("p-1"), step, attempt=1) == second
        assert await record_action_dispatched(
            store,
            process_id="p-1",
            step=step,
            attempt=1,
            correlation_id="c-1",
            proposal_ref="prop-1",
            params={"p": 1},
            claim=second,
            recorded_at=expired_now,
        )
        assert dispatch_event(await store.events("p-1"), step, attempt=1) is not None
        assert not await claim_is_current(
            store, process_id="p-1", claim=second, step=step, attempt=1
        )
        assert await _claim(store, expired_now + timedelta(minutes=1)) is None
        for swallow in (False, True):
            assert await _claim(_RejectingAppendStore(swallow=swallow), _NOW) is None


class _StubIntake:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def record_observation(self, **kwargs: object) -> bool:
        del kwargs
        if self.fail:
            raise RuntimeError("intake write failed")
        return True


class _StubObserver:
    def __init__(
        self,
        observation: RecoveryEffectObservation | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.observation = observation
        self.fail = fail

    async def observe_recovery_effect(self, **kwargs: object) -> RecoveryEffectObservation | None:
        del kwargs
        if self.fail:
            raise RuntimeError("observer read failed")
        return self.observation


class _StubAdmissionProvider:
    async def admit(
        self,
        *,
        evidence_digest: str,
        scope_digest: str,
        purpose_id: str,
        source_revision: str,
    ) -> DecisionEvidenceAdmission:
        return DecisionEvidenceAdmission(
            receipt_digest=_ADMISSION_DIGEST,
            verification_bundle_digest="sha256:" + "8" * 64,
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=purpose_id,
            source_revision=source_revision,
            verified_at=_NOW - timedelta(minutes=1),
            valid_until=_NOW + timedelta(minutes=10),
        )


class _RacyEffectStateStore(InMemoryStateStore):
    def __init__(self, *, fail_create: bool = False, fail_cas: bool = False) -> None:
        super().__init__(linearization_clock=lambda: _NOW)
        self.fail_create = fail_create
        self.fail_cas = fail_cas

    async def write_state_with_audit_if_absent(
        self, key: str, value: object, audit: object
    ) -> bool:
        if self.fail_create and key.startswith("workflow:recovery-effect:"):
            return False
        return await super().write_state_with_audit_if_absent(key, value, audit)  # type: ignore[arg-type]

    async def compare_and_set_state_with_audit(
        self, key: str, value: object, **kwargs: object
    ) -> bool:
        if self.fail_cas and key.startswith("workflow:recovery-effect:"):
            return False
        return await super().compare_and_set_state_with_audit(key, value, **kwargs)  # type: ignore[arg-type]


def _effect_observation(*, final: bool = True, success: bool = True) -> RecoveryEffectObservation:
    return RecoveryEffectObservation(
        evidence=_make_evidence(),
        observer_identity="observer@monitor.example.com",
        provider_identity="provider@cloud.example.com",
        expected_effect_digest=_EFFECT_DIGEST,
        approved_envelope_digest=_ENVELOPE_DIGEST,
        action_digest=_ACTION_DIGEST,
        evidence_window_start=_NOW - timedelta(minutes=5),
        evidence_window_end=_NOW,
        watermarks=(
            FinalizedWatermark(
                source_id="mon-1",
                watermark=_NOW,
                final=final,
                watermark_digest=_WATERMARK_DIGEST,
            ),
        ),
        success=success,
    )


def _effect_coord(
    store: InMemoryStateStore,
    *,
    observer: _StubObserver | None = None,
    intake: _StubIntake | None = None,
    with_admissions: bool = True,
) -> tuple[
    RecoveryEffectCoordinator,
    ProcessSnapshot,
    RecoveryAttemptIdentity,
    WorkflowApprovalSnapshot,
]:
    cfg = RecoveryCoordinatorConfig(
        executor_identity="executor@example.com",
        source_revision="commit:" + "0" * 40,
    )
    journal = RecoveryEvidenceJournal(audit_store=store, clock=lambda: _NOW)
    admission = RecoveryAdmissionGate(
        admission_provider=_StubAdmissionProvider() if with_admissions else None,
        config=cfg,
        journal=journal,
    )
    attempt = RecoveryAttemptIdentity.create(
        process_id="p-eff-1",
        failed_compensation_proposal_digest="sha256:" + "a" * 64,
        hold_revision=1,
        recovery_action_type="workflow.recovery.reconcile",
        recovery_payload_digest="sha256:" + "b" * 64,
        target_digest=f"sha256:{'e' * 64}",
        source_revision=cfg.source_revision,
        attempt_number=1,
    )
    snapshot = ProcessSnapshot(
        process_id="p-eff-1",
        workflow_ref="wf",
        workflow_version="1",
        status=ProcessStatus.COMPENSATING,
        current_step="s1",
        target_resource_id="res-eff-1",
        started_at=_NOW - timedelta(minutes=10),
        updated_at=_NOW,
        correlation_id="corr-1",
    )
    approval = WorkflowApprovalSnapshot(
        process_id="p-eff-1",
        step_id="step-eff-1",
        attempt=1,
        requester_principal="requester@example.com",
        requested_at=_NOW - timedelta(minutes=5),
        expires_at=_NOW + timedelta(minutes=25),
        decisions=(
            WorkflowApprovalDecision(
                principal="approver@example.com",
                decision="approved",
                receipt_ref="r-1",
            ),
        ),
        revision=1,
    )
    coord = RecoveryEffectCoordinator(
        admission=admission,
        audit_store=store,
        config=cfg,
        journal=journal,
        effect_observer=observer,
        effect_observations=intake,
    )
    return coord, snapshot, attempt, approval


async def _claim_with(
    coord: RecoveryEffectCoordinator,
    snapshot: ProcessSnapshot,
    attempt: RecoveryAttemptIdentity,
    approval: WorkflowApprovalSnapshot,
):
    return await coord.claim_effect(
        snapshot=snapshot,
        attempt=attempt,
        hold_revision=1,
        safeguard_bundle_digest=_SAFEGUARD_DIGEST,
        provider_receipt_digest=_RECEIPT_DIGEST,
        approval=approval,
        compensation_receipt_digests=(_RECEIPT_DIGEST,),
    )


class TestRecoveryEffectCoordinator:
    @pytest.mark.asyncio
    async def test_record_independent_observation_paths(self) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        obs = _effect_observation()
        for intake, expected in (
            (None, False),
            (_StubIntake(fail=False), True),
            (_StubIntake(fail=True), False),
        ):
            coord, _, attempt, _ = _effect_coord(store, intake=intake)
            assert (
                await coord.record_independent_observation(
                    attempt=attempt,
                    target_resource_id="res-eff-1",
                    provider_receipt_digest=_RECEIPT_DIGEST,
                    observation=obs,
                )
                is expected
            )

    @pytest.mark.asyncio
    async def test_claim_effect_unavailable_and_ineligible_branches(self) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        for observer, intake, with_adm, expected_reason in (
            (None, None, True, RecoveryAttemptRejectionReason.EFFECT_OBSERVER_UNBOUND),
            (
                _StubObserver(fail=True),
                None,
                True,
                RecoveryAttemptRejectionReason.EFFECT_OBSERVATION_UNREADABLE,
            ),
            (
                _StubObserver(None),
                _StubIntake(),
                True,
                RecoveryAttemptRejectionReason.EFFECT_OBSERVATION_MISSING,
            ),
            (
                _StubObserver(_effect_observation(final=False)),
                None,
                True,
                CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE.value,
            ),
            (
                _StubObserver(_effect_observation()),
                None,
                False,
                RecoveryAttemptRejectionReason.EFFECT_ADMISSION_UNAVAILABLE,
            ),
        ):
            coord, snapshot, attempt, approval = _effect_coord(
                store, observer=observer, intake=intake, with_admissions=with_adm
            )
            res = await _claim_with(coord, snapshot, attempt, approval)
            assert res.reason == expected_reason

    @pytest.mark.asyncio
    async def test_claim_supersession_and_storage_edge_cases(self) -> None:
        store = InMemoryStateStore(linearization_clock=lambda: _NOW)
        coord, snapshot, attempt, approval = _effect_coord(
            store, observer=_StubObserver(_effect_observation(success=True))
        )
        assert await coord.read_current_claim(attempt) is None
        first = await _claim_with(coord, snapshot, attempt, approval)
        assert first.claim is not None and first.claim.generation == 1
        key = effect_key(attempt)
        stored = await store.read_state(key)
        assert stored is not None
        await store.write_state(
            key,
            {**dict(stored), "claims": [{"claim_digest": "invalid"}, *list(stored["claims"])]},
        )
        non_success_coord, _, _, _ = _effect_coord(
            store, observer=_StubObserver(_effect_observation(success=False))
        )
        second = await _claim_with(non_success_coord, snapshot, attempt, approval)
        assert second.claim is not None and second.claim.generation == 2
        assert second.claim.success is False
        current = await non_success_coord.read_current_claim(attempt)
        assert current is not None and current.claim_digest == second.claim.claim_digest

        await store.write_state(key, {"revision": None, "generation": None, "claims": []})
        dup = await _claim_with(non_success_coord, snapshot, attempt, approval)
        assert dup.reason == CompletionClaimRejectionReason.DUPLICATE_CLAIM.value
        assert await non_success_coord.read_current_claim(attempt) is None

        racy_create = _RacyEffectStateStore(fail_create=True)
        c_create, _, _, _ = _effect_coord(
            racy_create, observer=_StubObserver(_effect_observation())
        )
        out_create = await _claim_with(c_create, snapshot, attempt, approval)
        assert out_create.reason == CompletionClaimRejectionReason.DUPLICATE_CLAIM.value

        racy_cas = _RacyEffectStateStore(fail_cas=True)
        await racy_cas.write_state(
            key,
            {
                "revision": 1,
                "generation": 1,
                "current_claim_digest": first.claim.claim_digest,
                "claims": [claim_to_record(first.claim)],
                "observations": [],
            },
        )
        c_cas, _, _, _ = _effect_coord(racy_cas, observer=_StubObserver(_effect_observation()))
        out_cas = await _claim_with(c_cas, snapshot, attempt, approval)
        assert out_cas.claim is not None
        assert out_cas.claim.claim_digest == first.claim.claim_digest

"""No-network unit-only facts using the real safeguard and independent-admission stores.

The sink and positive DE proofs are explicit synthetic test fixtures, never production
bindings or live evidence. This file does not weaken any production reader or verifier.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fdai.agents import InMemoryBus, load_pantheon
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectDrift,
    AlertExecutedActionRecord,
    alert_effect_key,
    alert_executed_action_key,
)
from fdai.core.executor import ResourceLockManager
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
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
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.workflow.outcome_verification import StateStoreWorkflowOutcomeLedger
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.delivery.alert_noise_effects import (
    HeimdallAlertEffectHandler,
    StateStoreAlertEffectReader,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.alert_noise import AlertEffectReader
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.ontology_query import content_digest

from tests.core.detection.alert_noise.test_outcomes import _fixture_context, _fixture_observation
from tests.delivery.test_alert_noise_evidence import SOURCE, _install_record


class _FixturePublication:
    """Unit-only sink response; the real coordinator must invoke its actual boundary guard."""

    def __init__(self, receipt):
        self.receipt, self.calls = receipt, 0

    async def dispatch(self, *, evidence_record, started_at, pre_invoke_guard):
        await pre_invoke_guard()
        assert evidence_record.dispatch_start_checkpoint is not None
        self.calls += 1
        receipt = self.receipt
        return (
            DispatchTransportState.ACKNOWLEDGED,
            AuthoritativeSinkState.COMMITTED,
            content_digest({"domain": "pr-publish-reference", "pr_ref": receipt.pr_ref}),
            content_digest(
                {
                    "domain": "pr-publish-status",
                    "pr_ref": receipt.pr_ref,
                    "state": receipt.state,
                    "already_existed": receipt.already_existed,
                }
            ),
        )


def _reader(h, **changes):
    values = dict(
        store=h.store,
        admissions=h.admissions,
        dispatches=h.dispatches,
        closures=h.closures,
        processes=h.processes,
        tenant_ref="tenant:example",
        scope_ref="scope:example",
        source_revision=SOURCE,
        source_ref="source:example",
        observer_ref="observer:example",
        executor_ref="executor:example",
        identities={
            "source:example": "principal:effect-source",
            "observer:example": "principal:effect-observer",
            "executor:example": "principal:effect-executor",
        },
        authority_class="provider_observation",
        clock=lambda: h.clock[0],
        purpose=h.context.purpose,
    )
    return StateStoreAlertEffectReader(**{**values, **changes})


async def _install(h, *, payload=None, observation_changes=None, receipt_changes=None):
    """Write positive contract shapes ONLY into the isolated in-memory test stores."""
    payload = dict(payload or h.payload)
    payload["observation"] = {**payload["observation"], **(observation_changes or {})}
    values = {"source_identity": "principal:effect-source", "event_at": h.observation.window_end}
    return await _install_record(
        h,
        key=h.key,
        payload=payload,
        purpose=h.context.purpose,
        receipt_changes={**values, **(receipt_changes or {})},
    )


async def _harness(*, restore=False):
    context = _fixture_context(restore=restore)
    action, notice = context.execution.action, context.execution.source_event
    clock = [context.dispatched_at]
    store = InMemoryStateStore(linearization_clock=lambda: clock[0])
    processes = InMemoryProcessRuntimeStore()
    lineage = action.workflow_action
    assert lineage is not None
    await processes.create(
        snapshot=ProcessSnapshot(
            process_id=lineage.process_id,
            workflow_ref="alert-fixture",
            workflow_version="1.0.0",
            status=ProcessStatus.COMPENSATING if restore else ProcessStatus.WAITING,
            current_step=lineage.step_id,
            target_resource_id=action.target_resource_ref,
            started_at=context.execution.plan.created_at,
            updated_at=clock[0],
            correlation_id=notice.correlation_id,
        ),
        event=ProcessEvent(
            event_id="fixture-created",
            process_id=lineage.process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="fixture-created",
            recorded_at=context.execution.plan.created_at,
            correlation_id=notice.correlation_id,
        ),
    )
    for event in context.process_events:
        await processes.append_event(event)
    reservations, fences = InMemoryIdempotencyReservationStore(), InMemoryTargetDispatchFenceStore()
    dispatches = InMemorySafeguardDispatchEvidenceStore()
    closures = InMemoryPostReleaseClosureStore(reservation_store=reservations, fence_store=fences)
    coordinator = SafeguardLifecycleCoordinator(
        resource_lock=ResourceLockManager(
            clock=lambda: clock[0], acquisition_id_factory=lambda: "effect-fixture"
        ),
        reservation_store=reservations,
        audit_intent_store=InMemoryAuditIntentStore(),
        fence_store=fences,
        evidence_store=dispatches,
        closure_store=closures,
        denial_audit_store=store,
        commitment_store=ProcessRuntimeSafeguardCommitmentStore(processes),
        continuity_policy=EffectSinkContinuityPolicy.create(
            sink_id="effect-unit-fixture",
            sink_version="1.0.0",
            strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
            cancellation_supported=True,
            durable_unknown_quarantine=True,
            reconciliation_supported=True,
        ),
        config=SafeguardLifecycleCoordinatorConfig(
            source_revision=SOURCE,
            producer_id="fdai.core.executor",
            producer_version="1.0.0",
            actor="Thor",
            expected_lock_verifier_id="fdai-in-memory-lock-readback",
            expected_lock_verifier_version="1.0.0",
            expected_lock_trust_anchor_id="fdai:local-test-only",
        ),
        clock=lambda: clock[0],
    )
    safety = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.PR_MANUAL,
        plan_digest=content_digest({"fixture": "publication-only"}),
        plan_kind="alert_noise_manual_pr",
    )
    assert isinstance(safety, SafeguardReceipt)
    port = _FixturePublication(context.execution.publication_receipt)
    dispatched = await coordinator.dispatch(
        action=action,
        safeguard_receipt=safety,
        dispatch_port=port,
        correlation_id=notice.correlation_id,
    )
    assert dispatched.lifecycle is not None and dispatched.lifecycle.evidence_record is not None
    assert dispatched.closure_receipt is not None and dispatched.bundle_digest is not None
    proof = dispatched.lifecycle.evidence_record
    execution = AlertExecutedActionRecord.model_validate(
        {
            **context.execution.model_dump(mode="python"),
            "dispatch_generation": proof.identity.target_fence_generation,
        }
    )
    context = replace(
        context, execution=execution, safeguard_bundle_digest=dispatched.bundle_digest
    )
    await store.write_state(
        alert_executed_action_key(full_action_digest(action)), execution.model_dump(mode="json")
    )
    observation = _fixture_observation(context)
    clock[0] = observation.recorded_at
    h = SimpleNamespace(
        context=context,
        observation=observation,
        clock=clock,
        store=store,
        processes=processes,
        dispatches=dispatches,
        closures=closures,
        port=port,
        admissions=StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: clock[0]),
    )
    h.key = alert_effect_key(
        plan_digest=digest_record(execution.plan), dispatch_ref=execution.dispatch_ref
    )
    h.payload = {
        "observation": observation.model_dump(mode="json"),
        "action_digest": full_action_digest(action),
        "dispatch_ref": execution.dispatch_ref,
        "dispatched_at": context.dispatched_at.isoformat(),
        "safeguard_bundle_digest": dispatched.bundle_digest,
    }
    h.receipt, h.admission = await _install(h)
    h.reader = _reader(h)
    h.bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)

    async def publish(principal, topic, payload):
        assert principal == "Heimdall" and topic == "object.drift"
        AlertEffectDrift.model_validate(payload)
        await h.bus.publish(principal, topic, payload)

    h.outcomes = StateStoreWorkflowOutcomeLedger(
        store=store, decision_evidence_provider=h.admissions, clock=lambda: clock[0]
    )
    h.handler = HeimdallAlertEffectHandler(
        store=store,
        processes=processes,
        reader=_reader(h, purpose=ALERT_EFFECT_PURPOSE),
        recovery_reader=_reader(h, purpose=ALERT_RECOVERY_EFFECT_PURPOSE),
        outcomes=h.outcomes,
        publish=publish,
        clock=lambda: clock[0],
    )
    h.notice = execution.source_event.model_dump(mode="json")
    return h


@pytest.fixture
async def effects():
    return await _harness()


async def _observe(h, reader=None):
    # Structural Protocol compatibility is checked by the parent's static validation.
    port: AlertEffectReader = reader or h.reader
    return await port.observe(
        h.context.execution.plan, dispatch_ref=h.context.execution.dispatch_ref
    )


async def test_reads_only_independently_admitted_exact_record(effects):
    observed = await _observe(effects)
    assert observed == effects.observation and observed is not None
    assert observed.execution_authority is False and effects.port.calls == 1
    assert await effects.store.read_states("alert-noise:outcome:", limit=10) == ()
    assert await _observe(effects, _reader(effects, admissions=None)) is None
    assert (
        await _reader(effects).observe(
            effects.context.execution.plan, dispatch_ref="proposal:absent"
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"synthetic": True},
        {"scope_digest": "sha256:" + "0" * 64},
        {"source_revision": "commit:" + "0" * 40},
        {"purpose_id": ALERT_RECOVERY_EFFECT_PURPOSE},
        {"source_identity": "principal:other-source"},
        {"authority_class": "fixture_only"},
        {"completeness_basis_points": 9999},
        {"conflict_status": "unknown"},
    ],
)
async def test_wrong_receipt_scope_source_purpose_and_synthetic_fail_closed(effects, changes):
    await _install(effects, receipt_changes=changes)
    with pytest.raises(AlertExecutionHeld):
        await _observe(effects)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_ref": "source:other"},
        {"observer_ref": "observer:other"},
        {"executor_ref": "executor:other"},
        {"recovery": True},
        {"configuration_matches": 1},
        {"synthetic": True},
        {"coverage": "partial"},
        {"dispatch_ref": "proposal:other"},
        {"plan_digest": "sha256:" + "0" * 64},
    ],
)
async def test_no_observer_booleans_or_independence_aliases_are_repaired(effects, changes):
    await _install(effects, observation_changes=changes)
    with pytest.raises(AlertExecutionHeld):
        await _observe(effects)


@pytest.mark.parametrize(
    "changes",
    [
        {"dispatch_ref": "proposal:other"},
        {"safeguard_bundle_digest": "sha256:" + "0" * 64},
        {"dispatched_at": "2026-09-14T11:59:59Z"},
        {"action_digest": "sha256:" + "0" * 64},
        {"provider_success": True},
    ],
)
async def test_exact_dispatch_identity_and_payload_shape_are_required(effects, changes):
    await _install(effects, payload={**effects.payload, **changes})
    with pytest.raises(AlertExecutionHeld):
        await _observe(effects)


async def test_full_action_digest_is_checked_against_real_coordinator_not_only_key(effects):
    raw = effects.context.execution.model_dump(mode="json")
    raw["action"]["event_id"] = "00000000-0000-0000-0000-000000000099"
    digest = full_action_digest(Action.model_validate(raw["action"]))
    raw["source_event"]["action_digest"] = digest
    changed = AlertExecutedActionRecord.model_validate(raw)
    await effects.store.write_state(
        alert_executed_action_key(digest), changed.model_dump(mode="json")
    )
    await _install(effects, payload={**effects.payload, "action_digest": digest})
    with pytest.raises(AlertExecutionHeld, match="dispatch_evidence_mismatch"):
        await _observe(effects)


async def test_missing_dispatch_and_closure_are_not_replaced_by_publication(effects, monkeypatch):
    async def absent(*args):
        return None

    original = effects.dispatches.read
    monkeypatch.setattr(effects.dispatches, "read", absent)
    assert await effects.handler.handle(effects.notice) is False
    monkeypatch.setattr(effects.dispatches, "read", original)
    monkeypatch.setattr(effects.closures, "read_receipt", absent)
    assert await effects.handler.handle(effects.notice) is False
    assert effects.bus.published == []


async def test_late_receipt_and_post_await_admission_expiry_hold(effects, monkeypatch):
    read_closure = effects.closures.read_receipt

    async def expiring(key):
        result = await read_closure(key)
        effects.clock[0] = effects.admission.valid_until
        return result

    monkeypatch.setattr(effects.closures, "read_receipt", expiring)
    assert await effects.handler.handle(effects.notice) is False
    assert not effects.bus.published


async def test_untrusted_reordered_and_public_api_only_triggers_are_audited_holds(
    effects, monkeypatch
):
    assert (
        await effects.handler.handle({**effects.notice, "producer_principal": "Operator"}) is False
    )
    assert (
        await effects.handler.handle({**effects.notice, "action_digest": "sha256:" + "0" * 64})
        is False
    )

    async def empty(process_id):
        return ()

    original = effects.processes.events
    monkeypatch.setattr(effects.processes, "events", empty)
    assert await effects.handler.handle(effects.notice) is False
    monkeypatch.setattr(effects.processes, "events", original)
    read_state = effects.store.read_state

    async def missing_effect(key):
        return None if key == effects.key else await read_state(key)

    monkeypatch.setattr(effects.store, "read_state", missing_effect)
    assert await effects.handler.handle({**effects.notice, "provider_success": True}) is False
    assert effects.bus.published == []
    assert (
        sum(
            row["entry"].get("action_kind") == "alert_noise.effect.held"
            for row in effects.store.audit_entries
        )
        == 4
    )


async def test_replay_journals_once_without_process_progress_or_workflow_admission(effects):
    before = await effects.processes.get("process:example")
    assert await effects.handler.handle(effects.notice) is True
    assert await effects.handler.handle(effects.notice) is True
    assert await effects.processes.get("process:example") == before
    events = await effects.processes.events("process:example")
    children = tuple(row for row in events if row.kind is ProcessEventKind.EVIDENCE_ATTACHED)
    assert len(children) == 1 and "independent_observation_ref" in children[0].payload
    assert len(effects.bus.published) == 2 and effects.port.calls == 1
    first, replay = (row.payload for row in effects.bus.published)
    assert (
        first == replay
        and first["effect_outcome"] == "verified"
        and first["process_completed"] is False
    )
    assert first["workflow_outcome_ref"] is not None
    assert not await effects.outcomes.verify(
        process_id="process:example",
        step_id="update_routing",
        proposal_ref=effects.context.execution.dispatch_ref,
        outcome="succeeded",
        receipt_ref=first["workflow_outcome_ref"],
    )
    journals = await effects.store.read_states("alert-noise:outcome:", limit=10)
    assert len(journals) == 1 and journals[0]["response_outcome"]["observed_value"] == 1.0


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("changes", [{"missed_incidents": 1}, {"eligible_events": 0}])
async def test_adverse_and_unscorable_effects_request_owner_review_not_fake_failure(
    restore, changes
):
    h = await _harness(restore=restore)
    await _install(h, observation_changes=changes)
    before = await h.processes.get("process:example")
    assert await h.handler.handle(h.notice) is True
    signal = h.bus.published[-1].payload
    assert signal["effect_outcome"] == (
        "recovery_incomplete"
        if restore
        else "unscorable"
        if "eligible_events" in changes
        else "recovery_required"
    )
    assert signal["workflow_outcome_ref"] is None and signal["process_completed"] is False
    assert await h.processes.get("process:example") == before and h.port.calls == 1
    assert await h.store.read_states("workflow:outcome:", limit=10) == ()


async def test_restore_observation_uses_separate_purpose_and_does_not_release_hold():
    h = await _harness(restore=True)
    assert await h.handler.handle(h.notice) is True
    signal = h.bus.published[-1].payload
    assert signal["effect_outcome"] == "recovered" and signal["process_completed"] is False
    with pytest.raises(AlertExecutionHeld):
        await _observe(h, _reader(h, purpose=ALERT_EFFECT_PURPOSE))
    assert await h.store.read_states("workflow:recovery-release-lookup:", limit=10) == ()


def test_constructor_rejects_different_refs_mapping_to_same_real_identity():
    h = SimpleNamespace(
        store=None,
        admissions=None,
        dispatches=None,
        closures=None,
        processes=None,
        context=SimpleNamespace(purpose=ALERT_EFFECT_PURPOSE),
        clock=[None],
    )
    for mapping in (
        {},
        {
            "source:example": "principal:same",
            "observer:example": "principal:SAME",
            "executor:example": "principal:separate",
        },
        {
            "source:example": "principal:separate",
            "observer:example": "principal:same",
            "executor:example": "principal:same",
        },
    ):
        with pytest.raises(ValueError, match="independent identity"):
            _reader(h, identities=mapping)


async def test_replaced_source_record_after_admission_never_reaches_outcome(effects, monkeypatch):
    read_closure = effects.closures.read_receipt

    async def replacing(key):
        closure = await read_closure(key)
        raw = await effects.store.read_state(effects.key)
        assert raw is not None
        raw["payload"]["observation"]["eligible_events"] += 1
        await effects.store.write_state(effects.key, raw)
        return closure

    monkeypatch.setattr(effects.closures, "read_receipt", replacing)
    with pytest.raises(AlertExecutionHeld, match="changed"):
        await _observe(effects)
    assert not await effects.store.read_states("workflow:outcome:", limit=10)
    assert effects.port.calls == 1


async def test_publish_failure_replays_retained_journal_without_dispatch(effects, monkeypatch):
    publish = effects.handler._publish

    async def unavailable(principal, topic, payload):
        raise RuntimeError("unit-only publication outage")

    monkeypatch.setattr(effects.handler, "_publish", unavailable)
    assert await effects.handler.handle(effects.notice) is False
    monkeypatch.setattr(effects.handler, "_publish", publish)
    assert await effects.handler.handle(effects.notice) is True
    assert effects.port.calls == 1 and len(effects.bus.published) == 1
    events = await effects.processes.events("process:example")
    assert sum(event.kind is ProcessEventKind.EVIDENCE_ATTACHED for event in events) == 1
    assert len(await effects.store.read_states("alert-noise:outcome:", limit=10)) == 1

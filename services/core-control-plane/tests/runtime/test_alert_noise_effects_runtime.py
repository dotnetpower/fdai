"""Source-authored, no-network scenarios; not live capability or executed test evidence.

Canonical Workflow, safeguard, publication and admission APIs run against explicit unit
stores when these tests are authorized. No private SQL copy substitutes for dispatch proof.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import fdai.runtime.alert_noise_effects as module
import psycopg
import pytest
from fdai.agents import InMemoryBus, load_pantheon
from fdai.core.detection.alert_noise.execution import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    ALERT_EFFECT_PURPOSE,
    ALERT_RECOVERY_EFFECT_PURPOSE,
    AlertEffectContext,
    alert_effect_deadline,
    alert_effect_key,
)
from fdai.core.detection.alert_noise.workflow import AlertWorkflowCoordinator
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import ResourceLockManager
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
from fdai.core.executor.testing_safeguard_lifecycle import (
    InMemoryAuditIntentStore,
    InMemoryIdempotencyReservationStore,
    InMemoryPostReleaseClosureStore,
    InMemorySafeguardDispatchEvidenceStore,
    InMemoryTargetDispatchFenceStore,
)
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.core.workflow.outcome_verification import (
    WORKFLOW_OUTCOME_EVIDENCE_PURPOSE,
    StateStoreWorkflowOutcomeLedger,
    workflow_outcome_evidence_digest,
    workflow_outcome_scope_digest,
)
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.delivery.alert_noise_effects import read_alert_execution
from fdai.delivery.alert_noise_execution_records import StateStoreAlertPublicationRecorder
from fdai.delivery.alert_noise_workflow import StateStoreAlertActionBinder
from fdai.runtime.alert_noise_config import (
    PRINCIPAL_SCOPES_ENV,
    SCOPE_BINDINGS_ENV,
    SOURCE_REVISION_ENV,
)
from fdai.runtime.alert_noise_effects import EFFECT_BINDINGS_ENV, bind_alert_effect_runtime
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.contracts.models import Action, ExecutionPath, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator, JsonSchemaEventValidator
from fdai.shared.providers.process_runtime import ProcessEventKind, ProcessStatus
from fdai.shared.providers.remediation_pr import PublishReceipt
from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_outcomes import _fixture_observation
from tests.core.detection.alert_noise.test_workflow import (
    _dispatched,
    _retain_admission,
)
from tests.core.detection.alert_noise.test_workflow import workflow_harness as workflow_harness
from tests.delivery.test_alert_noise_effects import _FixturePublication
from tests.delivery.test_alert_noise_evidence import SOURCE, _install_record


def _environment():
    """Generic unit-only DSN and identities; no real connection or principal is supplied."""
    binding = dict(
        tenant_ref="tenant:example",
        scope_ref="scope:example",
        source_ref="source:example",
        observer_ref="observer:example",
        executor_ref="executor:example",
        authority_class="provider_observation",
        identities={
            "source:example": "principal:effect-source",
            "observer:example": "principal:effect-observer",
            "executor:example": "principal:effect-executor",
        },
    )
    return {
        SCOPE_BINDINGS_ENV: json.dumps(
            [
                dict(
                    subscription_id=str(UUID(int=10)),
                    resource_group="example-rg",
                    tenant_ref="tenant:example",
                    scope_ref="scope:example",
                )
            ]
        ),
        PRINCIPAL_SCOPES_ENV: json.dumps({str(UUID(int=1)): ["scope:example"]}),
        SOURCE_REVISION_ENV: SOURCE,
        EFFECT_BINDINGS_ENV: json.dumps([binding]),
        "FDAI_STATE_STORE_DSN": "postgresql://example@127.0.0.1/example",
    }


def _options(h, environment=None):
    return dict(
        environment=environment if environment is not None else _environment(),
        store=h.store,
        processes=h.processes,
        workflows=h.coordinator,
        admissions=h.admissions,
        publish=AsyncMock(),
        clock=lambda: h.clock[0],
    )


def test_absence_is_none_without_touching_optional_stores(workflow_harness, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError(
            "an absent effect configuration must not construct PostgreSQL adapters"
        )

    monkeypatch.setattr(module, "PostgresSafeguardDispatchEvidenceStore", forbidden)
    options = {
        **_options(workflow_harness, {}),
        "processes": None,
        "workflows": None,
        "admissions": None,
    }
    assert bind_alert_effect_runtime(**options) is None


def test_existing_postgres_constructors_are_lazy_not_a_readiness_claim(
    workflow_harness, monkeypatch
):
    connect = AsyncMock(side_effect=AssertionError("startup must not connect"))
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    options = _options(workflow_harness)
    runtime = bind_alert_effect_runtime(**options)
    assert runtime is not None
    forward, recovery = runtime._readers[("tenant:example", "scope:example")]
    assert isinstance(forward._dispatches, module.PostgresSafeguardDispatchEvidenceStore)
    assert isinstance(forward._closures, module.PostgresPostReleaseClosureStore)
    assert forward._dispatches is recovery._dispatches and forward._closures is recovery._closures
    assert (
        forward._dispatches._config.dsn
        == forward._closures._config.dsn
        == options["environment"]["FDAI_STATE_STORE_DSN"]
    )
    assert runtime._holds.store is forward._store is workflow_harness.store
    connect.assert_not_awaited()


@pytest.mark.parametrize(
    "missing",
    [SOURCE_REVISION_ENV, SCOPE_BINDINGS_ENV, PRINCIPAL_SCOPES_ENV, "FDAI_STATE_STORE_DSN"],
)
def test_explicit_lost_configuration_has_no_fallback(workflow_harness, missing):
    environment = _environment()
    del environment[missing]
    environment["FDAI_DATABASE_URL"] = _environment()["FDAI_STATE_STORE_DSN"]
    with pytest.raises(ValueError):
        bind_alert_effect_runtime(**_options(workflow_harness, environment))


@pytest.mark.parametrize("raw", ["", "null", "[]", "[{}]", "[NaN]", json.dumps([{}] * 65)])
def test_explicit_malformed_bindings_fail_closed(workflow_harness, raw):
    environment = {**_environment(), EFFECT_BINDINGS_ENV: raw}
    with pytest.raises(ValueError):
        bind_alert_effect_runtime(**_options(workflow_harness, environment))


@pytest.mark.parametrize("missing", ["processes", "workflows", "admissions"])
def test_explicit_effects_require_canonical_dependencies(workflow_harness, missing):
    with pytest.raises(ValueError):
        bind_alert_effect_runtime(**{**_options(workflow_harness), missing: None})


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "tenant",
        "newline",
        "duplicate",
        "alias",
        "extra",
        "extra_identity",
        "repeated_field",
    ],
)
def test_exact_scope_and_three_independent_identity_maps_are_required(workflow_harness, change):
    environment = _environment()
    row = json.loads(environment[EFFECT_BINDINGS_ENV])[0]
    if change in {"scope", "tenant"}:
        row[change + "_ref"] = change + ":other"
    elif change == "newline":
        row["observer_ref"] += "\n"
    elif change == "alias":
        row["identities"][row["observer_ref"]] = row["identities"][row["executor_ref"]].upper()
    elif change == "extra":
        row["execution_authority"] = True
    elif change == "extra_identity":
        row["identities"]["principal:extra"] = "principal:extra"
    raw = json.dumps([row, row] if change == "duplicate" else [row])
    if change == "repeated_field":
        raw = raw.replace(
            '"scope_ref": "scope:example"',
            '"scope_ref": "scope:example", "scope_ref": "scope:example"',
        )
    with pytest.raises(ValueError):
        bind_alert_effect_runtime(
            **_options(workflow_harness, {**environment, EFFECT_BINDINGS_ENV: raw})
        )


@pytest.fixture
async def effects_runtime(workflow_harness, monkeypatch):
    h = workflow_harness
    # Explicit short unit budget fits the existing immutable five-minute promotion fixture.
    h.plan = AlertChangePlan.model_validate(
        {**h.plan.model_dump(mode="python"), "max_observation_seconds": 60}
    )
    h.inputs["plan_digest"] = digest_record(h.plan)
    await h.store.write_state(
        "alert-noise:plan:" + digest_record(h.plan), h.plan.model_dump(mode="json")
    )

    class FixtureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return h.clock[0].astimezone(tz)

    for name in ("orchestrator", "workflow_step_executor", "compensation"):
        monkeypatch.setattr(f"fdai.core.workflow.{name}.datetime", FixtureDatetime)
    ledger = StateStoreWorkflowOutcomeLedger(h.store, h.admissions, lambda: h.clock[0])
    orchestrator = WorkflowOrchestrator(
        planner=h.planner,
        action_types=h.actions,
        audit_store=h.store,
        process_store=h.processes,
        approval_provider=h.approvals,
        approval_decision_evidence_provider=h.admissions,
        outcome_verifier=ledger,
        action_dispatcher=EventBusWorkflowActionDispatcher(h.bus, "test:operator-request"),
    )
    h.coordinator = AlertWorkflowCoordinator(**{**h.options, "orchestrator": orchestrator})
    binder = StateStoreAlertActionBinder(
        workflows=h.coordinator,
        registered_actions=h.registered,
        store=h.store,
        clock=lambda: h.clock[0],
    )
    action, event = await _dispatched(h)
    bound = await binder.bind(action, event)
    # Explicit unit-only enforce input; no production promotion or approval is claimed.
    h.action = Action.model_validate(
        {
            **bound.model_dump(mode="python"),
            "mode": Mode.ENFORCE,
            "executor_identity_ref": "executor:example",
        }
    )
    reservations, fences = InMemoryIdempotencyReservationStore(), InMemoryTargetDispatchFenceStore()
    h.dispatches = InMemorySafeguardDispatchEvidenceStore()
    h.closures = InMemoryPostReleaseClosureStore(reservation_store=reservations, fence_store=fences)
    h.lock = ResourceLockManager(
        clock=lambda: h.clock[0], acquisition_id_factory=lambda: "effect-runtime-fixture"
    )
    coordinator = SafeguardLifecycleCoordinator(
        resource_lock=h.lock,
        reservation_store=reservations,
        audit_intent_store=InMemoryAuditIntentStore(),
        fence_store=fences,
        evidence_store=h.dispatches,
        closure_store=h.closures,
        denial_audit_store=h.store,
        commitment_store=ProcessRuntimeSafeguardCommitmentStore(h.processes),
        continuity_policy=EffectSinkContinuityPolicy.create(
            sink_id="effect-runtime-fixture",
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
        clock=lambda: h.clock[0],
    )
    h.executor, h.orchestrator, h.binder = coordinator, orchestrator, binder
    await _execute_publication(h)
    h.pantheon = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    monkeypatch.setattr(
        module, "PostgresSafeguardDispatchEvidenceStore", lambda **kwargs: h.dispatches
    )
    monkeypatch.setattr(module, "PostgresPostReleaseClosureStore", lambda **kwargs: h.closures)
    monkeypatch.setattr(module, "PostgresAdvisoryResourceLock", lambda **kwargs: h.lock)
    h.environment = _environment()
    h.factory = {**_options(h, h.environment), "publish": h.pantheon.publish}
    h.runtime = bind_alert_effect_runtime(**h.factory)
    assert h.runtime is not None
    return h


async def _execute_publication(h):
    """Retain only a real coordinator result and actual recorder output in unit stores."""
    restore = h.action.action_type == RESTORE_ACTION
    receipt = PublishReceipt(pr_ref="pr:restore-example" if restore else "pr:example")
    h.port = _FixturePublication(receipt)
    safety = evaluate_pre_dispatch(
        h.action,
        execution_path=ExecutionPath.PR_MANUAL,
        plan_digest=digest_record(h.plan),
        plan_kind="alert_noise_manual_pr",
    )
    assert isinstance(safety, SafeguardReceipt)
    result = await h.executor.dispatch(
        action=h.action,
        safeguard_receipt=safety,
        dispatch_port=h.port,
        correlation_id=h.inputs["correlation_id"],
    )
    assert result.lifecycle is not None and result.lifecycle.evidence_record is not None
    h.clock[0] += timedelta(seconds=1)
    await StateStoreAlertPublicationRecorder(
        store=h.store, processes=h.processes, clock=lambda: h.clock[0]
    ).record(action=h.action, plan=h.plan, receipt=receipt, result=result)
    execution = await read_alert_execution(h.store, full_action_digest(h.action))
    assert execution is not None and execution.source_event.state == "effect_observing"
    proof = result.lifecycle.evidence_record
    assert proof.dispatch_start_checkpoint is not None and h.action.workflow_action is not None
    h.context = AlertEffectContext(
        execution,
        proof.dispatch_start_checkpoint.dispatch_started_at,
        proof.bundle.bundle_digest,
        ALERT_RECOVERY_EFFECT_PURPOSE if restore else ALERT_EFFECT_PURPOSE,
        await h.processes.events(h.action.workflow_action.process_id),
    )
    h.key = alert_effect_key(plan_digest=digest_record(h.plan), dispatch_ref=execution.dispatch_ref)


async def _independent(h, *, receipt_changes=None, **changes):
    observation = _fixture_observation(h.context, **changes)
    h.clock[0] = observation.recorded_at
    payload = dict(
        observation=observation.model_dump(mode="json"),
        action_digest=full_action_digest(h.action),
        dispatch_ref=h.context.execution.dispatch_ref,
        dispatched_at=h.context.dispatched_at.isoformat(),
        safeguard_bundle_digest=h.context.safeguard_bundle_digest,
    )
    await _install_record(
        h,
        key=h.key,
        payload=payload,
        purpose=h.context.purpose,
        receipt_changes={
            "source_identity": "principal:effect-source",
            "event_at": observation.window_end,
            **(receipt_changes or {}),
        },
    )


async def _signal(h):
    assert await h.runtime.tick() == 1
    notice = h.pantheon.messages_on("object.action-run")[-1].payload
    assert await h.runtime.observe(notice)
    return h.pantheon.messages_on("object.drift")[-1].payload


async def _admit_workflow(h, signal):
    record = await h.store.find_state(
        "workflow:outcome:", field="receipt_ref", value=signal["workflow_outcome_ref"]
    )
    assert record is not None
    await _retain_admission(
        h,
        evidence_digest=workflow_outcome_evidence_digest(record),
        scope_digest=workflow_outcome_scope_digest(record),
        purpose_id=WORKFLOW_OUTCOME_EVIDENCE_PURPOSE,
        source_revision=record["receipt_ref"],
    )


async def test_missing_proof_is_quiet_then_unknown_with_real_per_target_holds(effects_runtime):
    h = effects_runtime
    before = await h.processes.get(h.action.workflow_action.process_id)
    audits = h.store.audit_entries
    for _ in range(3):
        assert await h.runtime.tick() == 0
    assert h.pantheon.published == [] and h.store.audit_entries == audits
    h.clock[0] = alert_effect_deadline(h.context)
    signal = await _signal(h)
    journal = await h.store.read_state(signal["outcome_ref"])
    assert journal["evidence_status"] == "unknown" and journal["receipt_digest"] is None
    assert journal["response_outcome"] is None and signal["workflow_outcome_ref"] is None
    result = await h.runtime.plan(signal)
    assert result["recovery_required"] is True and result["status"] == "recovery_required"
    for ref in h.plan.lock_refs:
        assert await h.runtime._holds.is_held(target_ref=ref)
    assert len(await h.store.read_states("workflow:automation-hold:", limit=256)) == len(
        h.plan.lock_refs
    )
    assert await h.processes.get(before.process_id) == before and h.port.calls == 1
    children = [
        row
        for row in await h.processes.events(before.process_id)
        if row.kind is ProcessEventKind.EVIDENCE_ATTACHED
        and row.payload.get("actor_agent") == "Forseti"
    ]
    assert len(children) == 1 and children[0].payload["recovery_required"] is True


@pytest.mark.parametrize(
    "changes", [{"eligible_events": 0}, {"coverage": "partial"}, {"coverage": "unavailable"}]
)
async def test_partial_or_unscorable_is_not_zero_or_success(effects_runtime, changes):
    h = effects_runtime
    await _independent(h, **changes)
    if "coverage" in changes:
        assert await h.runtime.tick() == 1
        assert not await h.runtime.observe(h.pantheon.messages_on("object.action-run")[-1].payload)
        assert not h.pantheon.messages_on("object.drift")
        h.clock[0] = alert_effect_deadline(h.context)
    signal = await _signal(h)
    journal = await h.store.read_state(signal["outcome_ref"])
    assert (
        journal["response_outcome"] is None or journal["response_outcome"]["observed_value"] is None
    )
    assert signal["effect_outcome"] in {"unscorable", "recovery_required"}
    assert (await h.runtime.plan(signal))["recovery_required"] is True
    assert await h.store.read_states("workflow:outcome:", limit=10) == ()


async def test_verified_resumes_actual_workflow_only_after_exact_journal_and_own_admission(
    effects_runtime, monkeypatch
):
    h = effects_runtime
    await _independent(h)
    signal = await _signal(h)
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    assert (await h.runtime.plan(signal))["status"] == "held"
    resume.assert_not_awaited()
    await _admit_workflow(h, signal)
    journal = await h.store.read_state(signal["outcome_ref"])
    await h.store.write_state(
        signal["outcome_ref"], {**journal, "receipt_digest": "sha256:" + "0" * 64}
    )
    assert (await h.runtime.plan(signal))["status"] == "held"
    resume.assert_not_awaited()
    await h.store.write_state(signal["outcome_ref"], journal)
    result = await h.runtime.plan(signal)
    resume.assert_awaited_once_with(process_id=signal["process_id"])
    assert result["process_status"] == "succeeded"
    assert (await h.processes.get(signal["process_id"])).status is ProcessStatus.SUCCEEDED
    restarted = bind_alert_effect_runtime(**h.factory)
    assert (await restarted.plan(signal))["status"] == "already_terminal"
    assert resume.await_count == 1 and h.port.calls == 1
    h.clock[0] = alert_effect_deadline(h.context)
    # Deadline passage cannot turn accepted evidence into missing proof.
    assert await restarted.tick() == 0
    read = h.store.read_state

    async def retired_effect(key):
        return None if key == h.key else await read(key)

    monkeypatch.setattr(h.store, "read_state", retired_effect)
    assert await restarted.tick() == 0
    assert await restarted.observe(h.pantheon.messages_on("object.action-run")[-1].payload)
    assert await h.store.read_states("workflow:automation-hold:", limit=10) == ()


async def test_recovered_resumes_real_compensation_without_dispatch_or_hold_release(
    effects_runtime, monkeypatch
):
    h = effects_runtime
    await _independent(h)
    forward = await _signal(h)
    await _admit_workflow(h, forward)
    cancelled = await h.orchestrator.cancel(
        process_id=forward["process_id"],
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
    resolved = await h.coordinator.resolve(process_id=forward["process_id"])
    assert (
        event.payload["operator_request"]["initiator_principal"]
        == resolved.binding.requester_principal
    )
    assert proposed.target_resource_ref == resolved.binding.target_resource_id
    assert event.correlation_id == resolved.binding.correlation_id
    assert proposed.params == {"plan_digest": resolved.binding.plan_digest[7:]}
    assert proposed.rollback_ref.reference in {None, resolved.plan.rollback_ref}
    bound = await h.binder.bind(proposed, event)
    h.action = Action.model_validate(
        {
            **bound.model_dump(mode="python"),
            "mode": Mode.ENFORCE,
            "executor_identity_ref": "executor:example",
        }
    )
    await _execute_publication(h)
    await _independent(h)
    signal = await _signal(h)
    assert signal["effect_outcome"] == "recovered"
    await _admit_workflow(h, signal)
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    result = await h.runtime.plan(signal)
    assert result["process_status"] == "compensated" and h.port.calls == 1
    resume.assert_awaited_once_with(process_id=signal["process_id"])
    assert await h.store.read_states("workflow:automation-hold-release-intent:", limit=10) == ()


async def test_positive_evidence_cannot_release_an_active_hold(effects_runtime, monkeypatch):
    h = effects_runtime
    await _independent(h)
    signal = await _signal(h)
    await _admit_workflow(h, signal)
    await h.runtime._holds.issue(
        target_ref=signal["resource_id"],
        process_id=signal["process_id"],
        reason="unit-only unresolved recovery",
    )
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    assert (await h.runtime.plan(signal))["recovery_required"] is True
    assert await h.runtime._holds.is_held(target_ref=signal["resource_id"])
    resume.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"producer_principal": "Thor"},
        {"signature": "test-only-signature"},
        {"schema_version": True},
        {"envelope_schema_version": 2},
        {"process_id": "process:other"},
        {"resource_id": "rule:other"},
        {"correlation_id": "correlation:other"},
        {"workflow_outcome_ref": "workflow-outcome:other"},
        {"outcome_ref": "alert-noise:outcome:sha256:" + "0" * 64},
    ],
)
async def test_forged_reference_or_signature_never_grants_producer_or_success(
    effects_runtime, monkeypatch, change
):
    h = effects_runtime
    await _independent(h)
    signal = await _signal(h)
    await _admit_workflow(h, signal)
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    assert (await h.runtime.plan({**signal, **change}))["status"] == "held"
    resume.assert_not_awaited()
    await h.pantheon.publish("Heimdall", "object.drift", {**signal, "producer_principal": "Thor"})
    assert h.pantheon.messages_on("object.drift")[-1].payload["producer_principal"] == "Heimdall"


@pytest.mark.parametrize(
    "changes", [{"scope_digest": "sha256:" + "0" * 64}, {"source_identity": "principal:other"}]
)
async def test_wrong_scope_or_source_receipt_is_not_a_wakeup_proof(effects_runtime, changes):
    h = effects_runtime
    await _independent(h, receipt_changes=changes)
    assert await h.runtime.tick() == 0 and h.pantheon.published == []
    h.clock[0] = alert_effect_deadline(h.context)
    signal = await _signal(h)
    assert signal["effect_outcome"] == "recovery_required"


async def test_duplicate_and_restart_keep_original_notice_and_missing_journal(
    effects_runtime, monkeypatch
):
    h = effects_runtime
    h.clock[0] = alert_effect_deadline(h.context)
    signal = await _signal(h)
    await h.runtime.plan(signal)
    before = h.store.audit_entries
    restarted = bind_alert_effect_runtime(**h.factory)
    issue = AsyncMock(
        side_effect=AssertionError("an old outcome must never reissue a released hold")
    )
    monkeypatch.setattr(type(restarted._holds), "issue", issue)
    assert await restarted.tick() == 0
    notice = h.pantheon.messages_on("object.action-run")[-1].payload
    h.clock[0] += timedelta(seconds=1)
    assert await restarted.observe(notice)
    replay = h.pantheon.messages_on("object.drift")[-1].payload
    assert replay == signal
    await restarted.plan(replay)
    issue.assert_not_awaited()
    assert h.store.audit_entries == before and h.port.calls == 1


async def test_final_notice_retries_until_canonical_consumer_evidence_exists(effects_runtime):
    h = effects_runtime
    h.clock[0] = alert_effect_deadline(h.context)
    assert await h.runtime.tick() == 1
    assert await bind_alert_effect_runtime(**h.factory).tick() == 1
    first, second = h.pantheon.messages_on("object.action-run")
    assert first.payload == second.payload
    signal = await _signal(h)
    assert (await h.runtime.plan(signal))["recovery_required"] is True
    assert await bind_alert_effect_runtime(**h.factory).tick() == 0


async def test_restart_cursor_passes_newest_hundred_without_provider_calls(
    effects_runtime, monkeypatch
):
    h = effects_runtime
    h.clock[0] = alert_effect_deadline(h.context)
    for index in range(100):
        await h.store.write_state(
            f"alert-noise:executed-action:malformed-{index}", {"test_only": "invalid"}
        )
    page = AsyncMock(wraps=h.store.read_state_page)
    monkeypatch.setattr(h.store, "read_state_page", page)
    admission = AsyncMock(
        side_effect=AssertionError("the tick must not call the admission provider")
    )
    monkeypatch.setattr(h.admissions, "admit", admission)
    assert await h.runtime.tick() == 0
    restarted = bind_alert_effect_runtime(**h.factory)
    assert await restarted.tick() == 1
    assert [call.kwargs["offset"] for call in page.await_args_list] == [0, 100]
    assert all(call.kwargs["limit"] == 100 for call in page.await_args_list)
    admission.assert_not_awaited()
    assert h.pantheon.messages_on("object.action-run")[0].payload[
        "action_digest"
    ] == full_action_digest(h.action)


async def test_publish_ack_loss_replays_at_least_once_with_same_identity(
    effects_runtime, monkeypatch
):
    h = effects_runtime
    h.clock[0] = alert_effect_deadline(h.context)
    write = h.store.write_state_if_absent

    async def unavailable(key, value):
        if key.startswith("alert-noise:effect-published:"):
            raise OSError("test-only checkpoint interruption")
        return await write(key, value)

    monkeypatch.setattr(h.store, "write_state_if_absent", unavailable)
    await h.runtime.tick()
    monkeypatch.setattr(h.store, "write_state_if_absent", write)
    assert await bind_alert_effect_runtime(**h.factory).tick() == 1
    messages = h.pantheon.messages_on("object.action-run")
    assert len(messages) == 2 and messages[0].payload == messages[1].payload and h.port.calls == 1


async def test_lost_configuration_withdraws_existing_callbacks(effects_runtime, monkeypatch):
    h = effects_runtime
    await _independent(h)
    signal = await _signal(h)
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    del h.environment[SOURCE_REVISION_ENV]
    with pytest.raises(AlertExecutionHeld, match="configuration_changed"):
        await h.runtime.tick()
    assert (await h.runtime.plan(signal))["status"] == "held"
    assert not await h.runtime.observe(h.pantheon.messages_on("object.action-run")[-1].payload)
    resume.assert_not_awaited()


async def test_process_replacement_during_admission_cannot_resume(effects_runtime, monkeypatch):
    h = effects_runtime
    await _independent(h)
    signal = await _signal(h)
    await _admit_workflow(h, signal)
    resolve = h.runtime._outcomes.resolve
    get = h.processes.get

    async def changed(**kwargs):
        result = await resolve(**kwargs)
        monkeypatch.setattr(h.processes, "get", AsyncMock(return_value=None))
        return result

    monkeypatch.setattr(
        type(h.runtime._outcomes), "resolve", lambda self, **kwargs: changed(**kwargs)
    )
    resume = AsyncMock(wraps=h.coordinator.resume)
    monkeypatch.setattr(h.coordinator, "resume", resume)
    assert (await h.runtime.plan(signal))["status"] == "held"
    resume.assert_not_awaited()
    monkeypatch.setattr(h.processes, "get", get)

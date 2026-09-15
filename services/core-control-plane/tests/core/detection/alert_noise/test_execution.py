"""No-network mechanics with the real coordinator and explicit test-only authority proofs.

The production-shaped authority records below are simulated unit inputs, not live evidence.
No fixture verifier, writer fence, catalog reference or source reader is a production binding.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.core.detection.alert_noise.execution import (
    ALERT_ACTIONS,
    AlertActionExecution,
    alert_execution_key,
    alert_publication_digest,
)
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.executor.executor import ExecutionResult, ExecutorOutcome
from fdai.core.workflow.safeguard_commitment import ProcessRuntimeSafeguardCommitmentStore
from fdai.delivery.alert_noise_iac import AlertIaCBinding, render_alert_iac
from fdai.delivery.alert_noise_pr import (
    AlertManualPrDispatcher,
    StateStoreAlertPatchReader,
    StateStoreAlertPlanReader,
)
from fdai.shared.contracts.models import (
    ExecutionPath,
    Mode,
    OntologyDeclarationKind,
    OntologyTypeRef,
    Operation,
    RollbackKind,
    RollbackRef,
    WorkflowActionRef,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr
from fdai.shared.providers.testing import InMemoryStateStore, RecordingRemediationPrPublisher
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    NoisePolicy,
    ProcessingRule,
    digest_record,
)
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertDispatchEvidence,
    AlertTreatment,
)
from tests.core.executor.test_executor import _action, _rule
from tests.core.executor.test_safeguard_lifecycle_coordinator import (
    _AdvancingEmptyHoldReader,
    _coordinator,
)


class _FixtureFence:
    """Test-only scope lease: a refusal can be inserted at either proof-resolution call."""

    def __init__(self) -> None:
        self.held, self.calls, self.fail_on = False, 0, 0
        self.revoked = False
        self.targets: tuple[str, ...] = ()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, **kwargs: Any) -> AsyncIterator[_FixtureFence]:
        async with self._lock:
            self.targets, self.held = kwargs["plan"].lock_refs, True
            try:
                yield self
            finally:
                self.held = False

    async def require_current(self, **kwargs: Any) -> None:
        assert self.held and kwargs["action"].target_resource_ref in self.targets
        self.calls += 1
        if self.calls == self.fail_on:
            raise PermissionError("test-only authority revocation")

    def require_active(self, *, now: datetime) -> None:
        if not self.held or self.revoked:
            raise PermissionError("test-only authority lease lost")


class _FixtureAuthority:
    """Simulate independent Var/risk observations without fabricating runtime bindings."""

    def __init__(self, evidence: AlertDispatchEvidence, decisions: tuple[AlertApproval, ...]):
        self.evidence, self.decisions, self.calls = evidence, decisions, 0

    async def dispatch_evidence(self, plan: Any) -> AlertDispatchEvidence:
        self.calls += 1
        return self.evidence

    async def approvals(self, plan: Any) -> tuple[AlertApproval, ...]:
        return self.decisions


class _FixtureSource:
    """One explicit existing repository file; optional hook simulates a boundary race."""

    def __init__(self, content: str) -> None:
        self.content: str | None = content
        self.paths: list[str] = []
        self.hook: Any = None

    async def read(self, *, path: str) -> str | None:
        self.paths.append(path)
        if self.hook is not None:
            self.hook()
        return self.content


class _FixturePublisher(RecordingRemediationPrPublisher):
    """Fail if the real call site loses its lease, bundle or preceding audit intent."""

    def __init__(self, fence: _FixtureFence, audit: InMemoryStateStore) -> None:
        super().__init__()
        self.fence, self.audit, self.calls = fence, audit, 0
        self.error: BaseException | None = None

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        assert self.fence.held and self.fence.calls >= 2
        assert pr.metadata["safeguard_bundle_digest"].startswith("sha256:")
        assert any(row["entry"].get("audit_phase") == "intent" for row in self.audit.audit_entries)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return await super().publish(pr)


@pytest.fixture
async def harness(now: datetime, evidence: AlertEvidence, request: pytest.FixtureRequest):
    """Compose real stores, renderer and workflow commitment; only authority/I/O are fakes."""
    clock = [now]
    # This simulates admitted evidence exclusively inside this no-network unit fixture.
    evidence = evidence.model_copy(
        update={"stamp": evidence.stamp.model_copy(update={"synthetic": False})}
    )
    kind = getattr(request, "param", "routing")
    treatment = AlertTreatment(
        kind="routing",
        target_ref="rule:example",
        remove_group_ref="group:old",
        replacement_group_ref="group:new",
    )
    target, field = evidence.rules[0].ref, "action"
    native_type, validation = "azurerm_monitor_metric_alert", None
    document = {"action": [{"action_group_id": "group:old"}], "description": "unchanged"}
    if kind == "suppression":
        target, field = "processing:example", "schedule"
        native_type = "azurerm_monitor_alert_processing_rule_suppression"
        processing = ProcessingRule(
            ref=target,
            revision="sha256:" + "e" * 64,
            rule_refs=("rule:example",),
            action="suppress",
            enabled=False,
            effective_from=now,
            effective_to=now + timedelta(hours=1),
            semantics_complete=True,
        )
        evidence = evidence.model_copy(update={"processing_rules": (processing,)})
        treatment = AlertTreatment(
            kind="suppression",
            target_ref="rule:example",
            processing_rule_ref=target,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        document = {"enabled": False, "schedule": [], "description": "unchanged"}
    elif kind == "evaluation":
        baseline = evidence.rules[0].evaluation
        assert baseline is not None
        field = "criteria.0.threshold"
        treatment = AlertTreatment(
            kind="evaluation",
            target_ref="rule:example",
            evaluation=baseline.model_copy(update={"threshold": 85.0}),
        )
        validation = EvaluationReceipt(
            rule_ref="rule:example",
            rule_revision=evidence.rules[0].revision,
            scenario_digest="sha256:" + "e" * 64,
            baseline=baseline,
            treatment=treatment.evaluation,
            evaluated_at=now,
            expires_at=now + timedelta(hours=1),
            baseline_true_positive=1,
            treatment_true_positive=1,
            baseline_false_positive=1,
            treatment_false_positive=0,
            baseline_false_negative=0,
            treatment_false_negative=0,
            accepted=True,
            reason="accepted",
        )
        document = {"criteria": [{"threshold": 80.0}], "description": "unchanged"}
    plan = plan_alert_change(
        evidence,
        treatment,
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
        evaluation_receipt=validation,
    )
    digest = digest_record(plan)
    rule = _rule().model_copy(
        update={"id": "alert.noise.governance", "remediates": plan.action_type}
    )
    registry = {
        name: OntologyTypeRef(
            kind=OntologyDeclarationKind.ACTION,
            name=name,
            version="1.0.0",
            catalog_digest="sha256:" + "b" * 64,
        )
        for name in ALERT_ACTIONS
    }
    action = _action(
        mode=Mode.ENFORCE,
        target=target,
        idempotency_key=alert_execution_key(plan.action_type, digest),
        citing_rules=(rule.id,),
        params={"plan_digest": digest[7:]},
    ).model_copy(
        update={
            "action_type": plan.action_type,
            "action_type_ref": registry[plan.action_type],
            "operation": Operation.UPDATE,
            "executor_identity_ref": "person:executor",
            "rollback_ref": RollbackRef(kind=RollbackKind.PR_REVERT, reference=plan.rollback_ref),
            "workflow_action": WorkflowActionRef(
                process_id="process:alert", step_id="apply", proposal_ref="proposal:alert"
            ),
            "created_at": now,
        }
    )
    source_text = json.dumps({"resource": {native_type: {"example": document}}}) + "\n"
    binding = AlertIaCBinding(
        path="infra/example.tf.json",
        source_digest="sha256:" + hashlib.sha256(source_text.encode()).hexdigest(),
        resource_type=native_type,
        resource_name="example",
        field=field,
        group_ids={"group:old": "group:old", "group:new": "group:new"},
        target_ref=target,
    )
    patch = render_alert_iac(plan, evidence, binding=binding, source=source_text)
    store = InMemoryStateStore(linearization_clock=lambda: clock[0])
    await store.write_state("alert-noise:plan:" + digest, plan.model_dump(mode="json"))
    await store.write_state(
        "alert-noise:evidence:" + plan.evidence_digest, evidence.model_dump(mode="json")
    )
    await store.write_state("alert-noise:patch:" + digest, {**asdict(patch), "plan_digest": digest})
    processes = InMemoryProcessRuntimeStore()
    await processes.create(
        snapshot=ProcessSnapshot(
            process_id="process:alert",
            workflow_ref="alert",
            workflow_version="1",
            status=ProcessStatus.RUNNING,
            current_step="apply",
            target_resource_id=action.target_resource_ref,
            started_at=now,
            updated_at=now,
            correlation_id="correlation:alert",
        ),
        event=ProcessEvent(
            event_id="event:created",
            process_id="process:alert",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="process:alert:created",
            recorded_at=now,
            correlation_id="correlation:alert",
        ),
    )
    commitments = ProcessRuntimeSafeguardCommitmentStore(processes)
    coordinator, lock = _coordinator(store, commitment_store=commitments, clock=lambda: clock[0])
    fence, source = _FixtureFence(), _FixtureSource(source_text)
    publisher = _FixturePublisher(fence, store)
    delivery = AlertManualPrDispatcher(
        patches=StateStoreAlertPatchReader(store=store), publisher=publisher, source_reader=source
    )
    pr = await delivery.prepare(action=action, rule=rule, plan=plan)
    proof = AlertDispatchEvidence(
        plan_digest=digest,
        evidence_digest=plan.evidence_digest,
        policy_digest=plan.policy_digest,
        target_revision=plan.target_revision,
        evaluated_at=now,
        valid_until=now + timedelta(minutes=5),
        authorization_until=now + timedelta(hours=12),
        executor_ref="person:executor",
        dry_run_digest=alert_publication_digest(plan, pr),
        promotion_digest="sha256:" + "c" * 64,
        writer_fence_ref="fence:test",
        audit_intent_ref="audit:test",
        recovery_admission_ref="recovery:test",
        dependencies_current=True,
        actors_current=True,
        observer_ready=True,
        recovery_ready=True,
        kill_switch=False,
        mode="enforce",
    )
    decisions = tuple(
        AlertApproval(
            plan_digest=digest,
            principal_ref="person:" + lane,
            tenant_ref=plan.tenant_ref,
            scope_ref=plan.scope_ref,
            decision="approved",
            lane=lane,
            service_refs=plan.service_refs,
            decided_at=now,
            expires_at=now + timedelta(hours=12),
            receipt_ref="approval:" + lane,
            authority_revision="sha256:" + "d" * 64,
        )
        for lane in ("service_owner", "change_owner")
    )
    authority = _FixtureAuthority(proof, decisions)
    fallback = SimpleNamespace(
        execute=AsyncMock(
            return_value=ExecutionResult(
                action_id="fallback", outcome=ExecutorOutcome.REJECTED_MODE
            )
        )
    )
    options = dict(
        plans=StateStoreAlertPlanReader(store=store),
        delivery=delivery,
        authority=authority,
        fence=fence,
        coordinator=coordinator,
        audit_store=store,
        fallback=fallback,
        registered_actions=registry,
        clock=lambda: clock[0],
    )
    return SimpleNamespace(
        action=action,
        rule=rule,
        plan=plan,
        evidence=evidence,
        patch=patch,
        store=store,
        clock=clock,
        fence=fence,
        source=source,
        publisher=publisher,
        authority=authority,
        delivery=delivery,
        registry=registry,
        processes=processes,
        commitments=commitments,
        coordinator=coordinator,
        lock=lock,
        fallback=fallback,
        options=options,
        make=lambda **changes: AlertActionExecution(**{**options, **changes}),
    )


@pytest.mark.parametrize("harness", ["suppression", "evaluation"], indirect=True)
async def test_other_registered_forward_treatments_use_same_lifecycle(harness: SimpleNamespace):
    h = harness
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.PUBLISHED and result.safeguard_bundle_digest
    assert h.publisher.records[0].patch == h.patch.forward and h.fence.targets == h.plan.lock_refs


async def test_real_coordinator_publishes_only_manual_pr_evidence(harness: SimpleNamespace) -> None:
    h = harness
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.PUBLISHED
    assert result.safeguard_bundle_digest and result.audit_context["effect_verified"] is False
    pr = h.publisher.records[0]
    assert (pr.action_id, pr.idempotency_key, pr.rule_ids) == (
        h.action.action_id,
        h.action.idempotency_key,
        tuple(h.action.citing_rules),
    )
    assert pr.metadata["safeguard_bundle_digest"] == result.safeguard_bundle_digest
    assert pr.metadata["dry_run_receipt"].startswith("sha256:")
    assert "require-manual-merge" in pr.labels and h.authority.calls == 2
    assert h.fence.targets == h.plan.lock_refs and not h.fence.held
    assert any(
        event.kind is ProcessEventKind.ACTION_PRE_BUNDLE_COMMITTED
        for event in await h.processes.events("process:alert")
    )
    assert [row["entry"]["audit_phase"] for row in h.store.audit_entries] == ["intent", "terminal"]


async def test_shadow_never_reads_authority_or_publishes(harness: SimpleNamespace) -> None:
    h = harness
    result = await h.make().execute(
        action=h.action.model_copy(update={"mode": Mode.SHADOW}),
        rule=h.rule,
        execution_path=ExecutionPath.PR_MANUAL,
    )
    assert result.outcome is ExecutorOutcome.REJECTED_MODE and result.mode is Mode.SHADOW
    assert h.publisher.calls == h.authority.calls == h.fence.calls == 0 and h.source.paths == []
    assert len(h.store.audit_entries) == 1


async def test_restart_uses_shared_closure_not_an_adapter_cache(harness: SimpleNamespace) -> None:
    h = harness
    first = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    replay = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert replay.outcome is ExecutorOutcome.ALREADY_EXISTED and h.publisher.calls == 1
    assert replay.safeguard_bundle_digest == first.safeguard_bundle_digest


async def test_non_alert_delegates_unchanged_with_default_path(harness: SimpleNamespace) -> None:
    h = harness
    action, rule = _action(), _rule()
    result = await h.make().execute(action=action, rule=rule)
    h.fallback.execute.assert_awaited_once_with(
        action=action, rule=rule, execution_path=ExecutionPath.PR_NATIVE
    )
    assert result is h.fallback.execute.return_value and h.publisher.calls == 0


@pytest.mark.parametrize(
    "raw", [True, 1, "a" * 63, "A" * 64, "a" * 64 + "\n", "sha256:" + "a" * 64]
)
async def test_strict_catalog_digest_params(harness: SimpleNamespace, raw: object) -> None:
    h = harness
    result = await h.make().execute(
        action=h.action.model_copy(update={"params": {"plan_digest": raw}}),
        rule=h.rule,
        execution_path=ExecutionPath.PR_MANUAL,
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"target_resource_ref": "resource:other"},
        {"action_type_ref": None},
        {"workflow_action": None},
        {"executor_identity_ref": None},
        {"idempotency_key": "new-attempt"},
        {"operation": Operation.DELETE},
        {"params": {"plan_digest": "a" * 64, "actor": "Thor"}},
    ],
)
async def test_actual_action_bindings_are_required(harness: SimpleNamespace, changes: dict) -> None:
    h = harness
    result = await h.make().execute(
        action=h.action.model_copy(update=changes),
        rule=h.rule,
        execution_path=ExecutionPath.PR_MANUAL,
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


@pytest.mark.parametrize("missing", ["authority", "fence", "coordinator", "registered_actions"])
async def test_unbound_enforcement_holds(harness: SimpleNamespace, missing: str) -> None:
    h = harness
    result = await h.make(**{missing: {} if missing == "registered_actions" else None}).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("kill_switch", True),
        ("synthetic", True),
        ("mode", "shadow"),
        ("dependencies_current", False),
        ("actors_current", False),
        ("observer_ready", False),
        ("recovery_ready", False),
        ("promotion_digest", None),
        ("writer_fence_ref", None),
        ("audit_intent_ref", None),
        ("recovery_admission_ref", None),
        ("authorization_until", None),
        ("dry_run_digest", "sha256:" + "e" * 64),
        ("target_revision", "sha256:" + "e" * 64),
        ("executor_ref", "person:other"),
    ],
)
async def test_current_admission_cannot_be_inferred(
    harness: SimpleNamespace, field: str, value: Any
):
    h = harness
    h.authority.evidence = h.authority.evidence.model_copy(update={field: value})
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


@pytest.mark.parametrize("fail_on", [1, 2])
async def test_trusted_proof_resolution_runs_before_and_at_sink(
    harness: SimpleNamespace, fail_on: int
):
    h = harness
    h.fence.fail_on = fail_on
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert h.fence.calls == fail_on and not h.fence.held


async def test_revocation_after_intent_is_re_read(harness: SimpleNamespace) -> None:
    h = harness
    h.source.hook = lambda: setattr(h.authority, "decisions", ())
    result = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0
    assert h.authority.calls == 2 and result.safeguard_bundle_digest is not None


async def test_expiry_during_actual_coordinator_guard_proves_no_publication(
    harness: SimpleNamespace,
):
    h = harness
    reader = _AdvancingEmptyHoldReader(
        lambda: h.clock.__setitem__(0, h.clock[0] + timedelta(hours=1))
    )
    coordinator, _ = _coordinator(
        h.store, commitment_store=h.commitments, hold_state_reader=reader, clock=lambda: h.clock[0]
    )
    result = await h.make(coordinator=coordinator).execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT and h.publisher.calls == 0


async def test_unknown_publication_is_quarantined_without_resend(harness: SimpleNamespace) -> None:
    h = harness
    h.publisher.error = RuntimeError("private provider detail")
    first = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    replay = await h.make().execute(
        action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL
    )
    assert (
        first.outcome is ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN and first.safeguard_bundle_digest
    )
    assert replay.outcome not in {ExecutorOutcome.PUBLISHED, ExecutorOutcome.ALREADY_EXISTED}
    assert h.publisher.calls == 1 and "private provider detail" not in str(h.store.audit_entries)


async def test_cancellation_after_sink_keeps_unknown_and_propagates(
    harness: SimpleNamespace,
) -> None:
    h = harness
    h.publisher.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.make().execute(action=h.action, rule=h.rule, execution_path=ExecutionPath.PR_MANUAL)
    assert h.store.audit_entries[-1]["entry"]["outcome"] == "publish_outcome_unknown"
    assert h.publisher.calls == 1 and not h.fence.held

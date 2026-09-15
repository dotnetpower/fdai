"""Current catalog Action -> original HIL -> prepared case -> independent observed effect.

Provider/transport evidence is explicit synthetic test data. This proves owned
source coordination, not production promotion, a live Graph write or shared
safeguard conformance; the isolated service has separate owning tests.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import yaml
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.testing_safeguard_lifecycle import InMemoryTargetDispatchFenceStore
from fdai.core.human_assignment import AssignmentCaseService, AssignmentState
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.core.human_assignment.execution_material import (
    HumanAccessMaterialBuilder,
    HumanAccessMaterialStore,
)
from fdai.core.human_assignment.execution_recovery import HumanAccessRecoverySource
from fdai.core.human_assignment.execution_sources import (
    HumanAccessCaseSource,
    HumanAccessCurrentPublisher,
)
from fdai.core.rbac.roles import Role
from fdai.core.risk_gate.gate import ActionModeRecord, ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.identity.human_access_observer import IndependentHumanAccessObserver
from fdai.runtime.human_access_workflow import HumanAccessWorkflowRuntime
from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.shared.contracts.models import (
    Action,
    ExecutionPath,
    ExecutorEffectReceipt,
    Mode,
    OntologyActionType,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken
from fdai_service_contracts.human_access_workflow import HumanAccessWorkNotice
from tests.core.human_assignment.test_access_apply import _ownership_merged

ROOT = Path(__file__).resolve().parents[4]
AT = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
async def setup():
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    registry = ActionPromotionRegistry()
    name = "ops.apply-human-access"
    registry.restore(name, ActionModeRecord(name, Mode.ENFORCE))
    promotions = SimpleNamespace(refresh=AsyncMock(), mode_of=registry.mode_of)
    await store.write_state(
        "action_promotion:" + name, {"action_type": name, "mode": "enforce", "revision": 1}
    )
    types = {
        name: OntologyActionType.model_validate(
            yaml.safe_load(
                (ROOT / "rule-catalog/action-types/ops.assignment-role-grant.yaml").read_text()
            )
        )
    }
    clock = {"now": AT}

    def time():
        return clock["now"]

    groups = {Role.READER: "group:reader"}
    builder = HumanAccessMaterialBuilder(cases, HumanAccessMaterialStore(store), groups)
    source = HumanAccessCaseSource(cases, groups, promotions, time)
    owners = SimpleNamespace(is_current_owner=AsyncMock(return_value=True))
    approvals = HumanAccessApprovalService(
        store, owners, source.check, time, lambda _person, _action: True
    )
    sent = []

    async def dispatch(*, action, source_guard=None):
        if source_guard is not None:
            await source_guard()
        sent.append(action.model_dump(mode="json"))
        command = SafeguardBoundExecutorCommand.from_action(
            command_id=uuid4(),
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            attempt=1,
            issued_at=time(),
            deadline_at=time() + timedelta(seconds=120),
            safeguard_proof_bundle_digest="sha256:" + "a" * 64,
            source_revision="b" * 40,
        )
        correlation = BoundCommandCorrelation(
            command=command,
            registration_id=uuid4(),
            reservation_identity_digest="sha256:" + "c" * 64,
            evidence_identity_digest="sha256:" + "d" * 64,
            target_digest="sha256:" + "e" * 64,
            target_fence_generation=1,
        )
        await store.write_state(
            "runtime:isolated-executor:human-access:" + str(action.action_id),
            {"command_id": str(command.command_id), "action_digest": command.action_payload_digest},
        )
        await store.write_state(
            "runtime:isolated-executor:command:" + str(command.command_id),
            correlation.model_dump(mode="json"),
        )
        return SimpleNamespace(audit_context={"dispatch_status": "pending"})

    graph_requests = []
    present = {"membership": True}

    async def graph(request):
        graph_requests.append(request)
        if "/members/" in request.url.path:
            return (
                httpx.Response(200, json={"id": case.intent.subject.subject_id})
                if present["membership"]
                else httpx.Response(404)
            )
        return httpx.Response(
            200,
            json={
                "id": "group:reader"
                if "/groups/" in request.url.path
                else case.intent.subject.subject_id
            },
        )

    identity = SimpleNamespace(
        get_token=AsyncMock(
            return_value=IdentityToken(
                "synthetic-placeholder",
                AT + timedelta(hours=1),
                "https://graph.microsoft.com/.default",
            )
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(graph)) as client:
        runtime = HumanAccessWorkflowRuntime(
            builder,
            approvals,
            HumanAccessCurrentPublisher(source, approvals, time),
            ActionBuilder(types, clock=time),
            RiskGate(registry=registry),
            load_risk_table(ROOT / "rule-catalog/risk-classification.yaml"),
            SimpleNamespace(execute=dispatch),
            IndependentHumanAccessObserver(client, identity, "observer:independent-read", time),
            lambda: True,
            time,
            recovery=HumanAccessRecoverySource(builder, InMemoryTargetDispatchFenceStore()),
        )
        notice = HumanAccessWorkNotice(
            request_id=uuid4(),
            operation="request",
            case_id=case.case_id,
            expected_revision=case.revision,
            observed_at=AT,
            expires_at=AT + timedelta(minutes=5),
        )
        yield SimpleNamespace(
            runtime=runtime,
            case=case,
            notice=notice,
            clock=clock,
            owners=owners,
            sent=sent,
            graph_requests=graph_requests,
            present=present,
        )


async def reviewed(setup):
    f = setup
    proposed = await f.runtime.judge_request(f.notice)
    waiting = await f.runtime.review(proposed)
    assert waiting.stage == "awaiting_human"
    material = await f.runtime.builder.materials.read(str(proposed.action_id))
    approval = material.approval_ids[0]
    f.clock["now"] += timedelta(seconds=1)
    await f.runtime.store.write_state(
        "operator-hil-decision:" + approval,
        {
            "approval_id": approval,
            "idempotency_key": "human-access:" + approval,
            "approver_oid": "person:independent-owner",
            "decision": "approve",
            "decided_at": f.clock["now"].isoformat(),
            "receipt_ref": "operator:synthetic-decision",
        },
    )
    notice = HumanAccessWorkNotice.model_validate(
        {
            **f.notice.model_dump(),
            "operation": "decision",
            "action_id": material.action().action_id,
            "approval_id": approval,
        }
    )
    checked = await f.runtime.judge_decision(notice)
    return material, await f.runtime.review(checked)


async def dispatch_receipt(setup, material):
    store = setup.runtime.store
    link = await store.read_state(
        "runtime:isolated-executor:human-access:" + str(material.action().action_id)
    )
    correlation = BoundCommandCorrelation.model_validate(
        await store.read_state("runtime:isolated-executor:command:" + link["command_id"])
    )
    command = correlation.command
    receipt = ExecutorEffectReceipt(
        receipt_id=uuid4(),
        command_id=command.command_id,
        action_id=command.action_id,
        idempotency_key=command.idempotency_key,
        attempt=command.attempt,
        action_payload_digest=command.action_payload_digest,
        requested_mode=command.requested_mode,
        status="dispatched",
        executor_instance_id="executor:synthetic",
        received_at=setup.clock["now"],
        completed_at=setup.clock["now"],
        effect_applied=True,
        provider_receipt_ref="human-access-dispatch:synthetic",
        safeguard_proof_bundle_digest=command.safeguard_proof_bundle_digest,
        audit_ref="action:" + str(command.action_id),
    )
    await store.write_state(
        "runtime:isolated-executor:terminal-receipt:" + str(command.command_id),
        receipt.model_dump(mode="json"),
    )


async def test_original_action_and_human_decision_are_preserved_until_independent_effect(setup):
    f = setup
    material, approved = await reviewed(f)
    assert not f.sent and not f.graph_requests
    prepared = await f.runtime.prepare(approved)
    ready = await f.runtime.review(prepared)
    pending = await f.runtime.dispatch(ready)
    assert pending.stage == "dispatch_pending"
    assert f.sent == [material.action().model_dump(mode="json")]
    assert (
        await f.runtime.builder.cases.get_case(f.case.case_id)
    ).state is AssignmentState.IAM_APPLYING
    with pytest.raises(ValueError):
        await f.runtime.observe(pending)
    assert not f.graph_requests
    await dispatch_receipt(f, material)
    observed = await f.runtime.observe(pending)
    assert all(request.method == "GET" for request in f.graph_requests)
    checked = await f.runtime.judge_effect(observed)
    with pytest.raises(ValueError, match="post-release reconciliation"):
        await f.runtime.record_effect(checked)
    assert (
        await f.runtime.builder.cases.get_case(f.case.case_id)
    ).state is AssignmentState.IAM_APPLYING


async def test_lost_owner_before_dispatch_leaves_prepared_case_without_any_effect(setup):
    f = setup
    _, approved = await reviewed(f)
    prepared = await f.runtime.prepare(approved)
    ready = await f.runtime.review(prepared)
    f.owners.is_current_owner.return_value = False
    with pytest.raises(PermissionError):
        await f.runtime.dispatch(ready)
    assert not f.sent and not f.graph_requests


async def test_contrary_membership_does_not_activate_case_or_request_inverse(setup):
    f = setup
    material, approved = await reviewed(f)
    pending = await f.runtime.dispatch(await f.runtime.review(await f.runtime.prepare(approved)))
    await dispatch_receipt(f, material)
    f.present["membership"] = False
    observed = await f.runtime.observe(pending)
    assert (await f.runtime.judge_effect(observed)).stage == "effect_mismatch"
    with pytest.raises(ValueError, match="post-release reconciliation"):
        await f.runtime.record_failure(observed)
    assert (
        await f.runtime.builder.cases.get_case(f.case.case_id)
    ).state is AssignmentState.IAM_APPLYING
    assert len(f.sent) == 1


async def test_actual_shared_safeguards_publish_original_action_and_keep_receipt_pending(setup):
    from dataclasses import replace

    from fdai.delivery.human_access_closure import (
        HumanAccessClosureReconciler,
        HumanAccessClosureStore,
    )
    from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
    from fdai.runtime.safeguard_isolated_executor import (
        SafeguardBoundEventBusDirectApiExecutionClient,
    )
    from fdai.shared.providers.testing.event_bus import InMemoryEventBus
    from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator
    from tests.runtime.test_isolated_executor_receipt_journal import _bind_journal, _command

    f = setup
    f.clock["now"] = AT + timedelta(minutes=1)
    f.notice = HumanAccessWorkNotice.model_validate(
        {
            **f.notice.model_dump(),
            "observed_at": f.clock["now"],
            "expires_at": f.clock["now"] + timedelta(minutes=5),
        }
    )
    bus = InMemoryEventBus()
    coordinator, lock = _coordinator(f.runtime.store, clock=lambda: f.clock["now"])
    closures = HumanAccessClosureStore(coordinator._closure._closure_store, f.runtime.store)
    coordinator._closure._closure_store = closures
    client = EventBusDirectApiExecutionClient(bus, f.runtime.store, "core:human-test")
    _bind_journal(client, coordinator._closure._closure_store)
    f.runtime = replace(
        f.runtime,
        dispatch_port=SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator),
        closure=HumanAccessClosureReconciler(
            closures, f.runtime.store, lambda: f.clock["now"], f.runtime.observer.identity_ref
        ),
    )
    try:
        material, approval = await reviewed(f)
        pending = await f.runtime.dispatch(
            await f.runtime.review(await f.runtime.prepare(approval))
        )
        assert pending.stage == "dispatch_pending"
        command = await _command(bus)
        assert Action.model_validate(command.action_payload).model_dump(
            mode="json"
        ) == material.action().model_dump(mode="json")
        assert not any(lock.snapshot().values())
        assert not f.graph_requests
        assert (
            await f.runtime.builder.cases.get_case(f.case.case_id)
        ).state is AssignmentState.IAM_APPLYING
        await dispatch_receipt(f, material)
        f.clock["now"] += timedelta(seconds=2)
        observed = await f.runtime.observe(pending)
        checked = await f.runtime.judge_effect(observed)
        assert (await f.runtime.record_effect(checked)).stage == "effect_recorded"
        assert (
            await f.runtime.builder.cases.get_case(f.case.case_id)
        ).state is AssignmentState.ACTIVE
        assert (await f.runtime.record_effect(checked)).stage == "effect_recorded"
    finally:
        await client.stop()


async def test_current_kill_or_degradation_after_review_prevents_publication(setup):
    f = setup
    _, approval = await reviewed(f)
    ready = await f.runtime.review(await f.runtime.prepare(approval))
    f.runtime = replace(f.runtime, safety_held=lambda: True)
    with pytest.raises(ValueError, match="risk policy"):
        await f.runtime.dispatch(ready)
    assert not f.sent


async def test_prepared_restart_reenters_original_review_without_renewal(setup):
    from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation

    f = setup
    material, approval = await reviewed(f)
    await f.runtime.prepare(approval)
    ingress = AsyncMock()
    worker = HumanAccessReconciliation(f.runtime, ingress)
    assert await worker.tick() == 1
    payload = ingress.await_args.args[0]
    notice = HumanAccessWorkNotice.model_validate(payload["payload"]["notice"])
    assert notice.operation == "resume"
    handoff = await f.runtime.resume(notice)
    prepared = await f.runtime.prepare(await f.runtime.review(handoff))
    assert prepared.stage == "prepared"
    assert (
        await f.runtime.builder.materials.read(str(material.action().action_id))
    ).expires_at == material.expires_at
    assert not f.sent


async def test_notice_cannot_substitute_another_request_correlation(setup):
    f = setup
    material, _ = await reviewed(f)
    notice = HumanAccessWorkNotice.model_validate(
        {
            **f.notice.model_dump(),
            "operation": "resume",
            "action_id": material.action().action_id,
            "request_id": uuid4(),
        }
    )
    with pytest.raises(ValueError, match="identity changed"):
        await f.runtime.resume(notice)


async def test_poison_material_does_not_starve_later_current_requests(setup):
    from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation

    f = setup
    await f.runtime.store.write_state(
        "human_assignment:execution-material:invalid", {"malformed": True}
    )
    worker = HumanAccessReconciliation(f.runtime, AsyncMock())
    assert await worker.tick() == 1


async def test_valid_material_with_poison_case_is_audited_without_stalling_page(setup):
    from fdai.runtime.human_access_reconciliation import HumanAccessReconciliation

    f = setup
    await f.runtime.judge_request(f.notice)
    await f.runtime.store.write_state(
        "human_assignment:case:" + f.case.case_id, {"malformed": True}
    )
    worker = HumanAccessReconciliation(f.runtime, AsyncMock())
    assert await worker.tick() == 0


async def test_independent_observer_rejects_a_token_for_another_audience(setup):
    f = setup
    material, approval = await reviewed(f)
    pending = await f.runtime.dispatch(await f.runtime.review(await f.runtime.prepare(approval)))
    await dispatch_receipt(f, material)
    f.runtime.observer.identity.get_token.return_value = IdentityToken(
        "synthetic-placeholder", f.clock["now"] + timedelta(minutes=5), "https://example.com"
    )
    with pytest.raises(ValueError, match="identity is expired"):
        await f.runtime.observe(pending)
    assert not f.graph_requests


async def test_shadow_material_cannot_be_promoted_by_replaying_the_old_notice(setup):
    f = setup
    action_type = "ops.apply-human-access"
    f.runtime.risk_gate._registry.demote(action_type)
    await f.runtime.store.write_state(
        "action_promotion:" + action_type,
        {"action_type": action_type, "mode": "shadow", "revision": 2},
    )
    proposed = await f.runtime.judge_request(f.notice)
    material = await f.runtime.builder.materials.read(str(proposed.action_id))
    assert material.action().mode.value == "shadow"
    f.runtime.risk_gate._registry.restore(action_type, ActionModeRecord(action_type, Mode.ENFORCE))
    await f.runtime.store.write_state(
        "action_promotion:" + action_type,
        {"action_type": action_type, "mode": "enforce", "revision": 3},
    )
    with pytest.raises(ValueError, match="MUST NOT be rewritten"):
        await f.runtime.judge_request(f.notice)
    assert not f.sent

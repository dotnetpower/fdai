"""HilResumeCoordinator - park / push / resolve round-trip + safety invariants.

Asserts the step-B contract from
[docs/roadmap/decisioning/execution-model.md](../../../docs/roadmap/decisioning/execution-model.md):

- ``request_approval`` parks the full Action and pushes an A1 card.
- ``resolve(APPROVE)`` re-dispatches the parked action to the executor.
- ``resolve(REJECT|TIMEOUT)`` never executes.
- resolve is idempotent; a conflicting re-decision is refused.
- self-approval is refused before any execution.
- an unknown / expired park is a fail-safe no-op.
- a push failure keeps the action parked (recoverable, never executed).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.executor import (
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.hil_resume import (
    HilResumeCoordinator,
    RequestOutcome,
    ResolveOutcome,
)
from fdai.core.oncall import OnCallResolver
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Mode,
    Operation,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.hil_channel import HilChannelError, HilDecision
from fdai.shared.providers.oncall_schedule import OnCallShift, StaticOnCallSchedule
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel

REPO_ROOT = Path(__file__).resolve().parents[3]
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"

_RULE_ID = "object-storage.owner-tag.required"
_SUBMITTER = "system:control-loop"
_APPROVER = "alice@example.com"


def _rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=_RULE_ID,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/object_storage/owner_tag_required.rego",
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates="remediate.tag-add",
        parameters={"tag_name": "owner", "tag_value": "unknown"},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _action(
    *,
    idempotency_key: str = "example-idem",
    target: str = "resource:example/rg/stg1",
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",  # type: ignore[arg-type]
        idempotency_key=idempotency_key,
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="remediate.tag-add",
        target_resource_ref=target,
        operation=Operation.TAG,
        params={"tag_value": "team-a"},
        stop_condition="target_already_tagged",
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=[_RULE_ID],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _coordinator(
    *, send_error: BaseException | None = None
) -> tuple[
    HilResumeCoordinator,
    RecordingRemediationPrPublisher,
    InMemoryStateStore,
    InMemoryHilChannel,
]:
    publisher = RecordingRemediationPrPublisher()
    store = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=store,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    channel = InMemoryHilChannel(send_error=send_error)
    coordinator = HilResumeCoordinator(
        state_store=store,
        executor=executor,
        hil_channel=channel,
        rules_by_id={_RULE_ID: _rule()},
    )
    return coordinator, publisher, store, channel


def _audit_kinds(store: InMemoryStateStore) -> list[str]:
    return [str(e["entry"].get("action_kind")) for e in store.audit_entries]


async def _park(
    coordinator: HilResumeCoordinator,
    *,
    approval_id: str,
    idempotency_key: str = "example-idem",
) -> None:
    await coordinator.request_approval(
        action=_action(idempotency_key=idempotency_key),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id=approval_id,
    )


_ROTATION = "sre-primary"


def _oncall_coordinator(
    *, schedule: StaticOnCallSchedule | None, rotation: str | None = _ROTATION
) -> tuple[HilResumeCoordinator, InMemoryStateStore]:
    publisher = RecordingRemediationPrPublisher()
    store = InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=store,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    coordinator = HilResumeCoordinator(
        state_store=store,
        executor=executor,
        hil_channel=InMemoryHilChannel(),
        rules_by_id={_RULE_ID: _rule()},
        on_call_resolver=OnCallResolver(schedule) if schedule is not None else None,
        on_call_rotation=rotation,
    )
    return coordinator, store


async def test_no_resolver_records_no_on_call() -> None:
    coordinator, _publisher, store, _channel = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-oc0",
    )
    parked = await store.read_state("hil_park:aid-oc0")
    assert parked is not None
    assert parked["on_call"] is None


async def test_live_shift_records_responder_on_park_and_audit() -> None:
    now = datetime.now(tz=UTC)
    schedule = StaticOnCallSchedule(
        [
            OnCallShift(
                rotation=_ROTATION,
                primary_oid="oid-primary",
                secondary_oid="oid-secondary",
                start=now - timedelta(hours=1),
                until=now + timedelta(hours=1),
            )
        ]
    )
    coordinator, store = _oncall_coordinator(schedule=schedule)
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-oc1",
    )
    parked = await store.read_state("hil_park:aid-oc1")
    assert parked is not None
    on_call = parked["on_call"]
    assert on_call["from_schedule"] is True
    assert on_call["primary_oid"] == "oid-primary"
    assert on_call["secondary_oid"] == "oid-secondary"
    assert on_call["fallback_reason"] is None
    audit = [
        e["entry"] for e in store.audit_entries if e["entry"].get("action_kind") == "hil.requested"
    ]
    assert audit[0]["on_call"]["primary_oid"] == "oid-primary"


async def test_no_coverage_records_fallback_reason() -> None:
    # An empty schedule -> no coverage -> fail-safe fallback, still parks.
    coordinator, store = _oncall_coordinator(schedule=StaticOnCallSchedule([]))
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-oc2",
    )
    parked = await store.read_state("hil_park:aid-oc2")
    assert parked is not None
    assert parked["on_call"]["from_schedule"] is False
    assert parked["on_call"]["fallback_reason"] == "no_coverage"


@pytest.mark.asyncio
async def test_request_approval_parks_and_pushes() -> None:
    coordinator, publisher, store, channel = _coordinator()
    result = await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-1",
        reasons=("Verifier requires operator review.",),
        blast_radius_summary="1 resource, 0 downstream",
        ttl_seconds=1200,
    )
    assert result.outcome is RequestOutcome.PARKED
    assert result.approval_id == "aid-1"
    parked = await store.read_state("hil_park:aid-1")
    assert parked is not None
    assert parked["status"] == "pending"
    assert parked["approval_context"]["reasons"] == ["Verifier requires operator review."]
    assert parked["approval_context"]["blast_radius_summary"] == "1 resource, 0 downstream"
    assert parked["approval_context"]["ttl_seconds"] == 1200
    assert parked["approval_context"]["expires_at"] > parked["parked_at"]
    assert len(channel.sent) == 1
    assert channel.sent[0].approval_id == "aid-1"
    assert "hil.requested" in _audit_kinds(store)
    requested = next(
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("action_kind") == "hil.requested"
    )
    assert requested["severity"] == "low"
    assert requested["category"] == "config_drift"
    # Parking alone NEVER executes.
    assert publisher.records == ()


@pytest.mark.asyncio
async def test_approve_resumes_and_executes() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-2")
    result = await coordinator.resolve(
        approval_id="aid-2",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )
    assert result.outcome is ResolveOutcome.EXECUTED
    # Re-dispatched to the executor -> exactly one shadow PR.
    assert len(publisher.records) == 1
    assert "hil.approved.executed" in _audit_kinds(store)
    parked = await store.read_state("hil_park:aid-2")
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == "approve"


@pytest.mark.asyncio
async def test_reject_records_no_execution() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-3")
    result = await coordinator.resolve(
        approval_id="aid-3",
        decision=HilDecision.REJECT,
        approver_oid=_APPROVER,
        reason="not during business hours",
    )
    assert result.outcome is ResolveOutcome.REJECTED
    assert publisher.records == ()
    assert "hil.rejected" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_timeout_no_execution() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-4")
    result = await coordinator.resolve(
        approval_id="aid-4",
        decision=HilDecision.TIMEOUT,
        approver_oid="system",
    )
    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert publisher.records == ()
    assert "hil.timeout" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_double_approve_is_idempotent() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-5")
    first = await coordinator.resolve(
        approval_id="aid-5", decision=HilDecision.APPROVE, approver_oid=_APPROVER
    )
    second = await coordinator.resolve(
        approval_id="aid-5", decision=HilDecision.APPROVE, approver_oid=_APPROVER
    )
    assert first.outcome is ResolveOutcome.EXECUTED
    assert second.outcome is ResolveOutcome.ALREADY_RESOLVED
    # Re-execution NEVER happens: still exactly one PR.
    assert len(publisher.records) == 1


@pytest.mark.asyncio
async def test_conflicting_decision_is_refused() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-6")
    await coordinator.resolve(
        approval_id="aid-6", decision=HilDecision.APPROVE, approver_oid=_APPROVER
    )
    conflict = await coordinator.resolve(
        approval_id="aid-6", decision=HilDecision.REJECT, approver_oid=_APPROVER
    )
    assert conflict.outcome is ResolveOutcome.CONFLICTING_DECISION
    assert len(publisher.records) == 1


@pytest.mark.asyncio
async def test_self_approval_is_refused() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-7")
    result = await coordinator.resolve(
        approval_id="aid-7",
        decision=HilDecision.APPROVE,
        approver_oid=_SUBMITTER,  # same principal that parked it
    )
    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert publisher.records == ()
    assert "hil.resolve.self_approval_refused" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_request_approval_rejects_blank_submitter() -> None:
    # A blank submitter would make the resolve-time no-self-approval check
    # unverifiable - refuse to park (fail closed).
    coordinator, _publisher, _store, _ = _coordinator()
    with pytest.raises(ValueError, match="submitter_oid MUST be non-empty"):
        await coordinator.request_approval(
            action=_action(),
            rule=_rule(),
            submitter_oid="   ",
            correlation_id="c1",
            approval_id="aid-blank-sub",
        )


@pytest.mark.asyncio
async def test_resolve_refuses_blank_approver() -> None:
    # An APPROVE with no verifiable approver identity MUST NOT execute -
    # we cannot prove it is a distinct principal from the submitter.
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-blank-appr")
    result = await coordinator.resolve(
        approval_id="aid-blank-appr",
        decision=HilDecision.APPROVE,
        approver_oid="   ",
    )
    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert publisher.records == ()
    assert "hil.resolve.self_approval_refused" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_unknown_park_is_not_found() -> None:
    coordinator, publisher, store, _ = _coordinator()
    result = await coordinator.resolve(
        approval_id="does-not-exist",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )
    assert result.outcome is ResolveOutcome.NOT_FOUND
    assert publisher.records == ()


@pytest.mark.asyncio
async def test_dispatch_failure_keeps_action_parked() -> None:
    coordinator, publisher, store, _ = _coordinator(
        send_error=HilChannelError("channel down", approval_id="aid-9")
    )
    result = await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-9",
    )
    assert result.outcome is RequestOutcome.PARKED_DISPATCH_FAILED
    # Still parked and recoverable; never auto-executed.
    parked = await store.read_state("hil_park:aid-9")
    assert parked is not None
    assert parked["status"] == "pending"
    assert publisher.records == ()
    assert "hil.request.dispatch_failed" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_parked_action_roundtrips_through_serialization() -> None:
    coordinator, _, store, _ = _coordinator()
    action = _action(idempotency_key="rt-1")
    await coordinator.request_approval(
        action=action,
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-rt",
    )
    parked = await store.read_state("hil_park:aid-rt")
    assert parked is not None
    restored = Action.model_validate(parked["action"])
    assert restored.idempotency_key == action.idempotency_key
    assert restored.action_type == action.action_type
    assert restored.citing_rules == action.citing_rules
    assert restored.target_resource_ref == action.target_resource_ref


# ---------------------------------------------------------------------------
# Delegation gate (Scenario A) - role-scoped HIL queue + delegated approval
# ---------------------------------------------------------------------------

_ASSIGNEE = "bob@example.com"


@pytest.mark.asyncio
async def test_park_records_explicit_assignee_oid() -> None:
    coordinator, _publisher, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-asg1",
        assignee_oid=_ASSIGNEE,
    )
    parked = await store.read_state("hil_park:aid-asg1")
    assert parked is not None
    assert parked["assignee_oid"] == _ASSIGNEE


@pytest.mark.asyncio
async def test_park_defaults_assignee_to_on_call_primary() -> None:
    now = datetime.now(tz=UTC)
    schedule = StaticOnCallSchedule(
        [
            OnCallShift(
                rotation=_ROTATION,
                primary_oid="oid-primary",
                secondary_oid="oid-secondary",
                start=now - timedelta(hours=1),
                until=now + timedelta(hours=1),
            )
        ]
    )
    coordinator, store = _oncall_coordinator(schedule=schedule)
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-asg2",
    )
    parked = await store.read_state("hil_park:aid-asg2")
    assert parked is not None
    # No explicit assignee -> the surfaced on-call primary becomes the assignee.
    assert parked["assignee_oid"] == "oid-primary"


@pytest.mark.asyncio
async def test_explicit_assignee_overrides_on_call_primary() -> None:
    now = datetime.now(tz=UTC)
    schedule = StaticOnCallSchedule(
        [
            OnCallShift(
                rotation=_ROTATION,
                primary_oid="oid-primary",
                secondary_oid="oid-secondary",
                start=now - timedelta(hours=1),
                until=now + timedelta(hours=1),
            )
        ]
    )
    coordinator, store = _oncall_coordinator(schedule=schedule)
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-asg3",
        assignee_oid=_ASSIGNEE,
    )
    parked = await store.read_state("hil_park:aid-asg3")
    assert parked is not None
    assert parked["assignee_oid"] == _ASSIGNEE


@pytest.mark.asyncio
async def test_direct_approval_by_assignee_is_not_delegated() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-dir",
        assignee_oid=_ASSIGNEE,
    )
    result = await coordinator.resolve(
        approval_id="aid-dir",
        decision=HilDecision.APPROVE,
        approver_oid=_ASSIGNEE,  # the assignee resolves their own item
    )
    assert result.outcome is ResolveOutcome.EXECUTED
    assert result.delegated is False
    assert result.assignee_oid == _ASSIGNEE
    assert len(publisher.records) == 1
    executed = [
        e["entry"]
        for e in store.audit_entries
        if e["entry"].get("action_kind") == "hil.approved.executed"
    ]
    assert executed[0]["delegated"] is False
    assert executed[0]["delegation_mode"] == "direct"
    assert executed[0]["assignee_oid"] == _ASSIGNEE


@pytest.mark.asyncio
async def test_delegated_approval_is_allowed_and_recorded() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-del",
        assignee_oid=_ASSIGNEE,
    )
    # A different authorized operator approves on the assignee's behalf.
    result = await coordinator.resolve(
        approval_id="aid-del",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )
    assert result.outcome is ResolveOutcome.EXECUTED
    assert result.delegated is True
    assert result.assignee_oid == _ASSIGNEE
    assert len(publisher.records) == 1
    executed = [
        e["entry"]
        for e in store.audit_entries
        if e["entry"].get("action_kind") == "hil.approved.executed"
    ]
    # The audit records BOTH the actual approver and the original assignee.
    assert executed[0]["delegated"] is True
    assert executed[0]["delegation_mode"] == "delegated"
    assert executed[0]["approver_oid"] == _APPROVER
    assert executed[0]["assignee_oid"] == _ASSIGNEE


@pytest.mark.asyncio
async def test_role_scoped_approval_when_no_assignee() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-rs")
    result = await coordinator.resolve(
        approval_id="aid-rs",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )
    assert result.outcome is ResolveOutcome.EXECUTED
    assert result.delegated is False
    assert result.assignee_oid is None
    executed = [
        e["entry"]
        for e in store.audit_entries
        if e["entry"].get("action_kind") == "hil.approved.executed"
    ]
    assert executed[0]["delegation_mode"] == "role_scoped"


@pytest.mark.asyncio
async def test_missing_capability_is_refused() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c1",
        approval_id="aid-cap",
        assignee_oid=_ASSIGNEE,
    )
    result = await coordinator.resolve(
        approval_id="aid-cap",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
        approver_can_approve_hil=False,  # RBAC says no
    )
    assert result.outcome is ResolveOutcome.MISSING_CAPABILITY
    assert result.assignee_oid == _ASSIGNEE
    # Refused before any execution - fail closed.
    assert publisher.records == ()
    assert "hil.resolve.capability_refused" in _audit_kinds(store)
    parked = await store.read_state("hil_park:aid-cap")
    assert parked is not None
    assert parked["status"] == "pending"  # still resolvable by an authorized approver


@pytest.mark.asyncio
async def test_missing_capability_still_refuses_self_approval_first() -> None:
    # Self-approval is checked before capability: a submitter who also lacks
    # the capability is refused as self-approval (identity floor wins).
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-cap2")
    result = await coordinator.resolve(
        approval_id="aid-cap2",
        decision=HilDecision.APPROVE,
        approver_oid=_SUBMITTER,
        approver_can_approve_hil=False,
    )
    assert result.outcome is ResolveOutcome.SELF_APPROVAL_REFUSED
    assert publisher.records == ()

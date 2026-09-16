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

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.executor import (
    ExecutorOutcome,
    ResourceLockManager,
    ShadowExecutor,
    TemplateRenderer,
)
from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.core.hil_resume import (
    ApprovalLoadController,
    ApprovalLoadPolicy,
    ApprovalReminderDispatcher,
    EscalationDuty,
    EscalationPolicy,
    EscalationRung,
    HilResumeCoordinator,
    HumanNonResponseSupervisor,
    RequestOutcome,
    ResolveOutcome,
)
from fdai.core.hil_resume.integrity import approval_request_fingerprint
from fdai.core.human_reporting import (
    ApprovalContactConsentService,
    ReportingGraphEdge,
    ReportingGraphSnapshot,
    ReportLineApprovalRouter,
    ReportLineRoutingPolicy,
)
from fdai.core.oncall import OnCallResolver
from fdai.core.ontology_platform.reconciliation_producer import (
    ReconciliationRequestProduction,
    ReconciliationRequestProductionStatus,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
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
    StopConditionKind,
    WorkflowActionRef,
)
from fdai.shared.providers.hil_channel import HilChannelError, HilDecision
from fdai.shared.providers.oncall_schedule import OnCallShift, StaticOnCallSchedule
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingRemediationPrPublisher,
)
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel

REPO_ROOT = Path(__file__).resolve().parents[5]
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"

_RULE_ID = "object-storage.owner-tag.required"
_SUBMITTER = "system:control-loop"
_APPROVER = "alice@example.com"
_ROUTE_START = datetime(2020, 1, 1, tzinfo=UTC)
_ROUTE_END = datetime(2100, 1, 1, tzinfo=UTC)


class ResolveDeliveryRaceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.injected = False

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if audit_entry.get("action_kind") == "hil.rejected" and not self.injected:
            self.injected = True
            current = await self.read_state(key)
            assert current is not None
            delivered = dict(current)
            delivered["revision"] = expected_revision + 1
            applied = await super().compare_and_set_state_with_audit(
                key,
                delivered,
                expected_revision=expected_revision,
                audit_entry={
                    "actor": "test",
                    "action_kind": "hil.delivery.observed",
                    "idempotency_key": f"{key}:delivery-observed",
                },
            )
            assert applied
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


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
    mode: Mode = Mode.SHADOW,
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
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=mode,
        citing_rules=[_RULE_ID],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def test_legacy_approval_fingerprint_is_stable_without_report_line_route() -> None:
    action = _action()
    rule = _rule()
    material = {
        "action": action.model_dump(mode="json"),
        "rule": {"id": rule.id, "version": rule.version},
        "submitter_oid": _SUBMITTER,
        "correlation_id": "correlation",
        "reasons": [],
        "blast_radius_summary": "",
        "ttl_seconds": 1800,
        "assignee_oid": None,
    }
    expected = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()

    assert (
        approval_request_fingerprint(
            action=action,
            rule=rule,
            submitter_oid=_SUBMITTER,
            correlation_id="correlation",
            reasons=(),
            blast_radius_summary="",
            ttl_seconds=1800,
            assignee_oid=None,
        )
        == expected
    )


def _coordinator(
    *,
    send_error: BaseException | None = None,
    with_escalation: bool = False,
    state_store: InMemoryStateStore | None = None,
    pre_dispatch_kinetic_safety_writer: Any | None = None,
    effect_reconciliation_request_sink: Any | None = None,
    report_line_router: ReportLineApprovalRouter | None = None,
    escalation_policy: EscalationPolicy | None = None,
    escalation_eligibility: Any | None = None,
) -> tuple[
    HilResumeCoordinator,
    RecordingRemediationPrPublisher,
    InMemoryStateStore,
    InMemoryHilChannel,
]:
    publisher = RecordingRemediationPrPublisher()
    store = state_store or InMemoryStateStore()
    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=store,
        renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
        resource_lock=ResourceLockManager(),
    )
    channel = InMemoryHilChannel(send_error=send_error)
    escalation_supervisor = (
        HumanNonResponseSupervisor(
            state_store=store,
            channel=channel,
            policy=escalation_policy or EscalationPolicy(decision_timeout_seconds=60),
            eligibility=escalation_eligibility,
        )
        if with_escalation
        else None
    )
    coordinator = HilResumeCoordinator(
        state_store=store,
        executor=executor,
        hil_channel=channel,
        rules_by_id={_RULE_ID: _rule()},
        escalation_supervisor=escalation_supervisor,
        pre_dispatch_kinetic_safety_writer=pre_dispatch_kinetic_safety_writer,
        effect_reconciliation_request_sink=effect_reconciliation_request_sink,
        report_line_router=report_line_router,
        contact_consent_service=(
            ApprovalContactConsentService(store) if report_line_router is not None else None
        ),
    )
    return coordinator, publisher, store, channel


class _ReportLineGraphs:
    def __init__(self) -> None:
        self.revision = "a" * 64
        self.edge_digest = "b" * 64

    async def current_graph(self, *, at=None):
        observed_at = at or datetime.now(tz=UTC)
        return ReportingGraphSnapshot(
            revision=self.revision,
            observed_at=observed_at,
            edges=(
                ReportingGraphEdge(
                    case_id="report-line-case",
                    edge_digest=self.edge_digest,
                    subject_ref=_SUBMITTER,
                    manager_ref=_APPROVER,
                    effective_from=_ROUTE_START,
                    effective_until=_ROUTE_END,
                ),
            ),
        )


class _ReportLineEligibility:
    def __init__(self, eligible: set[str] | None = None) -> None:
        self.eligible = eligible or {_APPROVER}

    async def is_eligible(
        self,
        *,
        subject_ref,
        minimum_role,
        action_type,
        scope_ref,
        at,
    ):
        del action_type, scope_ref, at
        return subject_ref in self.eligible and minimum_role == "Approver"


def _report_line_router(
    graphs: _ReportLineGraphs | None = None,
    *,
    eligible: set[str] | None = None,
) -> ReportLineApprovalRouter:
    return ReportLineApprovalRouter(
        graphs=graphs or _ReportLineGraphs(),
        eligibility=_ReportLineEligibility(eligible),
        policy=ReportLineRoutingPolicy(
            action_types=frozenset({"remediate.tag-add"}),
            quorum_by_action={},
        ),
    )


class _TwoLevelReportLineGraphs(_ReportLineGraphs):
    async def current_graph(self, *, at=None):
        observed_at = at or datetime.now(tz=UTC)
        return ReportingGraphSnapshot(
            revision=self.revision,
            observed_at=observed_at,
            edges=(
                ReportingGraphEdge(
                    case_id="report-line-case-primary",
                    edge_digest=self.edge_digest,
                    subject_ref=_SUBMITTER,
                    manager_ref=_APPROVER,
                    effective_from=_ROUTE_START,
                    effective_until=_ROUTE_END,
                ),
                ReportingGraphEdge(
                    case_id="report-line-case-escalation",
                    edge_digest="c" * 64,
                    subject_ref=_APPROVER,
                    manager_ref="backup@example.com",
                    effective_from=_ROUTE_START,
                    effective_until=_ROUTE_END,
                ),
            ),
        )


class _AlwaysEligible:
    async def is_eligible(self, **_kwargs):
        return True


async def test_request_snapshots_and_starts_escalation_after_delivery() -> None:
    coordinator, _, store, channel = _coordinator(with_escalation=True)

    result = await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="escalation-correlation",
        approval_id="escalation-approval",
        escalation_rungs=(
            EscalationRung(_APPROVER, EscalationDuty.PRIMARY),
            EscalationRung("backup@example.com", EscalationDuty.BACKUP),
        ),
    )

    parked = await store.read_state("hil_park:escalation-approval")
    assert result.outcome is RequestOutcome.PARKED
    assert len(channel.sent) == 1
    assert parked is not None
    assert parked["assignee_oid"] == _APPROVER
    assert parked["revision"] == 1
    assert parked["escalation"]["status"] == "awaiting_decision"
    requested = next(
        entry["entry"]
        for entry in store.audit_entries
        if entry["entry"].get("action_kind") == "hil.requested"
    )
    assert requested["assignee_oid"] == _APPROVER


async def test_report_line_route_waits_for_requester_contact_consent() -> None:
    coordinator, publisher, store, channel = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(),
    )

    requested = await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-correlation",
        approval_id="report-line-approval",
    )

    parked = await store.read_state("hil_park:report-line-approval")
    assert requested.outcome is RequestOutcome.CONTACT_CONSENT_REQUIRED
    assert parked is not None
    assert parked["status"] == "awaiting_contact_consent"
    assert parked["assignee_oid"] == _APPROVER
    assert channel.sent == []
    assert publisher.records == ()

    premature = await coordinator.resolve(
        approval_id="report-line-approval",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )
    assert premature.outcome is ResolveOutcome.CONTACT_CONSENT_REQUIRED
    assert publisher.records == ()

    sent = await coordinator.decide_report_line_contact(
        approval_id="report-line-approval",
        requester_oid=_SUBMITTER,
        consent=True,
        expected_consent_revision=0,
    )
    assert sent.outcome is RequestOutcome.PARKED
    assert len(channel.sent) == 1
    parked = await store.read_state("hil_park:report-line-approval")
    assert parked is not None and parked["status"] == "pending"
    assert parked["report_line_route"]["graph_revision"] == "a" * 64
    assert len(parked["report_line_route"]["path_revision"]) == 64


async def test_report_line_contact_decline_is_terminal_noop() -> None:
    coordinator, publisher, store, channel = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-decline",
        approval_id="report-line-decline",
    )

    declined = await coordinator.decide_report_line_contact(
        approval_id="report-line-decline",
        requester_oid=_SUBMITTER,
        consent=False,
        expected_consent_revision=0,
    )

    assert declined.outcome is RequestOutcome.CONTACT_DECLINED
    assert channel.sent == []
    assert publisher.records == ()
    parked = await store.read_state("hil_park:report-line-decline")
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == "timeout"


async def test_report_line_contact_expiry_is_terminal_noop() -> None:
    coordinator, publisher, store, channel = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-expired",
        approval_id="report-line-expired",
    )
    parked = await store.read_state("hil_park:report-line-expired")
    assert parked is not None
    expires_at = datetime.fromisoformat(str(parked["contact_consent_expires_at"]))

    expired = await coordinator.decide_report_line_contact(
        approval_id="report-line-expired",
        requester_oid=_SUBMITTER,
        consent=True,
        expected_consent_revision=0,
        at=expires_at,
    )

    assert expired.outcome is RequestOutcome.CONTACT_CONSENT_EXPIRED
    assert channel.sent == []
    assert publisher.records == ()
    parked = await store.read_state("hil_park:report-line-expired")
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == "timeout"


async def test_unanswered_report_line_contact_is_reaped_at_consent_deadline() -> None:
    coordinator, publisher, store, channel = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-unanswered",
        approval_id="report-line-unanswered",
    )
    parked = await store.read_state("hil_park:report-line-unanswered")
    assert parked is not None
    expires_at = datetime.fromisoformat(str(parked["contact_consent_expires_at"]))
    assert coordinator.escalation_supervisor is not None

    tick = await coordinator.escalation_supervisor.tick(at=expires_at)

    assert tick.exhausted == 1
    assert channel.sent == []
    assert publisher.records == ()
    parked = await store.read_state("hil_park:report-line-unanswered")
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == "timeout"


async def test_report_line_graph_change_blocks_a_late_approval() -> None:
    graphs = _ReportLineGraphs()
    coordinator, publisher, store, _ = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(graphs),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-stale",
        approval_id="report-line-stale",
    )
    await coordinator.decide_report_line_contact(
        approval_id="report-line-stale",
        requester_oid=_SUBMITTER,
        consent=True,
        expected_consent_revision=0,
    )
    graphs.edge_digest = "d" * 64

    result = await coordinator.resolve(
        approval_id="report-line-stale",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert result.reason == "report_line_route_stale"
    assert publisher.records == ()


async def test_unrelated_graph_revision_does_not_invalidate_pinned_path() -> None:
    graphs = _ReportLineGraphs()
    coordinator, publisher, store, _ = _coordinator(
        with_escalation=True,
        report_line_router=_report_line_router(graphs),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-unrelated-change",
        approval_id="report-line-unrelated-change",
    )
    await coordinator.decide_report_line_contact(
        approval_id="report-line-unrelated-change",
        requester_oid=_SUBMITTER,
        consent=True,
        expected_consent_revision=0,
    )
    graphs.revision = "d" * 64

    result = await coordinator.resolve(
        approval_id="report-line-unrelated-change",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTED
    assert len(publisher.records) == 1
    terminal = [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") in {"hil.approved.claimed", "hil.approved.executed"}
    ]
    assert len(terminal) == 2
    assert all(item.get("report_line_route_digest") for item in terminal)
    assert all(item.get("report_line_path_revision") for item in terminal)
    assert all(item.get("report_line_graph_revision") for item in terminal)


async def test_escalated_report_line_rung_can_approve_after_revalidation() -> None:
    graphs = _TwoLevelReportLineGraphs()
    coordinator, publisher, store, channel = _coordinator(
        with_escalation=True,
        escalation_policy=EscalationPolicy(
            decision_timeout_seconds=1,
            overall_timeout_seconds=60,
            mode=Mode.ENFORCE,
        ),
        escalation_eligibility=_AlwaysEligible(),
        report_line_router=_report_line_router(
            graphs,
            eligible={_APPROVER, "backup@example.com"},
        ),
    )
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="report-line-escalation",
        approval_id="report-line-escalation",
    )
    await coordinator.decide_report_line_contact(
        approval_id="report-line-escalation",
        requester_oid=_SUBMITTER,
        consent=True,
        expected_consent_revision=0,
    )
    parked = await store.read_state("hil_park:report-line-escalation")
    assert parked is not None
    deadline = datetime.fromisoformat(str(parked["escalation"]["decision_deadline"]))
    assert coordinator.escalation_supervisor is not None

    tick = await coordinator.escalation_supervisor.tick(
        at=deadline + timedelta(seconds=1),
    )
    assert tick.advanced == 1
    parked = await store.read_state("hil_park:report-line-escalation")
    assert parked is not None
    assert parked["assignee_oid"] == "backup@example.com"
    delivered = await coordinator.escalation_supervisor.tick(
        at=deadline + timedelta(seconds=2),
    )
    assert delivered.delivered == 1
    assert len(channel.sent) == 2

    result = await coordinator.resolve(
        approval_id="report-line-escalation",
        decision=HilDecision.APPROVE,
        approver_oid="backup@example.com",
    )
    assert result.outcome is ResolveOutcome.EXECUTED
    assert len(publisher.records) == 1


async def test_concurrent_terminal_decisions_have_one_winner() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="decision-race-correlation",
        approval_id="decision-race",
    )

    approve, reject = await asyncio.gather(
        coordinator.resolve(
            approval_id="decision-race",
            decision=HilDecision.APPROVE,
            approver_oid="approver-1",
        ),
        coordinator.resolve(
            approval_id="decision-race",
            decision=HilDecision.REJECT,
            approver_oid="approver-2",
        ),
    )

    outcomes = {approve.outcome, reject.outcome}
    parked = await store.read_state("hil_park:decision-race")
    assert len(outcomes & {ResolveOutcome.EXECUTED, ResolveOutcome.REJECTED}) == 1
    assert ResolveOutcome.CONFLICTING_DECISION in outcomes
    assert len(publisher.records) <= 1
    assert parked is not None
    assert parked["revision"] == 1


async def test_terminal_decision_retries_after_benign_delivery_revision() -> None:
    store = ResolveDeliveryRaceStore()
    coordinator, publisher, _, _ = _coordinator(state_store=store)
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="delivery-race-correlation",
        approval_id="delivery-race",
    )

    result = await coordinator.resolve(
        approval_id="delivery-race",
        decision=HilDecision.REJECT,
        approver_oid=_APPROVER,
    )

    parked = await store.read_state("hil_park:delivery-race")
    assert result.outcome is ResolveOutcome.REJECTED
    assert publisher.records == ()
    assert parked is not None
    assert parked["status"] == "resolved"
    assert parked["decision"] == HilDecision.REJECT.value


def _audit_kinds(store: InMemoryStateStore) -> list[str]:
    return [str(e["entry"].get("action_kind")) for e in store.audit_entries]


def _load_policy() -> ApprovalLoadPolicy:
    return ApprovalLoadPolicy.from_mapping(
        {
            "schema_version": "1.0.0",
            "group_window_seconds": 300,
            "max_pending_per_assignee": 2,
            "reminder_offsets_seconds": [600],
            "quiet_hours_utc": {"start": "22:00", "end": "06:00"},
            "urgent_severities": ["critical"],
            "scan_limit": 100,
            "worker_interval_seconds": 30,
        }
    )


def _load_controlled_coordinator(
    *, now: datetime
) -> tuple[HilResumeCoordinator, InMemoryStateStore, InMemoryHilChannel]:
    publisher = RecordingRemediationPrPublisher()
    store = InMemoryStateStore()
    channel = InMemoryHilChannel()
    policy = _load_policy()
    controller = ApprovalLoadController(state_store=store, policy=policy, clock=lambda: now)
    dispatcher = ApprovalReminderDispatcher(
        state_store=store,
        channel=channel,
        policy=policy,
        clock=lambda: now,
    )
    coordinator = HilResumeCoordinator(
        state_store=store,
        executor=ShadowExecutor(
            publisher=publisher,
            audit_store=store,
            renderer=TemplateRenderer(remediation_root=REMEDIATION_ROOT),
            resource_lock=ResourceLockManager(),
        ),
        hil_channel=channel,
        rules_by_id={_RULE_ID: _rule()},
        approval_load_controller=controller,
        approval_reminder_dispatcher=dispatcher,
    )
    return coordinator, store, channel


async def test_quiet_hour_defers_delivery_but_keeps_park() -> None:
    now = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    coordinator, store, channel = _load_controlled_coordinator(now=now)

    result = await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="quiet-correlation",
        approval_id="quiet-approval",
        assignee_oid=_APPROVER,
        ttl_seconds=30_000,
    )

    assert result.outcome is RequestOutcome.PARKED_DEFERRED
    assert await store.read_state("hil_park:quiet-approval") is not None
    assert channel.sent == []
    assert coordinator.reminder_dispatcher is not None


async def test_reaped_timeout_returns_idempotent_timed_out_to_late_approval() -> None:
    coordinator, _, store, _ = _coordinator()
    await store.write_state(
        "hil_park:expired-reaped",
        {
            "status": "resolved",
            "decision": HilDecision.TIMEOUT.value,
            "approval_id": "expired-reaped",
            "correlation_id": "corr-expired-reaped",
            "idempotency_key": "idem-expired-reaped",
            "submitter_oid": _SUBMITTER,
            "approver_oid": "system:approval-expiry",
        },
    )

    result = await coordinator.resolve(
        approval_id="expired-reaped",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert result.reason == "approval_expired"


async def test_similar_approval_groups_without_dropping_member() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    coordinator, store, channel = _load_controlled_coordinator(now=now)

    first = await coordinator.request_approval(
        action=_action(idempotency_key="group-one"),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="group-correlation-one",
        approval_id="group-approval-one",
        assignee_oid=_APPROVER,
    )
    second = await coordinator.request_approval(
        action=_action(idempotency_key="group-two", target="resource:example/rg/stg2"),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="group-correlation-two",
        approval_id="group-approval-two",
        assignee_oid=_APPROVER,
    )

    assert first.outcome is RequestOutcome.PARKED
    assert second.outcome is RequestOutcome.PARKED_DEFERRED
    assert len(channel.sent) == 1
    assert await store.read_state("hil_park:group-approval-one") is not None
    assert await store.read_state("hil_park:group-approval-two") is not None


async def test_critical_approval_bypasses_quiet_hour() -> None:
    now = datetime(2026, 7, 25, 23, 0, tzinfo=UTC)
    coordinator, store, channel = _load_controlled_coordinator(now=now)
    critical_rule = _rule().model_copy(update={"severity": Severity.CRITICAL})

    result = await coordinator.request_approval(
        action=_action(idempotency_key="critical-idem"),
        rule=critical_rule,
        submitter_oid=_SUBMITTER,
        correlation_id="critical-correlation",
        approval_id="critical-approval",
        assignee_oid=_APPROVER,
    )

    assert result.outcome is RequestOutcome.PARKED
    assert len(channel.sent) == 1
    assert channel.sent[0].metadata["approval_load_mode"] == "send_now"
    assert await store.read_state("hil_park:critical-approval") is not None


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
async def test_approve_persists_kinetic_safety_before_resume_dispatch() -> None:
    writer = MagicMock()
    writer.persist = AsyncMock(return_value=None)
    coordinator, publisher, _, _ = _coordinator(
        pre_dispatch_kinetic_safety_writer=writer,
    )
    await _park(coordinator, approval_id="aid-kinetic-order")

    result = await coordinator.resolve(
        approval_id="aid-kinetic-order",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTED
    writer.persist.assert_awaited_once_with(
        action=_action(),
        correlation_id="c1",
    )
    assert len(publisher.records) == 1


@pytest.mark.asyncio
async def test_approve_blocks_resume_dispatch_when_kinetic_safety_fails() -> None:
    writer = MagicMock()
    writer.persist = AsyncMock(side_effect=ValueError("proposal identity mismatch"))
    coordinator, publisher, _, _ = _coordinator(
        pre_dispatch_kinetic_safety_writer=writer,
    )
    await _park(coordinator, approval_id="aid-kinetic-invalid")

    result = await coordinator.resolve(
        approval_id="aid-kinetic-invalid",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTION_NOT_ATTEMPTED
    assert result.execution_result is not None
    assert result.execution_result.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert publisher.records == ()


@pytest.mark.asyncio
async def test_approved_pending_execution_is_not_recorded_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconciliation = AsyncMock(
        return_value=ReconciliationRequestProduction(
            ReconciliationRequestProductionStatus.PUBLISHED,
            "broker_acknowledged",
            "reconciliation:one",
        )
    )
    coordinator, _, store, _ = _coordinator(
        effect_reconciliation_request_sink=reconciliation,
    )
    action = _action().model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id="process-hil-001",
                step_id="restart",
                proposal_ref="proposal:hil:001",
                attempt=2,
            )
        }
    )
    await coordinator.request_approval(
        action=action,
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="pending-execution-correlation",
        approval_id="pending-execution",
    )

    async def pending_dispatch(
        _self: HilResumeCoordinator,
        **_kwargs: Any,
    ) -> DirectApiExecutionResult:
        return DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
            mode=Mode.ENFORCE,
            safeguard_bundle_digest="sha256:" + "b" * 64,
            audit_context={
                "effect_possible": True,
                "reconciliation_required": True,
            },
        )

    monkeypatch.setattr(HilResumeCoordinator, "_dispatch", pending_dispatch)

    result = await coordinator.resolve(
        approval_id="pending-execution",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTION_PENDING
    terminal = [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "hil.approved.execution_pending"
    ]
    assert terminal[-1]["execution_outcome"] == "awaiting_effect_evidence"
    assert terminal[-1]["action_id"] == str(action.action_id)
    assert terminal[-1]["workflow_action"]["attempt"] == 2
    assert terminal[-1]["effect_reconciliation_request_status"] == "published"
    assert terminal[-1]["effect_reconciliation_id"] == "reconciliation:one"
    reconciliation.assert_awaited_once_with(
        action,
        "awaiting_effect_evidence",
        None,
        correlation_id="pending-execution-correlation",
    )
    requested = next(
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "hil.requested"
    )
    claimed = next(
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "hil.approved.claimed"
    )
    assert requested["workflow_action"]["attempt"] == 2
    assert claimed["workflow_action"]["attempt"] == 2
    assert not any(
        item["entry"].get("action_kind") == "hil.approved.execute_failed"
        for item in store.audit_entries
    )


@pytest.mark.asyncio
async def test_approved_no_effect_attempt_is_not_recorded_as_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, _, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="not-attempted-correlation",
        approval_id="not-attempted",
    )

    async def no_effect_dispatch(
        _self: HilResumeCoordinator,
        **_kwargs: Any,
    ) -> DirectApiExecutionResult:
        return DirectApiExecutionResult(
            action_id=str(_action().action_id),
            outcome=DirectApiExecutionOutcome.DISPATCH_NOT_ATTEMPTED,
            mode=Mode.ENFORCE,
            reason="broker refused before publication",
        )

    monkeypatch.setattr(HilResumeCoordinator, "_dispatch", no_effect_dispatch)

    result = await coordinator.resolve(
        approval_id="not-attempted",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTION_NOT_ATTEMPTED
    terminal = [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "hil.approved.execution_not_attempted"
    ]
    assert terminal[-1]["execution_outcome"] == "dispatch_not_attempted"
    assert not any(
        item["entry"].get("action_kind") == "hil.approved.execute_failed"
        for item in store.audit_entries
    )


@pytest.mark.asyncio
async def test_approve_refuses_tampered_parked_action() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-tampered")
    parked = await store.read_state("hil_park:aid-tampered")
    assert parked is not None
    parked["action"]["target_resource_ref"] = "azure://resource/changed"
    await store.write_state("hil_park:aid-tampered", parked)

    result = await coordinator.resolve(
        approval_id="aid-tampered",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert result.reason == "approval_integrity_failed"
    assert publisher.records == ()
    assert "hil.resolve.integrity_failed" in _audit_kinds(store)


@pytest.mark.asyncio
async def test_approve_refuses_parked_action_without_a_digest() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-no-digest")
    parked = await store.read_state("hil_park:aid-no-digest")
    assert parked is not None
    parked.pop("action_hash")
    parked["action"]["target_resource_ref"] = "azure://resource/changed"
    await store.write_state("hil_park:aid-no-digest", parked)

    result = await coordinator.resolve(
        approval_id="aid-no-digest",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert result.reason == "approval_integrity_failed"
    assert publisher.records == ()
    assert "hil.resolve.integrity_failed" in _audit_kinds(store)


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
async def test_expired_approve_times_out_before_execution() -> None:
    coordinator, publisher, store, _ = _coordinator()
    await _park(coordinator, approval_id="aid-expired")
    parked = await store.read_state("hil_park:aid-expired")
    assert parked is not None
    parked["approval_context"]["expires_at"] = (
        datetime.now(tz=UTC) - timedelta(seconds=1)
    ).isoformat()
    await store.write_state("hil_park:aid-expired", parked)

    result = await coordinator.resolve(
        approval_id="aid-expired",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.TIMED_OUT
    assert result.reason == "approval_expired"
    assert publisher.records == ()
    resolved = await store.read_state("hil_park:aid-expired")
    assert resolved is not None
    assert resolved["decision"] == "timeout"
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
async def test_hil_terminal_audit_preserves_enforce_action_mode() -> None:
    coordinator, _, store, _ = _coordinator()
    await coordinator.request_approval(
        action=_action(mode=Mode.ENFORCE),
        rule=_rule(),
        submitter_oid=_SUBMITTER,
        correlation_id="c-enforce",
        approval_id="aid-enforce",
    )

    result = await coordinator.resolve(
        approval_id="aid-enforce",
        decision=HilDecision.APPROVE,
        approver_oid=_APPROVER,
    )

    assert result.outcome is ResolveOutcome.EXECUTION_NOT_ATTEMPTED
    terminal = [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == "hil.approved.execution_not_attempted"
    ]
    assert terminal[-1]["mode"] == "enforce"


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

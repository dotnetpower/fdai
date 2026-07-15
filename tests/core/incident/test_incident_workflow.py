"""Built-in incident workflow tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.conversation.session import Principal, Role
from fdai.core.incident.registry import IncidentRegistry
from fdai.core.incident.workflow import (
    IncidentConfirmationError,
    IncidentLifecycleNotice,
    IncidentLifecycleWorkflow,
    IncidentNoticeKind,
    IncidentNotificationDeferred,
    IncidentWorkflowError,
    IncidentWorkflowForbiddenError,
)
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.state_store import IncidentWriteConflictError
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class RecordingNotifier:
    def __init__(self) -> None:
        self.notices: list[IncidentLifecycleNotice] = []

    async def notify(self, notice: IncidentLifecycleNotice) -> str:
        self.notices.append(notice)
        return notice.kind.value


def _operator(role: Role = Role.CONTRIBUTOR) -> Principal:
    return Principal(id="operator@example.com", role=role)


def _workflow() -> tuple[IncidentLifecycleWorkflow, RecordingNotifier, InMemoryStateStore]:
    store = InMemoryStateStore()
    notifier = RecordingNotifier()
    workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=store),
        notifier=notifier,
        allowed_agent_principals={"Heimdall"},
    )
    return workflow, notifier, store


async def test_operator_chat_requires_confirmation_then_opens_and_notifies() -> None:
    workflow, notifier, store = _workflow()
    turn = workflow.prepare_chat(
        text="prod-api-01 대상으로 SEV2 장애 케이스 열어줘",
        principal=_operator(),
    )
    assert turn.proposal is not None

    result = await workflow.confirm_chat(
        proposal=turn.proposal,
        principal=_operator(),
        confirmation="확인",
    )

    assert result.incident.state is IncidentState.OPEN
    assert result.notification_result == "opened"
    assert notifier.notices[0].kind is IncidentNoticeKind.OPENED
    assert store.incident_transitions[0]["actor_oid"] == "operator@example.com"


async def test_confirmation_rejects_other_operator_and_expired_proposal() -> None:
    workflow, _, _ = _workflow()
    turn = workflow.prepare_chat(
        text="Open a SEV3 incident for target prod-api-01",
        principal=_operator(),
    )
    assert turn.proposal is not None

    with pytest.raises(IncidentConfirmationError, match="requester"):
        await workflow.confirm_chat(
            proposal=turn.proposal,
            principal=Principal(id="other@example.com", role=Role.CONTRIBUTOR),
            confirmation="confirm",
        )
    with pytest.raises(IncidentConfirmationError, match="expired"):
        await workflow.confirm_chat(
            proposal=turn.proposal,
            principal=_operator(),
            confirmation="confirm",
            now=turn.proposal.expires_at + timedelta(seconds=1),
        )


async def test_reader_cannot_prepare_incident_creation() -> None:
    workflow, _, _ = _workflow()
    with pytest.raises(IncidentWorkflowForbiddenError, match="contributor"):
        workflow.prepare_chat(
            text="Open a SEV3 incident for target prod-api-01",
            principal=_operator(Role.READER),
        )


async def test_authorized_agent_requires_evidence_and_can_open() -> None:
    workflow, notifier, _ = _workflow()
    with pytest.raises(IncidentWorkflowError, match="member event"):
        await workflow.open_from_agent(
            producer_principal="Heimdall",
            correlation_keys=("resource:prod-api-01",),
            severity=IncidentSeverity.SEV1,
            member_event_ids=(),
            reason="error rate threshold breached",
        )

    result = await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV1,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        reason="error rate threshold breached",
    )
    assert result.incident.severity is IncidentSeverity.SEV1
    assert notifier.notices[-1].actor_oid == "Heimdall"


async def test_unlisted_agent_cannot_open_incident() -> None:
    workflow, _, _ = _workflow()
    with pytest.raises(IncidentWorkflowForbiddenError, match="not allowed"):
        await workflow.open_from_agent(
            producer_principal="UnknownAgent",
            correlation_keys=("resource:prod-api-01",),
            severity=IncidentSeverity.SEV2,
            member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
            reason="detected failure",
        )


async def test_transition_and_roster_each_notify() -> None:
    workflow, notifier, _ = _workflow()
    opened = await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        reason="detected failure",
    )

    transitioned = await workflow.transition_as_operator(
        incident_id=opened.incident.incident_id,
        to_state=IncidentState.TRIAGING,
        principal=_operator(),
        reason="on-call acknowledged",
    )
    roster = await workflow.notify_roster(
        actor_oid="scheduler",
        state=IncidentState.TRIAGING,
        now=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert transitioned.incident.state is IncidentState.TRIAGING
    assert roster.incidents == (transitioned.incident,)
    assert [notice.kind for notice in notifier.notices] == [
        IncidentNoticeKind.OPENED,
        IncidentNoticeKind.STATE_CHANGED,
        IncidentNoticeKind.ROSTER,
    ]


async def test_replayed_open_and_same_state_do_not_repeat_notifications() -> None:
    workflow, notifier, _ = _workflow()
    member = UUID("00000000-0000-0000-0000-000000000001")
    first = await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(member,),
        reason="detected failure",
    )
    replayed = await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(member,),
        reason="detected failure",
    )
    unchanged = await workflow.transition_from_agent(
        incident_id=first.incident.incident_id,
        to_state=IncidentState.OPEN,
        producer_principal="Heimdall",
        reason="duplicate delivery",
    )

    assert first.created is True
    assert replayed.created is False
    assert unchanged.changed is False
    assert [notice.kind for notice in notifier.notices] == [IncidentNoticeKind.OPENED]


async def test_notification_failure_does_not_hide_committed_incident() -> None:
    class FailingNotifier:
        async def notify(self, notice: IncidentLifecycleNotice) -> None:  # noqa: ARG002
            raise RuntimeError("injected notification failure")

    store = InMemoryStateStore()
    workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=store),
        notifier=FailingNotifier(),
        allowed_agent_principals={"Heimdall"},
    )

    result = await workflow.open_from_agent(
        producer_principal="Heimdall",
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        reason="detected failure",
    )

    assert result.created is True
    assert isinstance(result.notification_result, IncidentNotificationDeferred)
    assert result.notification_result.error_type == "RuntimeError"
    assert len(tuple(store.incident_transitions)) == 1


async def test_concurrent_agent_open_reports_created_and_notifies_once() -> None:
    workflow, notifier, _ = _workflow()
    member = UUID("00000000-0000-0000-0000-000000000001")

    results = await asyncio.gather(
        *(
            workflow.open_from_agent(
                producer_principal="Heimdall",
                correlation_keys=("resource:prod-api-01",),
                severity=IncidentSeverity.SEV2,
                member_event_ids=(member,),
                reason="detected failure",
            )
            for _ in range(8)
        )
    )

    assert sum(result.created for result in results) == 1
    assert [notice.kind for notice in notifier.notices] == [IncidentNoticeKind.OPENED]


async def test_duplicate_replica_transition_notifies_once_and_reports_one_change() -> None:
    store = InMemoryStateStore()
    first_notifier = RecordingNotifier()
    second_notifier = RecordingNotifier()
    first_registry = IncidentRegistry(state_store=store)
    opened = await first_registry.open(
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    second_registry = IncidentRegistry(state_store=store)
    second_registry.rehydrate(await store.read_incident_transitions())
    first = IncidentLifecycleWorkflow(registry=first_registry, notifier=first_notifier)
    second = IncidentLifecycleWorkflow(registry=second_registry, notifier=second_notifier)

    results = await asyncio.gather(
        first.transition_as_operator(
            incident_id=opened.incident_id,
            to_state=IncidentState.TRIAGING,
            principal=_operator(),
            now=datetime(2026, 7, 15, tzinfo=UTC),
        ),
        second.transition_as_operator(
            incident_id=opened.incident_id,
            to_state=IncidentState.TRIAGING,
            principal=_operator(),
            now=datetime(2026, 7, 15, 0, 0, 1, tzinfo=UTC),
        ),
    )

    assert sum(result.changed for result in results) == 1
    assert len(first_notifier.notices) + len(second_notifier.notices) == 1


async def test_stale_same_state_request_reloads_and_rejects_canonical_mismatch() -> None:
    store = InMemoryStateStore()
    first = IncidentRegistry(state_store=store)
    incident = await first.open(
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    stale = IncidentRegistry(state_store=store)
    stale.rehydrate(await store.read_incident_transitions())
    await first.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator-a",
    )

    with pytest.raises(IncidentWriteConflictError, match="stale same-state"):
        await stale.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.OPEN,
            actor_oid="operator-b",
        )

    assert stale.get(incident.incident_id).state is IncidentState.TRIAGING  # type: ignore[union-attr]
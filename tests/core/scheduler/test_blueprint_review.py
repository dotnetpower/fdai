"""Automation blueprint review and scheduler materialization tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.core.conversation import CreateScheduledTaskCommand, Principal, Role
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintAggregator,
    AutomationBlueprintCandidate,
    AutomationBlueprintEvidence,
    AutomationBlueprintMetrics,
    AutomationBlueprintReviewService,
    AutomationBlueprintState,
    AutomationBlueprintTextDraft,
    BlueprintEvidenceSource,
    BlueprintOutcome,
    InMemoryAutomationBlueprintStore,
    draft_blueprint_text,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile
from fdai.core.scheduler.store import InMemoryScheduleStore

_NOW = datetime(2026, 7, 20, 17, 0, tzinfo=UTC)


class _Authorizer:
    def can_review(self, principal: Principal) -> bool:
        return principal.role in {Role.APPROVER, Role.OWNER}


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


def _evidence(index: int) -> AutomationBlueprintEvidence:
    return AutomationBlueprintEvidence(
        evidence_id=f"turn-{index}",
        principal_id="operator-1",
        normalized_task_intent="check inventory drift",
        schedule_class="daily",
        schedule_expression="0 3 * * *",
        event_type="object.drift-check-requested",
        resource_scope="scope://subscription/example/resource-group/app",
        delivery_intent="audit-only",
        required_tools=("query_inventory",),
        isolation_profile=ScheduledRunIsolationProfile(),
        outcome=BlueprintOutcome.SUCCEEDED,
        source=BlueprintEvidenceSource.OPERATOR_TURN,
        occurred_at=_NOW + timedelta(minutes=index),
    )


def _candidate() -> AutomationBlueprintCandidate:
    return AutomationBlueprintAggregator().aggregate(
        [_evidence(1), _evidence(2), _evidence(3)],
        now=_NOW + timedelta(days=1),
    )[0]


def _service() -> tuple[
    AutomationBlueprintReviewService,
    InMemoryAutomationBlueprintStore,
    InMemoryScheduleStore,
    _Audit,
    AutomationBlueprintMetrics,
]:
    candidates = InMemoryAutomationBlueprintStore()
    schedules = InMemoryScheduleStore()
    audit = _Audit()
    metrics = AutomationBlueprintMetrics()
    service = AutomationBlueprintReviewService(
        store=candidates,
        authorizer=_Authorizer(),
        audit=audit,
        schedule_command=CreateScheduledTaskCommand(store=schedules),
        metrics=metrics,
    )
    return service, candidates, schedules, audit, metrics


async def test_candidate_is_inert_until_review_then_materializes_through_command() -> None:
    service, _candidates, schedules, audit, metrics = _service()
    candidate = await service.submit(_candidate())
    assert await schedules.list_all() == ()

    principal = Principal(id="approver-1", role=Role.APPROVER)
    accepted = await service.review(
        candidate.candidate_id,
        principal=principal,
        approve=True,
        reason="Recurring evidence is stable.",
        at=_NOW + timedelta(days=2),
    )
    assert accepted.state is AutomationBlueprintState.ACCEPTED
    assert await schedules.list_all() == ()

    materialized = await service.materialize(
        candidate.candidate_id,
        principal=principal,
        at=_NOW + timedelta(days=2),
    )
    tasks = await schedules.list_all()
    assert materialized.state is AutomationBlueprintState.MATERIALIZED
    assert len(tasks) == 1
    assert tasks[0].created_by == principal.id
    assert tasks[0].event_payload["shadow_only"] is True
    assert tasks[0].isolation_profile.max_tool_calls == 0
    used = await service.record_realized_usage(candidate.candidate_id)
    assert used.realized_usage_count == 1
    assert metrics.snapshot()["materialized"] == 1
    assert metrics.snapshot()["realized_usage"] == 1
    assert [event["action_kind"] for event in audit.events] == [
        "automation_blueprint.proposed",
        "automation_blueprint.accepted",
        "automation_blueprint.materialized",
        "automation_blueprint.used",
    ]


async def test_materialization_retry_is_idempotent_and_conflict_safe() -> None:
    service, _candidates, schedules, _audit, _metrics = _service()
    candidate = await service.submit(_candidate())
    principal = Principal(id="approver-1", role=Role.APPROVER)
    await service.review(
        candidate.candidate_id,
        principal=principal,
        approve=True,
        reason="Stable recurrence.",
        at=_NOW + timedelta(days=2),
    )

    first = await service.materialize(
        candidate.candidate_id, principal=principal, at=_NOW + timedelta(days=2)
    )
    second = await service.materialize(
        candidate.candidate_id, principal=principal, at=_NOW + timedelta(days=2)
    )
    assert first == second
    assert len(await schedules.list_all()) == 1


async def test_authorization_self_review_rejection_and_expiry_are_auditable() -> None:
    service, candidates, _schedules, _audit, metrics = _service()
    candidate = await service.submit(_candidate())
    with pytest.raises(PermissionError, match="not authorized"):
        await service.review(
            candidate.candidate_id,
            principal=Principal(id="reader-1", role=Role.READER),
            approve=True,
            reason="No authority.",
            at=_NOW + timedelta(days=2),
        )

    rejected = await service.review(
        candidate.candidate_id,
        principal=Principal(id="approver-1", role=Role.APPROVER),
        approve=False,
        reason="scope_too_broad",
        at=_NOW + timedelta(days=2),
    )
    assert rejected.state is AutomationBlueprintState.REJECTED
    assert metrics.snapshot()["rejection_reasons"] == {"scope_too_broad": 1}
    duplicate = await service.submit(_candidate())
    assert duplicate.state is AutomationBlueprintState.REJECTED
    assert len(await candidates.list_all()) == 1


async def test_new_evidence_after_rejection_can_create_new_candidate() -> None:
    service, candidates, _schedules, _audit, _metrics = _service()
    first = await service.submit(_candidate())
    await service.review(
        first.candidate_id,
        principal=Principal(id="approver-1", role=Role.APPROVER),
        approve=False,
        reason="needs_more_evidence",
        at=_NOW + timedelta(days=2),
    )
    expanded = AutomationBlueprintAggregator().aggregate(
        [_evidence(1), _evidence(2), _evidence(3), _evidence(4)],
        now=_NOW + timedelta(days=3),
    )[0]

    second = await service.submit(expanded)

    assert second.candidate_id != first.candidate_id
    assert len(await candidates.list_all()) == 2


async def test_proposer_cannot_self_review_and_expiry_is_terminal() -> None:
    service, candidates, _schedules, _audit, metrics = _service()
    self_proposed = replace(_candidate(), proposer="approver-1")
    await service.submit(self_proposed)
    with pytest.raises(PermissionError, match="self-review"):
        await service.review(
            self_proposed.candidate_id,
            principal=Principal(id="approver-1", role=Role.APPROVER),
            approve=True,
            reason="Self review.",
            at=_NOW + timedelta(days=2),
        )

    assert await service.expire(now=_NOW + timedelta(days=40)) == 1
    expired = await candidates.get(self_proposed.candidate_id)
    assert expired.state is AutomationBlueprintState.EXPIRED
    assert metrics.snapshot()["expired"] == 1


class _TextDrafter:
    def __init__(self, draft: AutomationBlueprintTextDraft) -> None:
        self._draft = draft

    async def draft(
        self,
        candidate: AutomationBlueprintCandidate,
        *,
        max_chars: int,
    ) -> AutomationBlueprintTextDraft:
        del candidate, max_chars
        return self._draft


async def test_optional_text_draft_is_bounded_and_cannot_change_authority_fields() -> None:
    candidate = _candidate()
    draft = await draft_blueprint_text(
        candidate,
        drafter=_TextDrafter(
            AutomationBlueprintTextDraft(name="Inventory drift check", prompt="Review daily drift.")
        ),
        max_chars=128,
    )
    assert draft.name == "Inventory drift check"
    assert candidate.required_tools == ("query_inventory",)
    assert candidate.resource_scope.endswith("/app")

    with pytest.raises(ValueError, match="printable"):
        AutomationBlueprintTextDraft(name="unsafe\u0000name", prompt="text")
    with pytest.raises(ValueError, match="budget"):
        await draft_blueprint_text(
            candidate,
            drafter=_TextDrafter(AutomationBlueprintTextDraft(name="n" * 100, prompt="p" * 100)),
            max_chars=128,
        )

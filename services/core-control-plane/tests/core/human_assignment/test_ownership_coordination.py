"""Focused ownership proposal and matching-merge coordination tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.human_assignment import (
    AssignmentCaseService,
    AssignmentIntent,
    AssignmentOwnershipCoordinator,
    AssignmentState,
    DutyBinding,
    ProviderSubject,
    ReviewDecision,
    VerifiedOwnershipMerge,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty, load_stewardship_from_yaml
from fdai.core.stewardship.names import AGENT_NAMES
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
_CONFIG = Path(__file__).resolve().parents[5] / "config" / "agent-stewardship.yaml"


def _owner(oid: str) -> Principal:
    return Principal(oid=oid, roles=frozenset({Role.OWNER}))


async def _approved_case(service: AssignmentCaseService) -> str:
    created = await service.create_case(
        principal=_owner("owner-1"),
        intent=AssignmentIntent(
            idempotency_key="ownership-case-1",
            subject=ProviderSubject(
                provider="entra",
                subject_id="00000000-0000-0000-0000-000000009999",
            ),
            requested_role=Role.READER,
            duty_bindings=tuple(
                DutyBinding(name, Duty.BACKUP, "scope:platform")
                for name in AGENT_NAMES
                if name != "Loki"
            ),
            goal_refs=(),
            requester_ref="owner-1",
            justification="Assign complete backup coverage for platform ownership.",
        ),
        now=_NOW,
    )
    submitted = await service.submit_for_review(
        principal=_owner("owner-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
        now=_NOW,
    )
    reviewed = await service.review(
        principal=_owner("owner-2"),
        case_id=created.case_id,
        expected_revision=submitted.revision,
        decision=ReviewDecision.APPROVE,
        now=_NOW,
    )
    assert reviewed.state is AssignmentState.APPROVED
    return reviewed.case_id


async def test_matching_reviewed_merge_publishes_one_shadow_iam_request() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case_id = await _approved_case(cases)
    prs = RecordingRemediationPrPublisher()
    bus = InMemoryEventBus()
    coordinator = AssignmentOwnershipCoordinator(
        cases=cases,
        store=store,
        pr_publisher=prs,
        event_bus=bus,
        event_topic="fdai.events",
    )
    base = load_stewardship_from_yaml(_CONFIG, environ={})

    opened, proposal = await coordinator.open_proposal(
        case_id=case_id,
        expected_revision=3,
        actor_ref="Odin",
        base=base,
        now=_NOW,
    )
    replay, replayed_proposal = await coordinator.open_proposal(
        case_id=case_id,
        expected_revision=opened.revision,
        actor_ref="Odin",
        base=base,
        now=_NOW,
    )

    assert opened.state is AssignmentState.OWNERSHIP_PR_OPEN
    assert replay.state is AssignmentState.OWNERSHIP_PR_OPEN
    assert replayed_proposal == proposal
    assert len(prs.records) == 1

    with pytest.raises(ValueError, match="does not match"):
        await coordinator.record_verified_merge(
            case_id=case_id,
            expected_revision=opened.revision,
            actor_ref="github:reviewer",
            merge=VerifiedOwnershipMerge(
                pr_ref=proposal.pr_ref,
                merge_commit_sha="a" * 40,
                merged_yaml="different",
                merged_at=_NOW,
            ),
        )

    merged = await coordinator.record_verified_merge(
        case_id=case_id,
        expected_revision=opened.revision,
        actor_ref="github:reviewer",
        merge=VerifiedOwnershipMerge(
            pr_ref=proposal.pr_ref,
            merge_commit_sha="a" * 40,
            merged_yaml=prs.records[0].patch,
            merged_at=_NOW,
        ),
    )
    event = await anext(bus.subscribe("fdai.events", "test"))

    assert merged.state is AssignmentState.OWNERSHIP_MERGED
    assert event.payload["event_type"] == "human.assignment.iam_apply_requested"
    assert event.payload["mode"] == "shadow"
    assert event.payload["payload"]["case_id"] == case_id

    replayed = await coordinator.record_verified_merge(
        case_id=case_id,
        expected_revision=merged.revision,
        actor_ref="github:reviewer",
        merge=VerifiedOwnershipMerge(
            pr_ref=proposal.pr_ref,
            merge_commit_sha="a" * 40,
            merged_yaml=prs.records[0].patch,
            merged_at=_NOW,
        ),
    )
    replayed_event = await anext(bus.subscribe("fdai.events", "replay-test"))

    assert replayed == merged
    assert replayed_event.payload["event_id"] == event.payload["event_id"]

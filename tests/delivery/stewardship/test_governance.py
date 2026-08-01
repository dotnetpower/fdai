from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from fdai.core.human_assignment import (
    AssignmentCase,
    AssignmentCaseService,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    ProviderSubject,
    ReviewDecision,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import load_stewardship_from_mapping, load_stewardship_from_yaml
from fdai.core.stewardship.handover_bootstrap import DraftOutcome, StewardMapDraft
from fdai.core.stewardship.model import Duty
from fdai.core.stewardship.names import AGENT_NAMES
from fdai.delivery.ingestion_gateway.handover import HandoverDraftArtifact
from fdai.delivery.stewardship import StewardshipGovernanceService, StewardshipMerge
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agent-stewardship.yaml"


class RecordingNotifications:
    def __init__(self) -> None:
        self.messages = []

    async def dispatch(self, message):
        self.messages.append(message)
        return object()


class RecordingAssignmentApply:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def publish(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return object()


def _owner(oid: str) -> Principal:
    return Principal(oid=oid, roles=frozenset({Role.OWNER}))


async def _approved_assignment(service: AssignmentCaseService) -> AssignmentCase:
    created = await service.create_case(
        principal=_owner("requester-1"),
        intent=AssignmentIntent(
            idempotency_key="assignment-governance-1",
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
            requester_ref="requester-1",
            justification="Provide complete backup ownership across platform agents.",
        ),
        now=datetime(2026, 8, 1, tzinfo=UTC),
    )
    pending = await service.submit_for_review(
        principal=_owner("requester-1"),
        case_id=created.case_id,
        expected_revision=created.revision,
        now=datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
    )
    return await service.review(
        principal=_owner("reviewer-1"),
        case_id=pending.case_id,
        expected_revision=pending.revision,
        decision=ReviewDecision.APPROVE,
        now=datetime(2026, 8, 1, 0, 2, tzinfo=UTC),
    )


def _artifact() -> HandoverDraftArtifact:
    return HandoverDraftArtifact(
        upload_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        draft=StewardMapDraft(version=1, outcome=DraftOutcome.DRAFTED),
        yaml=_CONFIG.read_text(encoding="utf-8"),
    )


async def test_proposal_is_idempotent_and_audited() -> None:
    publisher = RecordingRemediationPrPublisher()
    notifications = RecordingNotifications()
    store = InMemoryStateStore()
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=publisher,
        notifications=notifications,
        state_store=store,
    )
    artifact = _artifact()

    first = await service.propose(artifact=artifact, actor_oid="operator-1")
    second = await service.propose(artifact=artifact, actor_oid="operator-1")

    assert first.pr_ref == second.pr_ref
    assert second.already_existed is True
    assert len(publisher.records) == 1
    assert publisher.records[0].patch_path == "config/agent-stewardship.yaml"
    proposed = load_stewardship_from_mapping(
        yaml.safe_load(publisher.records[0].patch),
        environ={},
    )
    assert proposed == load_stewardship_from_yaml(_CONFIG)
    assert len(notifications.messages) == 1
    assert len(store.audit_entries) == 1

    replacement_publisher = RecordingRemediationPrPublisher()
    restarted = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=replacement_publisher,
        notifications=notifications,
        state_store=store,
    )
    recovered = await restarted.propose(artifact=artifact, actor_oid="operator-1")
    assert recovered.pr_ref == first.pr_ref
    assert recovered.already_existed is True
    assert replacement_publisher.records == ()


async def test_merge_delivery_is_idempotent_and_audited() -> None:
    notifications = RecordingNotifications()
    store = InMemoryStateStore()
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=RecordingRemediationPrPublisher(),
        notifications=notifications,
        state_store=store,
    )
    merge = StewardshipMerge(
        delivery_id="delivery-1",
        pr_ref="acme/fdai#42",
        actor_identity="github:operator",
        merged_yaml=_CONFIG.read_text(encoding="utf-8"),
    )

    assert await service.record_merge(merge) is True
    assert await service.record_merge(merge) is False
    assert len(notifications.messages) == 1
    assert "merged" in notifications.messages[0].title
    assert len(store.audit_entries) == 1


async def test_assignment_proposal_and_matching_merge_record_ownership_effect() -> None:
    publisher = RecordingRemediationPrPublisher()
    notifications = RecordingNotifications()
    store = InMemoryStateStore()
    assignments = AssignmentCaseService(store)
    approved = await _approved_assignment(assignments)
    assignment_apply = RecordingAssignmentApply()
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=publisher,
        notifications=notifications,
        state_store=store,
        assignment_cases=assignments,
        assignment_apply_publisher=assignment_apply,
    )

    first = await service.propose_assignment(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        actor_oid="requester-1",
    )
    opened = await assignments.get_case(approved.case_id)
    second = await service.propose_assignment(
        case_id=approved.case_id,
        expected_revision=opened.revision,
        actor_oid="requester-1",
    )

    assert opened.state is AssignmentState.OWNERSHIP_PR_OPEN
    assert second.pr_ref == first.pr_ref
    assert second.already_existed is True
    assert len(publisher.records) == 1
    candidate = load_stewardship_from_mapping(
        yaml.safe_load(publisher.records[0].patch),
        environ={},
    )
    assert candidate.version == 2

    merge = StewardshipMerge(
        delivery_id="assignment-delivery-1",
        pr_ref=first.pr_ref,
        actor_identity="github:reviewer",
        merged_yaml=publisher.records[0].patch,
    )
    assert await service.record_merge(merge)
    assert await service.record_merge(merge) is False
    merged = await assignments.get_case(approved.case_id)
    assert merged.state is AssignmentState.OWNERSHIP_MERGED
    assert merged.effect_receipts[0].receipt_ref == first.pr_ref
    assert assignment_apply.calls == [
        {
            "case_id": merged.case_id,
            "expected_revision": merged.revision,
            "requester_ref": "requester-1",
        }
    ]


async def test_assignment_merge_digest_mismatch_is_rejected() -> None:
    publisher = RecordingRemediationPrPublisher()
    store = InMemoryStateStore()
    assignments = AssignmentCaseService(store)
    approved = await _approved_assignment(assignments)
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=publisher,
        notifications=RecordingNotifications(),
        state_store=store,
        assignment_cases=assignments,
    )
    receipt = await service.propose_assignment(
        case_id=approved.case_id,
        expected_revision=approved.revision,
        actor_oid="requester-1",
    )
    changed = yaml.safe_load(publisher.records[0].patch)
    changed["stewardship"]["escalation"]["hop_timeout_seconds"] = 901

    with pytest.raises(ValueError, match="digest does not match"):
        await service.record_merge(
            StewardshipMerge(
                delivery_id="assignment-delivery-mismatch",
                pr_ref=receipt.pr_ref,
                actor_identity="github:reviewer",
                merged_yaml=yaml.safe_dump(changed, sort_keys=False),
            )
        )

    held = await assignments.get_case(approved.case_id)
    assert held.state is AssignmentState.OWNERSHIP_PR_OPEN

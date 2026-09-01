"""Draft-only ownership coordination for reviewed assignment cases."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentState,
    EffectKind,
    EffectReceipt,
)
from fdai.core.human_assignment.ownership import render_assignment_ownership_yaml
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.stewardship import StewardshipMap
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher
from fdai.shared.providers.state_store import StateStore

_PROPOSAL_PREFIX = "human_assignment:ownership-proposal:"
_NAMESPACE = uuid.NAMESPACE_URL


@dataclass(frozen=True, slots=True)
class OwnershipProposal:
    case_id: str
    pr_ref: str
    candidate_digest: str
    opened_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "pr_ref": self.pr_ref,
            "candidate_digest": self.candidate_digest,
            "opened_at": self.opened_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> OwnershipProposal:
        return cls(
            case_id=_string(value, "case_id"),
            pr_ref=_string(value, "pr_ref"),
            candidate_digest=_digest(value, "candidate_digest"),
            opened_at=_timestamp(value, "opened_at"),
        )


@dataclass(frozen=True, slots=True)
class VerifiedOwnershipMerge:
    """Merge evidence accepted only after a delivery adapter verified its signature."""

    pr_ref: str
    merge_commit_sha: str
    merged_yaml: str
    merged_at: datetime


@dataclass(frozen=True, slots=True)
class AssignmentOwnershipCoordinator:
    cases: AssignmentCaseService
    store: StateStore
    pr_publisher: RemediationPrPublisher
    event_bus: EventBus
    event_topic: str

    async def open_proposal(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_ref: str,
        base: StewardshipMap,
        now: datetime | None = None,
    ) -> tuple[AssignmentCase, OwnershipProposal]:
        assignment = await self.cases.get_case(case_id)
        if assignment.state not in {
            AssignmentState.APPROVED,
            AssignmentState.OWNERSHIP_PR_OPEN,
        }:
            raise ValueError("ownership proposal requires an approved assignment case")
        if assignment.revision != expected_revision:
            raise ValueError("ownership proposal revision is stale")
        candidate = render_assignment_ownership_yaml(base, assignment.intent)
        candidate_digest = hashlib.sha256(candidate.encode()).hexdigest()
        key = f"{_PROPOSAL_PREFIX}{case_id}"
        stored = await self.store.read_state(key)
        if stored is None:
            receipt = await self.pr_publisher.publish(
                RemediationPr(
                    action_id=uuid.uuid5(_NAMESPACE, case_id),
                    idempotency_key=f"assignment-ownership-{case_id}",
                    rule_ids=("human.assignment.ownership",),
                    title=f"Review operational ownership assignment {case_id}",
                    body=_body(case_id, candidate_digest),
                    patch=candidate,
                    patch_path="config/agent-stewardship.yaml",
                    labels=("shadow", "governance", "ownership"),
                    mode=Mode.SHADOW,
                    metadata={
                        "assignment_case_id": case_id,
                        "candidate_digest": candidate_digest,
                    },
                )
            )
            opened_at = _now(now)
            proposal = OwnershipProposal(
                case_id=case_id,
                pr_ref=receipt.pr_ref,
                candidate_digest=candidate_digest,
                opened_at=opened_at,
            )
            created = await self.store.write_state_with_audit_if_absent(
                key,
                proposal.to_dict(),
                {
                    "actor": actor_ref,
                    "action_kind": "human.assignment.ownership_pr_opened",
                    "case_id": case_id,
                    "pr_ref": receipt.pr_ref,
                    "candidate_digest": candidate_digest,
                    "mode": Mode.SHADOW.value,
                    "idempotency_key": f"assignment-ownership-{case_id}",
                    "recorded_at": opened_at.isoformat(),
                },
            )
            if not created:
                stored = await self.store.read_state(key)
                if stored is None:
                    raise RuntimeError("ownership proposal disappeared after a create race")
                proposal = OwnershipProposal.from_dict(dict(stored))
        else:
            proposal = OwnershipProposal.from_dict(dict(stored))
        if proposal.candidate_digest != candidate_digest:
            raise ValueError("ownership proposal conflicts with the approved assignment intent")
        current = await self.cases.get_case(case_id)
        if current.state is AssignmentState.APPROVED:
            current = await self.cases.open_ownership_pr(
                case_id=case_id,
                expected_revision=expected_revision,
                actor_ref=actor_ref,
                now=now,
            )
        return current, proposal

    async def record_verified_merge(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_ref: str,
        merge: VerifiedOwnershipMerge,
    ) -> AssignmentCase:
        stored = await self.store.read_state(f"{_PROPOSAL_PREFIX}{case_id}")
        if stored is None:
            raise ValueError("ownership merge has no matching assignment proposal")
        proposal = OwnershipProposal.from_dict(dict(stored))
        merged_digest = hashlib.sha256(merge.merged_yaml.encode()).hexdigest()
        if merge.pr_ref != proposal.pr_ref or merged_digest != proposal.candidate_digest:
            raise ValueError("ownership merge does not match the assignment proposal")
        assignment = await self.cases.record_effect(
            case_id=case_id,
            expected_revision=expected_revision,
            receipt=EffectReceipt(
                kind=EffectKind.OWNERSHIP,
                receipt_ref=f"merge:{merge.merge_commit_sha}",
                digest=merged_digest,
                received_at=merge.merged_at,
            ),
            actor_ref=actor_ref,
        )
        timestamp = merge.merged_at.astimezone(UTC)
        event = Event(
            schema_version="1.0.0",
            event_id=uuid.uuid5(_NAMESPACE, f"{case_id}:iam:{assignment.revision}"),
            idempotency_key=f"assignment-iam-{case_id}",
            correlation_id=case_id,
            source="human-assignment.ownership",
            event_type="human.assignment.iam_apply_requested",
            resource_ref=f"human-assignment:{case_id}",
            payload={
                "action_type": "ops.apply-human-access",
                "case_id": case_id,
                "expected_revision": assignment.revision,
            },
            detected_at=timestamp,
            ingested_at=timestamp,
            mode=Mode.SHADOW,
        )
        await self.event_bus.publish(
            self.event_topic,
            key=case_id,
            payload=event.model_dump(mode="json"),
        )
        return assignment


def _body(case_id: str, digest: str) -> str:
    return "\n".join(
        (
            "This draft proposes an operational ownership change for independent review.",
            "",
            f"Assignment case: `{case_id}`",
            f"Candidate digest: `{digest}`",
            "",
            "Merging this pull request records the ownership effect only.",
            "IAM membership remains a separate shadow-first action.",
        )
    )


def _string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"ownership proposal {key} is invalid")
    return item


def _digest(value: dict[str, object], key: str) -> str:
    item = _string(value, key)
    if len(item) != 64 or any(character not in "0123456789abcdef" for character in item):
        raise ValueError(f"ownership proposal {key} is invalid")
    return item


def _timestamp(value: dict[str, object], key: str) -> datetime:
    item = datetime.fromisoformat(_string(value, key))
    if item.tzinfo is None:
        raise ValueError(f"ownership proposal {key} has no timezone")
    return item


def _now(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("ownership proposal timestamp MUST be timezone-aware")
    return timestamp.astimezone(UTC)


__all__ = [
    "AssignmentOwnershipCoordinator",
    "OwnershipProposal",
    "VerifiedOwnershipMerge",
]

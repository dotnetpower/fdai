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
from fdai.core.human_assignment.revocation_ownership import render_revocation_ownership_yaml
from fdai.core.human_assignment.revocation_target import require_revocation_target
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

    async def request_revocation(self, *, case_id: str, expected_revision: int) -> None:
        """Publish an inert current-review request, not a removal or old-duty proposal."""
        from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader

        case = await self.cases.get_case(case_id)
        if case.intent.revocation is None or case.revision != expected_revision:
            raise ValueError("revocation request requires the exact removal case")
        original = await require_revocation_target(
            self.store, case.intent, revocation_case_id=case_id
        )
        ownership = next(
            item for item in original.effect_receipts if item.kind is EffectKind.OWNERSHIP
        )
        notice = {
            "case_id": case_id,
            "expected_revision": expected_revision,
            "ownership_digest": ownership.digest,
            "ownership_ref": ownership.receipt_ref,
        }
        await AssignmentIamRequestReader(self.cases).read(notice)
        timestamp = max(item.reviewed_at for item in case.reviews)
        key = f"assignment-revoke-{case.case_id}"
        event = Event(
            schema_version="1.0.0",
            event_id=uuid.uuid5(_NAMESPACE, key),
            idempotency_key=key,
            correlation_id=case.case_id,
            source="human-assignment.revocation",
            event_type="human.assignment.iam_apply_requested",
            resource_ref=f"human-assignment:{case_id}",
            payload=notice,
            detected_at=timestamp,
            ingested_at=timestamp,
            mode=Mode.SHADOW,
        )
        await self.event_bus.publish(
            self.event_topic, key=case.case_id, payload=event.model_dump(mode="json")
        )

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
        revoke = assignment.intent.revocation
        initial = AssignmentState.IAM_REVOKED if revoke is not None else AssignmentState.APPROVED
        if assignment.state not in {initial, AssignmentState.OWNERSHIP_PR_OPEN}:
            raise ValueError("ownership proposal requires an approved assignment case")
        if assignment.revision != expected_revision:
            raise ValueError("ownership proposal revision is stale")
        if revoke is None:
            candidate = render_assignment_ownership_yaml(base, assignment.intent)
        else:
            original = await require_revocation_target(
                self.store, assignment.intent, revocation_case_id=case_id, allow_held=True
            )
            replacements = {
                replacement_id: await self.cases.get_case(replacement_id)
                for replacement_id in revoke.replacement_revisions
            }
            candidate = render_revocation_ownership_yaml(
                base, assignment, original=original, replacements=replacements
            )
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
                    body=_body(case_id, candidate_digest, revoke=revoke is not None),
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
        if current.state is initial:
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
        assignment = await self.cases.get_case(case_id)
        receipt = EffectReceipt(
            kind=EffectKind.OWNERSHIP,
            receipt_ref=f"merge:{merge.merge_commit_sha}",
            digest=merged_digest,
            received_at=merge.merged_at,
        )
        current_receipt = next(
            (item for item in assignment.effect_receipts if item.kind is EffectKind.OWNERSHIP),
            None,
        )
        replay = (
            current_receipt is not None
            and current_receipt.receipt_ref == receipt.receipt_ref
            and current_receipt.digest == receipt.digest
        )
        if not replay:
            assignment = await self.cases.record_effect(
                case_id=case_id,
                expected_revision=expected_revision,
                receipt=receipt,
                actor_ref=actor_ref,
            )
        elif assignment.state is not AssignmentState.OWNERSHIP_MERGED:
            if assignment.state is AssignmentState.REVOKED:
                await self.cases.close_revocation_target(case_id=case_id, actor_ref=actor_ref)
            return assignment
        if assignment.intent.revocation is not None:
            return assignment
        timestamp = merge.merged_at.astimezone(UTC)
        event = Event(
            schema_version="1.0.0",
            event_id=uuid.uuid5(
                _NAMESPACE,
                f"{case_id}:iam:{proposal.candidate_digest}",
            ),
            idempotency_key=f"assignment-iam-{case_id}",
            correlation_id=case_id,
            source="human-assignment.ownership",
            event_type="human.assignment.iam_apply_requested",
            resource_ref=f"human-assignment:{case_id}",
            payload={
                "action_type": "ops.apply-human-access",
                "case_id": case_id,
                "expected_revision": assignment.revision,
                "ownership_digest": receipt.digest,
                "ownership_ref": receipt.receipt_ref,
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


def _body(case_id: str, digest: str, *, revoke: bool = False) -> str:
    return "\n".join(
        (
            "This draft proposes an operational ownership change for independent review.",
            "",
            f"Assignment case: `{case_id}`",
            f"Candidate digest: `{digest}`",
            "",
            "Merging this pull request records the ownership effect only.",
            (
                "A separately verified IAM removal already precedes this old-duty proposal."
                if revoke
                else "IAM membership remains a separate shadow-first action."
            ),
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

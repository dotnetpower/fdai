"""Idempotent stewardship governance PR and merge lifecycle orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import yaml

from fdai.core.human_assignment import (
    AssignmentCaseService,
    AssignmentState,
    EffectKind,
    EffectReceipt,
    render_assignment_ownership_yaml,
)
from fdai.core.stewardship import (
    StewardshipChangeEvent,
    StewardshipChangePhase,
    StewardshipMap,
    affected_agents_from_stewardship_change,
    build_change_audit_payload,
    build_change_notification,
    load_stewardship_from_mapping,
)
from fdai.core.stewardship.handover_bootstrap import render_candidate_yaml
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.notifications.base import NotificationMessage
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.delivery.ingestion_gateway.handover import HandoverDraftArtifact

_ARTIFACT_PATH = "config/agent-stewardship.yaml"
_PROPOSAL_PREFIX = "stewardship_governance:proposal:"
_MERGE_PREFIX = "stewardship_governance:merge:"


class NotificationDispatcher(Protocol):
    async def dispatch(self, message: NotificationMessage) -> object: ...


class HandoverDraftGovernance(Protocol):
    async def propose(
        self,
        *,
        artifact: HandoverDraftArtifact,
        actor_oid: str,
    ) -> PublishReceipt: ...


@dataclass(frozen=True, slots=True)
class StewardshipMerge:
    """Validated Git-host merge facts consumed by the governance service."""

    delivery_id: str
    pr_ref: str
    actor_identity: str
    merged_yaml: str


class StewardshipGovernanceService(HandoverDraftGovernance):
    """Deliver handover drafts and audit merged ownership changes."""

    def __init__(
        self,
        *,
        current_map: StewardshipMap,
        publisher: RemediationPrPublisher,
        notifications: NotificationDispatcher,
        state_store: StateStore,
        assignment_cases: AssignmentCaseService | None = None,
    ) -> None:
        self._current_map = current_map
        self._publisher = publisher
        self._notifications = notifications
        self._state_store = state_store
        self._assignment_cases = assignment_cases

    async def propose_assignment(
        self,
        *,
        case_id: str,
        expected_revision: int,
        actor_oid: str,
    ) -> PublishReceipt:
        """Publish one approved assignment as a digest-bound ownership PR."""

        if self._assignment_cases is None:
            raise RuntimeError("assignment-case governance is not configured")
        assignment_case = await self._assignment_cases.get_case(case_id)
        if assignment_case.state not in {
            AssignmentState.APPROVED,
            AssignmentState.OWNERSHIP_PR_OPEN,
        }:
            raise ValueError("assignment case MUST be approved before ownership publication")
        candidate_yaml = render_assignment_ownership_yaml(
            self._current_map,
            assignment_case.intent,
        )
        candidate = _load_yaml(candidate_yaml)
        candidate_digest = _content_digest(candidate_yaml)
        correlation_id = f"human-assignment:{assignment_case.case_id}"
        prior = await self._state_store.find_state(
            _PROPOSAL_PREFIX,
            field="correlation_id",
            value=correlation_id,
        )
        if prior is not None:
            return _prior_receipt(prior)
        receipt = await self._publisher.publish(
            RemediationPr(
                action_id=UUID(assignment_case.case_id),
                idempotency_key=correlation_id,
                rule_ids=("human-agent-assignment",),
                title="[governance] Review human-agent ownership assignment",
                body=_assignment_proposal_body(assignment_case.case_id),
                patch=candidate_yaml,
                patch_path=_ARTIFACT_PATH,
                labels=("shadow", "governance", "stewardship", "human-assignment"),
                mode=Mode.SHADOW,
                metadata={
                    "correlation_id": correlation_id,
                    "assignment_case_id": assignment_case.case_id,
                    "candidate_digest": candidate_digest,
                },
            )
        )
        if assignment_case.state is AssignmentState.APPROVED:
            assignment_case = await self._assignment_cases.open_ownership_pr(
                case_id=assignment_case.case_id,
                expected_revision=expected_revision,
                actor_ref=actor_oid,
            )
        affected = tuple(
            sorted(affected_agents_from_stewardship_change(self._current_map, candidate))
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            f"{_PROPOSAL_PREFIX}{receipt.pr_ref}",
            {
                "pr_ref": receipt.pr_ref,
                "actor_oid": actor_oid,
                "correlation_id": correlation_id,
                "affected_agents": list(affected),
                "url": receipt.url,
                "assignment_case_id": assignment_case.case_id,
                "candidate_digest": candidate_digest,
            },
            {
                "kind": "human.assignment.ownership_pr_opened",
                "actor_oid": actor_oid,
                "artifact": _ARTIFACT_PATH,
                "affected_agents": list(affected),
                "correlation_id": correlation_id,
                "pr_ref": receipt.pr_ref,
                "candidate_digest": candidate_digest,
                "idempotency_key": correlation_id,
            },
        )
        if created:
            event = StewardshipChangeEvent(
                actor_oid=actor_oid,
                artifact=_ARTIFACT_PATH,
                affected_agents=affected,
                summary=f"Assignment case {assignment_case.case_id} opened {receipt.pr_ref}.",
                correlation_id=correlation_id,
            )
            message, _ = build_change_notification(self._current_map, event)
            await self._notifications.dispatch(message)
        return receipt

    async def propose(
        self,
        *,
        artifact: HandoverDraftArtifact,
        actor_oid: str,
    ) -> PublishReceipt:
        candidate_yaml = render_candidate_yaml(artifact.draft, base=self._current_map)
        candidate = _load_yaml(candidate_yaml)
        affected = tuple(
            sorted(affected_agents_from_stewardship_change(self._current_map, candidate))
        )
        correlation_id = f"handover:{artifact.upload_id}"
        prior = await self._state_store.find_state(
            _PROPOSAL_PREFIX,
            field="correlation_id",
            value=correlation_id,
        )
        if prior is not None:
            return _prior_receipt(prior)
        receipt = await self._publisher.publish(
            RemediationPr(
                action_id=artifact.upload_id,
                idempotency_key=correlation_id,
                rule_ids=("agent-stewardship-handover",),
                title="[governance] Review agent ownership handover",
                body=_proposal_body(artifact),
                patch=candidate_yaml,
                patch_path=_ARTIFACT_PATH,
                labels=("shadow", "governance", "stewardship"),
                mode=Mode.SHADOW,
                metadata={"correlation_id": correlation_id},
            )
        )
        event = StewardshipChangeEvent(
            actor_oid=actor_oid,
            artifact=_ARTIFACT_PATH,
            affected_agents=affected,
            summary=f"Draft PR {receipt.pr_ref} was created from a handover upload.",
            correlation_id=correlation_id,
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            f"{_PROPOSAL_PREFIX}{receipt.pr_ref}",
            {
                "pr_ref": receipt.pr_ref,
                "upload_id": str(artifact.upload_id),
                "actor_oid": actor_oid,
                "correlation_id": correlation_id,
                "affected_agents": list(affected),
                "url": receipt.url,
            },
            {
                "kind": "stewardship.change.requested",
                **build_change_audit_payload(event),
                "pr_ref": receipt.pr_ref,
                "url": receipt.url,
                "idempotency_key": correlation_id,
            },
        )
        if created:
            message, _ = build_change_notification(self._current_map, event)
            await self._notifications.dispatch(message)
        return receipt

    async def record_merge(self, merge: StewardshipMerge) -> bool:
        """Record and notify one merge delivery exactly once."""
        candidate = _load_yaml(merge.merged_yaml)
        merged_digest = _content_digest(merge.merged_yaml)
        proposal = await self._state_store.find_state(
            _PROPOSAL_PREFIX,
            field="pr_ref",
            value=merge.pr_ref,
        )
        if proposal is not None and isinstance(proposal, dict):
            assignment_case_id = proposal.get("assignment_case_id")
            expected_digest = proposal.get("candidate_digest")
            if assignment_case_id is not None:
                if not isinstance(assignment_case_id, str) or not assignment_case_id:
                    raise RuntimeError("assignment proposal state has an invalid case id")
                if expected_digest != merged_digest:
                    raise ValueError("merged stewardship digest does not match assignment proposal")
                if self._assignment_cases is None:
                    raise RuntimeError("assignment-case governance is not configured")
                assignment_case = await self._assignment_cases.get_case(assignment_case_id)
                await self._assignment_cases.record_effect(
                    case_id=assignment_case.case_id,
                    expected_revision=assignment_case.revision,
                    receipt=EffectReceipt(
                        kind=EffectKind.OWNERSHIP,
                        receipt_ref=merge.pr_ref,
                        digest=merged_digest,
                        received_at=datetime.now(UTC),
                    ),
                    actor_ref=merge.actor_identity,
                )
        affected = tuple(
            sorted(affected_agents_from_stewardship_change(self._current_map, candidate))
        )
        event = StewardshipChangeEvent(
            actor_oid=merge.actor_identity,
            artifact=_ARTIFACT_PATH,
            affected_agents=affected,
            summary=f"Governance PR {merge.pr_ref} merged.",
            correlation_id=f"github:{merge.delivery_id}",
            phase=StewardshipChangePhase.MERGED,
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            f"{_MERGE_PREFIX}{merge.delivery_id}",
            {
                "delivery_id": merge.delivery_id,
                "pr_ref": merge.pr_ref,
                "actor_identity": merge.actor_identity,
                "affected_agents": list(affected),
                "merged_digest": merged_digest,
            },
            {
                "kind": "stewardship.change.merged",
                **build_change_audit_payload(event),
                "pr_ref": merge.pr_ref,
                "merged_digest": merged_digest,
                "idempotency_key": f"stewardship-merge:{merge.delivery_id}",
            },
        )
        if not created:
            return False
        message, _ = build_change_notification(candidate, event)
        await self._notifications.dispatch(message)
        return True


def _load_yaml(content: str) -> StewardshipMap:
    raw = yaml.safe_load(content)
    if not isinstance(raw, dict):
        raise ValueError("stewardship governance content MUST be a YAML mapping")
    return load_stewardship_from_mapping(raw, environ={})


def _proposal_body(artifact: HandoverDraftArtifact) -> str:
    return (
        "This draft maps uploaded operational ownership evidence onto the fixed FDAI "
        "pantheon. Review every source citation and replace unresolved placeholders before "
        "marking the pull request ready.\n\n"
        f"- Upload: `{artifact.upload_id}`\n"
        f"- Outcome: `{artifact.draft.outcome.value}`\n"
        f"- Unresolved people: `{len(artifact.draft.unresolved_people)}`\n"
        f"- Unmapped agents: `{len(artifact.draft.unmapped_agents)}`\n"
        "- Runtime mutation: none; this pull request changes governance configuration only.\n"
        "- Rollback: revert the merged configuration commit.\n"
    )


def _assignment_proposal_body(case_id: str) -> str:
    return (
        "This draft applies one independently reviewed human-agent assignment to the "
        "operational ownership map.\n\n"
        f"- Assignment case: `{case_id}`\n"
        "- Runtime mutation: none; this pull request changes governance configuration only.\n"
        "- Rollback: revert the merged configuration commit.\n"
    )


def _content_digest(content: str) -> str:
    raw = yaml.safe_load(content)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prior_receipt(state: object) -> PublishReceipt:
    if not isinstance(state, dict):
        raise RuntimeError("durable stewardship proposal state is malformed")
    pr_ref = state.get("pr_ref")
    url = state.get("url")
    if not isinstance(pr_ref, str) or not pr_ref:
        raise RuntimeError("durable stewardship proposal state has no PR reference")
    if url is not None and not isinstance(url, str):
        raise RuntimeError("durable stewardship proposal state has an invalid PR URL")
    return PublishReceipt(pr_ref=pr_ref, url=url, already_existed=True)


__all__ = [
    "HandoverDraftGovernance",
    "NotificationDispatcher",
    "StewardshipGovernanceService",
    "StewardshipMerge",
]

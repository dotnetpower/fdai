"""Idempotent stewardship governance PR and merge lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import yaml

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
    ) -> None:
        self._current_map = current_map
        self._publisher = publisher
        self._notifications = notifications
        self._state_store = state_store

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
            },
            {
                "kind": "stewardship.change.merged",
                **build_change_audit_payload(event),
                "pr_ref": merge.pr_ref,
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

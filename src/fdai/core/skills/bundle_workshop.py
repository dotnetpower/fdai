"""Human-reviewed proposal workflow for governed skill bundle manifests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import (
    SkillBundleTrustVerifier,
    parse_skill_bundle_manifest,
)


class SkillBundleProposalState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    MATERIALIZED = "materialized"


@dataclass(frozen=True, slots=True)
class SkillBundleProposal:
    proposal_id: str
    bundle_name: str
    content_hash: str
    manifest: bytes
    proposed_by_agent: str
    created_at: datetime
    state: SkillBundleProposalState = SkillBundleProposalState.DRAFT
    reviewed_by: str | None = None
    review_reason: str | None = None
    reviewed_at: datetime | None = None


class SkillBundleProposalStore(Protocol):
    async def create(self, proposal: SkillBundleProposal) -> SkillBundleProposal: ...

    async def get(self, proposal_id: str) -> SkillBundleProposal: ...

    async def transition(
        self,
        proposal: SkillBundleProposal,
        *,
        expected_state: SkillBundleProposalState,
    ) -> SkillBundleProposal | None: ...


class SkillBundleWorkshopAudit(Protocol):
    async def append(self, event: Mapping[str, Any]) -> None: ...


class SkillBundleReviewAuthorizer(Protocol):
    def can_review(self, reviewer_id: str) -> bool: ...


class SkillBundleWorkshopError(ValueError):
    """A bundle proposal transition was invalid or unauthorized."""


class InMemorySkillBundleProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, SkillBundleProposal] = {}

    async def create(self, proposal: SkillBundleProposal) -> SkillBundleProposal:
        prior = self._proposals.get(proposal.proposal_id)
        if prior is not None:
            if prior.content_hash == proposal.content_hash:
                return prior
            raise SkillBundleWorkshopError("skill bundle proposal id collision")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    async def get(self, proposal_id: str) -> SkillBundleProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise SkillBundleWorkshopError(
                f"skill bundle proposal {proposal_id!r} was not found"
            ) from exc

    async def transition(
        self,
        proposal: SkillBundleProposal,
        *,
        expected_state: SkillBundleProposalState,
    ) -> SkillBundleProposal | None:
        current = self._proposals.get(proposal.proposal_id)
        if current is None:
            raise SkillBundleWorkshopError(
                f"skill bundle proposal {proposal.proposal_id!r} was not found"
            )
        if current.state is not expected_state:
            return None
        self._proposals[proposal.proposal_id] = proposal
        return proposal


class SkillBundleWorkshop:
    """Validate bundle drafts and require distinct human review before promotion."""

    def __init__(
        self,
        *,
        store: SkillBundleProposalStore,
        audit: SkillBundleWorkshopAudit,
        authorizer: SkillBundleReviewAuthorizer,
    ) -> None:
        self._store = store
        self._audit = audit
        self._authorizer = authorizer

    async def propose(
        self,
        raw_manifest: bytes,
        *,
        proposed_by_agent: str,
        at: datetime,
    ) -> SkillBundleProposal:
        if not proposed_by_agent:
            raise SkillBundleWorkshopError("skill bundle proposer agent MUST be non-empty")
        bundle = parse_skill_bundle_manifest(raw_manifest)
        content_hash = hashlib.sha256(raw_manifest).hexdigest()
        proposal_id = (
            "skill-bundle-proposal:"
            + hashlib.sha256(
                f"{proposed_by_agent}\0{bundle.manifest.name}\0{content_hash}".encode()
            ).hexdigest()[:32]
        )
        proposal = await self._store.create(
            SkillBundleProposal(
                proposal_id=proposal_id,
                bundle_name=bundle.manifest.name,
                content_hash=content_hash,
                manifest=bytes(raw_manifest),
                proposed_by_agent=proposed_by_agent,
                created_at=at,
            )
        )
        await self._audit.append(
            _event("skill_bundle.proposed", proposal, actor=proposed_by_agent, at=at)
        )
        return proposal

    async def review(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> SkillBundleProposal:
        if not reviewer_id or not reason.strip():
            raise SkillBundleWorkshopError("skill bundle review requires reviewer and reason")
        if not self._authorizer.can_review(reviewer_id):
            raise SkillBundleWorkshopError("reviewer is not authorized for bundle governance")
        current = await self._store.get(proposal_id)
        if current.state is not SkillBundleProposalState.DRAFT:
            raise SkillBundleWorkshopError("only a draft skill bundle proposal can be reviewed")
        if reviewer_id == current.proposed_by_agent:
            raise SkillBundleWorkshopError("skill bundle proposer cannot self-review")
        state = SkillBundleProposalState.APPROVED if approve else SkillBundleProposalState.REJECTED
        reviewed = await self._store.transition(
            replace(
                current,
                state=state,
                reviewed_by=reviewer_id,
                review_reason=reason.strip(),
                reviewed_at=at,
            ),
            expected_state=SkillBundleProposalState.DRAFT,
        )
        if reviewed is None:
            raise SkillBundleWorkshopError("skill bundle proposal changed before review")
        await self._audit.append(
            _event(f"skill_bundle.{state.value}", reviewed, actor=reviewer_id, at=at)
        )
        return reviewed

    async def materialize(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> bytes:
        current = await self._approved(proposal_id, actor_id=actor_id)
        materialized = await self._store.transition(
            replace(current, state=SkillBundleProposalState.MATERIALIZED),
            expected_state=SkillBundleProposalState.APPROVED,
        )
        if materialized is None:
            raise SkillBundleWorkshopError("skill bundle proposal changed before materialization")
        await self._audit.append(
            _event("skill_bundle.materialized", materialized, actor=actor_id, at=at)
        )
        return bytes(materialized.manifest)

    async def promote(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
        catalog: SkillBundleCatalog,
        verifier: SkillBundleTrustVerifier,
    ) -> SkillBundleCatalog:
        current = await self._approved(proposal_id, actor_id=actor_id)
        candidate = catalog.install(current.manifest, verifier=verifier)
        materialized = await self._store.transition(
            replace(current, state=SkillBundleProposalState.MATERIALIZED),
            expected_state=SkillBundleProposalState.APPROVED,
        )
        if materialized is None:
            raise SkillBundleWorkshopError("skill bundle proposal changed before promotion")
        await self._audit.append(
            _event("skill_bundle.promoted", materialized, actor=actor_id, at=at)
        )
        return candidate

    async def _approved(self, proposal_id: str, *, actor_id: str) -> SkillBundleProposal:
        current = await self._store.get(proposal_id)
        if current.state is not SkillBundleProposalState.APPROVED:
            raise SkillBundleWorkshopError("only an approved skill bundle proposal may proceed")
        if not self._authorizer.can_review(actor_id):
            raise SkillBundleWorkshopError("actor is not authorized for bundle governance")
        return current


def _event(
    kind: str,
    proposal: SkillBundleProposal,
    *,
    actor: str,
    at: datetime,
) -> dict[str, object]:
    return {
        "action_kind": kind,
        "proposal_id": proposal.proposal_id,
        "bundle_name": proposal.bundle_name,
        "content_hash": proposal.content_hash,
        "state": proposal.state.value,
        "actor": actor,
        "timestamp": at.isoformat(),
    }


__all__ = [
    "InMemorySkillBundleProposalStore",
    "SkillBundleProposal",
    "SkillBundleProposalState",
    "SkillBundleProposalStore",
    "SkillBundleWorkshop",
    "SkillBundleWorkshopError",
]

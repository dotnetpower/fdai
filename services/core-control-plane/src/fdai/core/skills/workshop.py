"""Audited proposal queue for agent-drafted runtime skill changes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import SkillBundleTrustVerifier
from fdai.core.skills.bundle_workshop import (
    SkillBundleProposal,
    SkillBundleProposalStore,
    SkillBundleWorkshop,
)
from fdai.core.skills.catalog import (
    SkillCatalog,
    SkillCatalogError,
    SkillTrustVerifier,
    parse_skill_markdown,
)


class SkillProposalState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    MATERIALIZED = "materialized"


@dataclass(frozen=True, slots=True)
class SkillProposal:
    proposal_id: str
    skill_name: str
    content_hash: str
    markdown: bytes
    proposed_by_agent: str
    created_at: datetime
    state: SkillProposalState = SkillProposalState.DRAFT
    reviewed_by: str | None = None
    review_reason: str | None = None
    reviewed_at: datetime | None = None


class SkillProposalStore(Protocol):
    async def create(self, proposal: SkillProposal) -> SkillProposal: ...

    async def get(self, proposal_id: str) -> SkillProposal: ...

    async def transition(
        self,
        proposal: SkillProposal,
        *,
        expected_state: SkillProposalState,
    ) -> SkillProposal | None: ...

    async def list(self) -> tuple[SkillProposal, ...]: ...


class SkillWorkshopAudit(Protocol):
    async def append(self, event: Mapping[str, Any]) -> None: ...


class SkillReviewAuthorizer(Protocol):
    def can_review(self, reviewer_id: str) -> bool: ...


class SkillWorkshopError(ValueError):
    """A proposal transition was invalid or unauthorized."""


class InMemorySkillProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, SkillProposal] = {}

    async def create(self, proposal: SkillProposal) -> SkillProposal:
        prior = self._proposals.get(proposal.proposal_id)
        if prior is not None:
            if prior.content_hash == proposal.content_hash:
                return prior
            raise SkillWorkshopError("skill proposal id collision")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    async def get(self, proposal_id: str) -> SkillProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise SkillWorkshopError(f"skill proposal {proposal_id!r} was not found") from exc

    async def transition(
        self,
        proposal: SkillProposal,
        *,
        expected_state: SkillProposalState,
    ) -> SkillProposal | None:
        current = self._proposals.get(proposal.proposal_id)
        if current is None:
            raise SkillWorkshopError(f"skill proposal {proposal.proposal_id!r} was not found")
        if current.state is not expected_state:
            return None
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    async def list(self) -> tuple[SkillProposal, ...]:
        return tuple(self._proposals[key] for key in sorted(self._proposals))


class SkillWorkshop:
    """Validate drafts, require human review, and materialize without activation."""

    def __init__(
        self,
        *,
        store: SkillProposalStore,
        audit: SkillWorkshopAudit,
        authorizer: SkillReviewAuthorizer,
        bundle_store: SkillBundleProposalStore | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._authorizer = authorizer
        self._bundle_workshop = (
            SkillBundleWorkshop(store=bundle_store, audit=audit, authorizer=authorizer)
            if bundle_store is not None
            else None
        )

    async def propose_bundle(
        self,
        raw_manifest: bytes,
        *,
        proposed_by_agent: str,
        at: datetime,
    ) -> SkillBundleProposal:
        return await self._bundles().propose(
            raw_manifest,
            proposed_by_agent=proposed_by_agent,
            at=at,
        )

    async def review_bundle(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> SkillBundleProposal:
        return await self._bundles().review(
            proposal_id,
            reviewer_id=reviewer_id,
            approve=approve,
            reason=reason,
            at=at,
        )

    async def materialize_bundle(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> bytes:
        return await self._bundles().materialize(proposal_id, actor_id=actor_id, at=at)

    async def promote_bundle(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
        catalog: SkillBundleCatalog,
        verifier: SkillBundleTrustVerifier,
    ) -> SkillBundleCatalog:
        return await self._bundles().promote(
            proposal_id,
            actor_id=actor_id,
            at=at,
            catalog=catalog,
            verifier=verifier,
        )

    def _bundles(self) -> SkillBundleWorkshop:
        if self._bundle_workshop is None:
            raise SkillWorkshopError("skill bundle proposal store is not configured")
        return self._bundle_workshop

    async def propose(
        self,
        raw_markdown: bytes,
        *,
        proposed_by_agent: str,
        at: datetime,
    ) -> SkillProposal:
        if not proposed_by_agent:
            raise SkillWorkshopError("skill proposer agent MUST be non-empty")
        skill = parse_skill_markdown(raw_markdown)
        content_hash = hashlib.sha256(raw_markdown).hexdigest()
        proposal_id = (
            "skill-proposal:"
            + hashlib.sha256(
                f"{proposed_by_agent}\0{skill.manifest.name}\0{content_hash}".encode()
            ).hexdigest()[:32]
        )
        proposal = await self._store.create(
            SkillProposal(
                proposal_id=proposal_id,
                skill_name=skill.manifest.name,
                content_hash=content_hash,
                markdown=raw_markdown,
                proposed_by_agent=proposed_by_agent,
                created_at=at,
            )
        )
        await self._audit.append(_event("skill.proposed", proposal, actor=proposed_by_agent, at=at))
        return proposal

    async def review(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> SkillProposal:
        if not reviewer_id or not reason.strip():
            raise SkillWorkshopError("skill review requires reviewer and reason")
        if not self._authorizer.can_review(reviewer_id):
            raise SkillWorkshopError("reviewer is not authorized for runtime skill governance")
        current = await self._store.get(proposal_id)
        if current.state is not SkillProposalState.DRAFT:
            raise SkillWorkshopError("only a draft skill proposal can be reviewed")
        if reviewer_id == current.proposed_by_agent:
            raise SkillWorkshopError("skill proposer cannot self-review")
        state = SkillProposalState.APPROVED if approve else SkillProposalState.REJECTED
        reviewed = await self._store.transition(
            replace(
                current,
                state=state,
                reviewed_by=reviewer_id,
                review_reason=reason.strip(),
                reviewed_at=at,
            ),
            expected_state=SkillProposalState.DRAFT,
        )
        if reviewed is None:
            raise SkillWorkshopError("skill proposal changed before review")
        await self._audit.append(_event(f"skill.{state.value}", reviewed, actor=reviewer_id, at=at))
        return reviewed

    async def materialize(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> bytes:
        current = await self._store.get(proposal_id)
        if current.state is not SkillProposalState.APPROVED:
            raise SkillWorkshopError("only an approved skill proposal can be materialized")
        if not self._authorizer.can_review(actor_id):
            raise SkillWorkshopError("actor is not authorized to materialize runtime skills")
        materialized = await self._store.transition(
            replace(current, state=SkillProposalState.MATERIALIZED),
            expected_state=SkillProposalState.APPROVED,
        )
        if materialized is None:
            raise SkillWorkshopError("skill proposal changed before materialization")
        await self._audit.append(_event("skill.materialized", materialized, actor=actor_id, at=at))
        return bytes(materialized.markdown)

    async def promote(
        self,
        proposal_id: str,
        *,
        actor_id: str,
        at: datetime,
        catalog: SkillCatalog,
        verifier: SkillTrustVerifier,
    ) -> SkillCatalog:
        """Trust-verify an approved proposal and install it disabled."""
        current = await self._store.get(proposal_id)
        if current.state is not SkillProposalState.APPROVED:
            raise SkillWorkshopError("only an approved skill proposal can be promoted")
        if not self._authorizer.can_review(actor_id):
            raise SkillWorkshopError("actor is not authorized to promote runtime skills")
        try:
            promoted_catalog = catalog.install(current.markdown, verifier=verifier)
        except SkillCatalogError as exc:
            raise SkillWorkshopError(str(exc)) from exc
        materialized = await self._store.transition(
            replace(current, state=SkillProposalState.MATERIALIZED),
            expected_state=SkillProposalState.APPROVED,
        )
        if materialized is None:
            raise SkillWorkshopError("skill proposal changed before promotion")
        await self._audit.append(_event("skill.promoted", materialized, actor=actor_id, at=at))
        return promoted_catalog


def _event(kind: str, proposal: SkillProposal, *, actor: str, at: datetime) -> dict[str, object]:
    return {
        "action_kind": kind,
        "proposal_id": proposal.proposal_id,
        "skill_name": proposal.skill_name,
        "content_hash": proposal.content_hash,
        "state": proposal.state.value,
        "actor": actor,
        "timestamp": at.isoformat(),
    }


__all__ = [
    "InMemorySkillProposalStore",
    "SkillProposal",
    "SkillProposalState",
    "SkillProposalStore",
    "SkillReviewAuthorizer",
    "SkillWorkshop",
    "SkillWorkshopAudit",
    "SkillWorkshopError",
]

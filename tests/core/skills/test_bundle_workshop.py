"""SkillWorkshop governed bundle proposal tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from fdai.core.skills import InMemorySkillProposalStore, SkillWorkshop, SkillWorkshopError
from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle, encode_skill_bundle_manifest
from fdai.core.skills.bundle_workshop import (
    InMemorySkillBundleProposalStore,
    SkillBundleProposalState,
)

_NOW = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


class _Authorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return reviewer_id.startswith("owner-")


class _Verifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


def _manifest() -> bytes:
    return encode_skill_bundle_manifest(
        {
            "name": "inventory-pack",
            "version": "1.0.0",
            "description": "Reviewed inventory procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": "PRIVATE-BUNDLE-INSTRUCTION",
        }
    )


def _workshop() -> tuple[SkillWorkshop, _Audit]:
    audit = _Audit()
    return (
        SkillWorkshop(
            store=InMemorySkillProposalStore(),
            bundle_store=InMemorySkillBundleProposalStore(),
            audit=audit,
            authorizer=_Authorizer(),
        ),
        audit,
    )


async def test_bundle_proposal_requires_distinct_review_and_promotes_disabled() -> None:
    workshop, audit = _workshop()
    proposal = await workshop.propose_bundle(
        _manifest(),
        proposed_by_agent="Bragi",
        at=_NOW,
    )
    approved = await workshop.review_bundle(
        proposal.proposal_id,
        reviewer_id="owner-1",
        approve=True,
        reason="Verified members and bounds.",
        at=_NOW,
    )
    promoted = await workshop.promote_bundle(
        proposal.proposal_id,
        actor_id="owner-1",
        at=_NOW,
        catalog=SkillBundleCatalog(),
        verifier=_Verifier(),
    )

    assert approved.state is SkillBundleProposalState.APPROVED
    assert promoted.get("inventory-pack").enabled is False
    assert [event["action_kind"] for event in audit.events] == [
        "skill_bundle.proposed",
        "skill_bundle.approved",
        "skill_bundle.promoted",
    ]
    assert all("PRIVATE-BUNDLE-INSTRUCTION" not in repr(event) for event in audit.events)


async def test_bundle_proposer_cannot_self_review() -> None:
    workshop, _audit = _workshop()
    proposal = await workshop.propose_bundle(
        _manifest(),
        proposed_by_agent="owner-agent",
        at=_NOW,
    )

    with pytest.raises(ValueError, match="self-review"):
        await workshop.review_bundle(
            proposal.proposal_id,
            reviewer_id="owner-agent",
            approve=True,
            reason="Self approval.",
            at=_NOW,
        )


async def test_bundle_methods_fail_closed_without_bundle_store() -> None:
    workshop = SkillWorkshop(
        store=InMemorySkillProposalStore(),
        audit=_Audit(),
        authorizer=_Authorizer(),
    )

    with pytest.raises(SkillWorkshopError, match="not configured"):
        await workshop.propose_bundle(_manifest(), proposed_by_agent="Bragi", at=_NOW)

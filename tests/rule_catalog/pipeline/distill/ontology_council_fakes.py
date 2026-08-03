"""Deterministic fakes shared by ontology council tests."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyCouncilPolicy
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityAliasRecord,
    EntityRecord,
    LinkDeclaration,
    SourceAuthorityPolicy,
    TypePropertyDeclaration,
    VerificationContext,
)
from fdai.shared.providers.distiller import ManualDocument
from fdai.shared.providers.ontology_council import (
    CouncilClaimPacket,
    CouncilDisposition,
    CouncilModelIdentity,
    CouncilOperation,
    CouncilProperty,
    CouncilTargetKind,
    CouncilVote,
)

type VoteFactory = Callable[[CouncilClaimPacket, CouncilModelIdentity], object]

OBJECT_TEXT = "Checkout service is owned by Platform team."
LINK_TEXT = "Checkout service depends on Billing service."


@dataclass(slots=True)
class CallTracker:
    blind_started: int = 0
    blind_completed: int = 0
    revision_started: int = 0


class FakeCouncilModel:
    def __init__(
        self,
        index: int,
        initial: VoteFactory,
        *,
        revised: VoteFactory | None = None,
        tracker: CallTracker | None = None,
        delay: float = 0.0,
    ) -> None:
        self.identity = CouncilModelIdentity(
            publisher="publisher-one",
            family=f"family-{index}",
            version="1.0.0",
            deployment=f"deployment-{index}",
            binding=f"binding-{index}",
            fault_domain=f"fault-{index}",
        )
        self._initial = initial
        self._revised = revised or initial
        self._tracker = tracker or CallTracker()
        self._delay = delay
        self.blind_calls = 0
        self.revision_calls = 0

    async def blind_vote(self, packet: CouncilClaimPacket) -> CouncilVote:
        self.blind_calls += 1
        self._tracker.blind_started += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        result = self._initial(packet, self.identity)
        self._tracker.blind_completed += 1
        if isinstance(result, Exception):
            raise result
        return cast(CouncilVote, result)

    async def revise_vote(self, packet: CouncilClaimPacket, dispute: object) -> CouncilVote:
        del dispute
        self.revision_calls += 1
        self._tracker.revision_started += 1
        assert self._tracker.blind_completed == 3
        result = self._revised(packet, self.identity)
        if isinstance(result, Exception):
            raise result
        return cast(CouncilVote, result)


def document(text: str = OBJECT_TEXT) -> ManualDocument:
    return ManualDocument(
        doc_id="manual-1",
        text=text,
        source_ref="doc:manual-1",
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        metadata={
            "access_policy_ref": "access:manuals",
            "revision": "rev-1",
            "source_format": "markdown",
        },
    )


def context() -> VerificationContext:
    return VerificationContext(
        ontology_release="a" * 64,
        current_graph_revision="graph-1",
        object_types=frozenset({"BusinessService", "Team"}),
        links=(LinkDeclaration("service_depends_on", "BusinessService", "BusinessService"),),
        entities=(
            EntityRecord("service:billing", "BusinessService"),
            EntityRecord("service:checkout", "BusinessService"),
            EntityRecord("team:platform", "Team"),
        ),
        aliases=(EntityAliasRecord("Checkout", "service:checkout"),),
        source_policies=(SourceAuthorityPolicy("doc:manual-1", frozenset(AuthorityClass), 10),),
        claim_text=(),
        object_properties=(
            TypePropertyDeclaration("BusinessService", ("owner_ref",)),
            TypePropertyDeclaration("Team", ()),
        ),
        link_properties=(TypePropertyDeclaration("service_depends_on", ()),),
    )


def policy(*, timeout: float = 1.0, max_claims: int = 256) -> OntologyCouncilPolicy:
    return OntologyCouncilPolicy(
        policy_id="ontology-council-test",
        version="1.0.0",
        prompt_digest="b" * 64,
        schema_digest="c" * 64,
        call_timeout_seconds=timeout,
        max_claims=max_claims,
    )


def object_vote(
    packet: CouncilClaimPacket,
    identity: CouncilModelIdentity,
    *,
    target_type: str = "BusinessService",
    target_identity: str = "service:checkout",
    property_name: str = "owner_ref",
) -> CouncilVote:
    return CouncilVote(
        model_identity=identity,
        claim_id=packet.claim_id,
        citation_digest=packet.citation_digest,
        disposition=CouncilDisposition.PROPOSE,
        operation=CouncilOperation.UPDATE,
        target_kind=CouncilTargetKind.OBJECT,
        target_type=target_type,
        target_identity=target_identity,
        authority=packet.authority,
        properties=(CouncilProperty(property_name, "team:platform"),),
    )


def link_vote(packet: CouncilClaimPacket, identity: CouncilModelIdentity) -> CouncilVote:
    return CouncilVote(
        model_identity=identity,
        claim_id=packet.claim_id,
        citation_digest=packet.citation_digest,
        disposition=CouncilDisposition.PROPOSE,
        operation=CouncilOperation.UPDATE,
        target_kind=CouncilTargetKind.LINK,
        target_type="service_depends_on",
        target_identity="service:checkout",
        authority=packet.authority,
        from_identity="service:checkout",
        to_identity="service:billing",
    )


def unsupported_vote(packet: CouncilClaimPacket, identity: CouncilModelIdentity) -> CouncilVote:
    return CouncilVote(
        model_identity=identity,
        claim_id=packet.claim_id,
        citation_digest=packet.citation_digest,
        disposition=CouncilDisposition.UNSUPPORTED,
    )


def models(
    factories: tuple[VoteFactory, VoteFactory, VoteFactory],
    *,
    revised: tuple[VoteFactory, VoteFactory, VoteFactory] | None = None,
    tracker: CallTracker | None = None,
    delays: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[FakeCouncilModel, FakeCouncilModel, FakeCouncilModel]:
    revisions = revised or factories
    shared_tracker = tracker or CallTracker()
    return tuple(
        FakeCouncilModel(
            index,
            factories[index - 1],
            revised=revisions[index - 1],
            tracker=shared_tracker,
            delay=delays[index - 1],
        )
        for index in (1, 2, 3)
    )  # type: ignore[return-value]

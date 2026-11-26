"""Pure claim-packet and strict candidate conversion for ontology councils."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.ontology_claims import claim_text_records
from fdai.rule_catalog.pipeline.distill.ontology_models import ClaimUnit, stable_digest
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.shared.providers.distiller import CandidateKind, DistilledCandidate, ManualDocument
from fdai.shared.providers.ontology_council import (
    CouncilAlias,
    CouncilClaimPacket,
    CouncilEntity,
    CouncilLinkDeclaration,
    CouncilObjectDeclaration,
    CouncilOperation,
    CouncilTargetKind,
    CouncilVote,
)


def build_council_claim_packet(
    claim: ClaimUnit,
    source_assertion: str,
    context: VerificationContext,
) -> CouncilClaimPacket:
    object_properties = {
        item.target_type: item.property_names for item in context.object_properties
    }
    link_properties = {item.target_type: item.property_names for item in context.link_properties}
    return CouncilClaimPacket(
        claim_id=claim.claim_id,
        source_assertion=source_assertion,
        source_ref=claim.evidence.source_ref,
        source_lines=(claim.evidence.line_start, claim.evidence.line_end),
        content_sha256=claim.evidence.content_sha256,
        citation_digest=claim.evidence.text_sha256,
        authority=claim.authority.value,
        ontology_release=context.ontology_release,
        graph_revision=context.current_graph_revision,
        object_types=tuple(
            CouncilObjectDeclaration(name, object_properties.get(name, ()))
            for name in sorted(context.object_types)
        ),
        links=tuple(
            CouncilLinkDeclaration(
                item.name,
                item.from_type,
                item.to_type,
                link_properties.get(item.name, ()),
            )
            for item in sorted(context.links, key=lambda item: item.name)
        ),
        entities=tuple(
            CouncilEntity(item.identity, item.object_type)
            for item in sorted(context.entities, key=lambda item: item.identity)
        ),
        aliases=tuple(
            CouncilAlias(item.alias, item.identity)
            for item in sorted(
                context.aliases,
                key=lambda item: (" ".join(item.alias.split()).casefold(), item.identity),
            )
        ),
    )


def candidate_from_council_vote(
    document: ManualDocument,
    claim: ClaimUnit,
    vote: CouncilVote,
) -> DistilledCandidate:
    if (
        vote.operation is None
        or vote.target_kind is None
        or vote.target_type is None
        or vote.target_identity is None
        or vote.authority is None
    ):
        raise ValueError("council candidate requires a complete proposal vote")
    operation: CouncilOperation = vote.operation
    target_kind: CouncilTargetKind = vote.target_kind
    target_type = vote.target_type
    target_identity = vote.target_identity
    authority = vote.authority
    body: dict[str, object] = {
        "operation": operation.value,
        "target_type": target_type,
        "target_identity": target_identity,
        "authority": authority,
        "source_assertion": _source_assertion(document, claim),
        "properties": {item.name: item.value for item in vote.properties},
    }
    if target_kind is CouncilTargetKind.LINK:
        body["from_identity"] = vote.from_identity
        body["to_identity"] = vote.to_identity
    return DistilledCandidate(
        kind=(
            CandidateKind.ONTOLOGY_OBJECT
            if target_kind is CouncilTargetKind.OBJECT
            else CandidateKind.ONTOLOGY_LINK
        ),
        candidate_id="council-"
        + stable_digest({"claim_id": claim.claim_id, "fingerprint": vote.semantic_fingerprint}),
        source_ref=claim.evidence.source_ref,
        source_section=claim.evidence.structural_locator,
        source_lines=(claim.evidence.line_start, claim.evidence.line_end),
        content_sha=claim.evidence.content_sha256,
        body=body,
    )


def _source_assertion(document: ManualDocument, claim: ClaimUnit) -> str:
    return dict(claim_text_records(document, (claim,)))[claim.claim_id]


__all__ = ["build_council_claim_packet", "candidate_from_council_vote"]

"""Grounded reviewed interpretation contracts inside the independent document Worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, get_args

from fdai_service_contracts import DocumentEnvelope, HandoverMapping
from fdai_service_contracts.adaptive_answer import AdaptiveAgentName
from fdai_service_contracts.handover import HandoverModelReview, handover_model_proposal_digest


@dataclass(frozen=True, slots=True)
class ReviewedHandoverInterpretation:
    mappings: tuple[HandoverMapping, ...] = ()
    review: HandoverModelReview | None = None
    unavailable_reason: str | None = None


class HandoverInterpreter(Protocol):
    async def interpret(self, envelope: DocumentEnvelope) -> ReviewedHandoverInterpretation: ...


def handover_proposal_digest(mappings: tuple[HandoverMapping, ...]) -> str:
    return handover_model_proposal_digest(mappings)


def validate_interpretation(
    result: ReviewedHandoverInterpretation,
    envelope: DocumentEnvelope,
    *,
    max_candidates: int,
) -> bool:
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates < 1
        or result.unavailable_reason is not None
        or not result.mappings
    ):
        return False
    review = result.review
    if (
        review is None
        or review.source_sha256 != envelope.source_sha256
        or review.reviewed_mapping_count != len(result.mappings)
        or review.proposal_sha256 != handover_proposal_digest(result.mappings)
        or len(result.mappings) > max_candidates
    ):
        return False
    lines = tuple(line for unit in envelope.units for line in unit.text.splitlines())
    identities: set[tuple[str, str, str]] = set()
    for mapping in result.mappings:
        identity = (
            mapping.agent_name,
            mapping.person.display_name.strip().casefold(),
            mapping.responsibility.value,
        )
        if (
            mapping.source != "model"
            or mapping.person.oid is not None
            or mapping.agent_name not in get_args(AdaptiveAgentName)
            or identity in identities
            or not mapping.person.display_name.strip()
            or not all(
                citation.doc_id == str(envelope.document_id)
                and 1 <= citation.line <= len(lines)
                and bool(citation.quote.strip())
                and citation.quote in lines[citation.line - 1]
                for citation in mapping.citations
            )
            or not any(
                mapping.person.display_name in citation.quote for citation in mapping.citations
            )
        ):
            return False
        identities.add(identity)
    return True

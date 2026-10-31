"""Bounded exact-evidence admission shared by RCA generation boundaries."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.rca.contract import Citation, CitationKind

MAX_RCA_CITATIONS = 100
MAX_RCA_REFERENCE_CHARS = 1024


def admitted_citations(citations: Sequence[Citation]) -> tuple[Citation, ...] | None:
    """Canonicalize complete evidence, holding invalid or conflicting identities."""
    if not 1 <= len(citations) <= MAX_RCA_CITATIONS:
        return None
    by_identity: dict[tuple[CitationKind, str], Citation] = {}
    for citation in citations:
        if (
            not citation.ref.strip()
            or citation.ref != citation.ref.strip()
            or len(citation.ref) > MAX_RCA_REFERENCE_CHARS
            or not citation.ref.isprintable()
        ):
            return None
        identity = (citation.kind, citation.ref)
        previous = by_identity.get(identity)
        if previous is not None and previous != citation:
            return None
        by_identity[identity] = citation
    return tuple(
        sorted(by_identity.values(), key=lambda citation: (citation.kind.value, citation.ref))
    )


def resolve_citation(reference: str, candidates: Sequence[Citation]) -> Citation | None:
    """Resolve both aliases together so a literal ref cannot shadow a qualified ref."""
    if not isinstance(reference, str):
        return None
    normalized_reference = reference.strip()
    if not normalized_reference:
        return None
    matches: list[Citation] = []
    seen_identities: set[tuple[CitationKind, str]] = set()
    for citation in candidates:
        if normalized_reference in (citation.ref, f"{citation.kind.value}:{citation.ref}"):
            identity = (citation.kind, citation.ref)
            if identity not in seen_identities:
                seen_identities.add(identity)
                matches.append(citation)
    return matches[0] if len(matches) == 1 else None

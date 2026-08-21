"""Structural claim inventory and completeness accounting.

Every prose unit is inventoried with provenance but remains semantically
unclassified until a model-extracted candidate is reconciled.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping, Sequence

from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimDisposition,
    ClaimKind,
    ClaimResolution,
    ClaimUnit,
    SourceEvidence,
)
from fdai.shared.providers.distiller import DistilledCandidate, ManualDocument

_FENCE_RE = re.compile(r"^(?P<marker>`{3,}|~{3,})")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_INLINE_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_INLINE_SHORTCODE = re.compile(r"\{\{[%<].*?[>%]\}\}")
_INLINE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_LIST_PREFIX = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_MAX_DOCUMENT_BYTES = 5_000_000


def inventory_claims(
    document: ManualDocument,
    *,
    source_ranges: Sequence[tuple[int, int]] | None = None,
) -> tuple[ClaimUnit, ...]:
    """Return stable structural units, optionally limited to model-cited lines."""
    if len(document.text.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
        raise ValueError("ontology claim inventory document exceeds the byte limit")
    content_sha = document_content_digest(document)
    revision = document.metadata.get("revision", content_sha)
    provenance_by_line = {item.line_number: item for item in document.line_provenance}
    selected_lines = (
        None
        if source_ranges is None
        else frozenset(
            line_number for start, end in source_ranges for line_number in range(start, end + 1)
        )
    )
    claims: list[ClaimUnit] = []
    fence_marker: str | None = None

    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        if selected_lines is not None and line_number not in selected_lines:
            continue
        stripped = raw_line.strip()
        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            marker = fence.group("marker")[0]
            if fence_marker is None:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = None
            continue
        if fence_marker is not None or not stripped or stripped.startswith("#"):
            continue

        semantic_line = _semantic_text(_LIST_PREFIX.sub("", stripped))
        if not semantic_line:
            continue
        for unit_ordinal, text in enumerate(_split_claim_units(semantic_line), start=1):
            signals = (ClaimKind.UNCLASSIFIED,)
            kind = ClaimKind.UNCLASSIFIED
            authority = AuthorityClass.UNCLASSIFIED
            text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            claim_material = "\0".join(
                [document.source_ref, content_sha, str(line_number), str(unit_ordinal), text_sha]
            )
            claim_id = "claim-" + hashlib.sha256(claim_material.encode("utf-8")).hexdigest()
            provenance = provenance_by_line.get(line_number)
            claims.append(
                ClaimUnit(
                    claim_id=claim_id,
                    kind=kind,
                    authority=authority,
                    evidence=SourceEvidence(
                        source_ref=document.source_ref,
                        document_id=document.doc_id,
                        document_revision=revision,
                        content_sha256=content_sha,
                        line_start=line_number,
                        line_end=line_number,
                        text_sha256=text_sha,
                        source_format=(
                            provenance.source_format
                            if provenance is not None
                            else document.metadata.get("source_format", "manual")
                        ),
                        structural_unit_id=(
                            provenance.unit_id if provenance is not None else f"line-{line_number}"
                        ),
                        structural_locator=(
                            provenance.locator if provenance is not None else f"line:{line_number}"
                        ),
                    ),
                    critical=False,
                    signals=signals,
                )
            )

    return tuple(claims)


def reconcile_claims(
    claims: Sequence[ClaimUnit],
    candidates: Sequence[DistilledCandidate],
    *,
    exact_candidate_claims: Mapping[str, str] | None = None,
) -> tuple[ClaimResolution, ...]:
    """Account for every claim using candidate source-line coverage."""
    resolutions: list[ClaimResolution] = []
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("distilled candidate ids MUST be unique for claim reconciliation")
    exact = exact_candidate_claims or {}
    if not set(exact).issubset(candidate_ids):
        raise ValueError("exact candidate claim mapping MUST reference known candidates")
    if not set(exact.values()).issubset({claim.claim_id for claim in claims}):
        raise ValueError("exact candidate claim mapping MUST reference known claims")

    for claim in claims:
        matching = tuple(
            candidate.candidate_id
            for candidate in candidates
            if (
                exact.get(candidate.candidate_id) == claim.claim_id
                if candidate.candidate_id in exact
                else candidate.source_ref == claim.evidence.source_ref
                and candidate.source_lines[0] <= claim.evidence.line_start
                and candidate.source_lines[1] >= claim.evidence.line_end
            )
        )
        if matching:
            resolutions.append(
                ClaimResolution(
                    claim_id=claim.claim_id,
                    disposition=ClaimDisposition.MAPPED,
                    candidate_ids=matching,
                )
            )
        else:
            resolutions.append(
                ClaimResolution(
                    claim_id=claim.claim_id,
                    disposition=ClaimDisposition.NEEDS_REVIEW,
                    reason_code="unmapped_claim",
                )
            )
    return tuple(resolutions)


def claim_text_records(
    document: ManualDocument,
    claims: Sequence[ClaimUnit],
) -> tuple[tuple[str, str], ...]:
    """Reconstruct ephemeral claim text for verification without storing it."""
    by_line: dict[int, list[str]] = {}
    fence_marker: str | None = None
    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        stripped = raw_line.strip()
        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            marker = fence.group("marker")[0]
            if fence_marker is None:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = None
            continue
        if fence_marker is not None or not stripped or stripped.startswith("#"):
            continue
        semantic_line = _semantic_text(_LIST_PREFIX.sub("", stripped))
        if semantic_line:
            by_line[line_number] = list(_split_claim_units(semantic_line))

    records: list[tuple[str, str]] = []
    for claim in claims:
        candidates = by_line.get(claim.evidence.line_start, [])
        matched = [
            text
            for text in candidates
            if hashlib.sha256(text.encode("utf-8")).hexdigest() == claim.evidence.text_sha256
        ]
        if not matched:
            raise ValueError("inventoried claim text MUST remain reconstructable")
        records.append((claim.claim_id, matched[0]))
    return tuple(records)


def _split_claim_units(line: str) -> tuple[str, ...]:
    return tuple(unit.strip() for unit in _SENTENCE.split(line) if unit.strip())


def _semantic_text(text: str) -> str:
    without_comments = _INLINE_COMMENT.sub(" ", text)
    without_shortcodes = _INLINE_SHORTCODE.sub(" ", without_comments)
    without_tags = _INLINE_TAG.sub(" ", without_shortcodes)
    return " ".join(html.unescape(without_tags).split())


def document_content_digest(document: ManualDocument) -> str:
    """Return and verify the exact SHA-256 digest of document text."""
    computed = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
    if not document.content_sha:
        return computed
    if re.fullmatch(r"[a-f0-9]{64}", document.content_sha) is None:
        raise ValueError("ManualDocument.content_sha MUST be a lowercase SHA-256 digest")
    if document.content_sha != computed:
        raise ValueError("ManualDocument.content_sha MUST match the provided document text")
    return document.content_sha


__all__ = [
    "claim_text_records",
    "document_content_digest",
    "inventory_claims",
    "reconcile_claims",
]

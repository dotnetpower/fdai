"""Validated immutable document references for web chat turns."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fdai.delivery.operator_api.application.conversation.verification import AnswerVerification


def with_document_evidence(
    view_context: dict[str, Any],
    evidence_refs: tuple[str, ...],
) -> dict[str, Any]:
    if not evidence_refs:
        return view_context
    enriched = dict(view_context)
    enriched["_document_evidence"] = {
        "authority": "governed_document_ingestion",
        "evidence_refs": list(evidence_refs),
    }
    return enriched


def merge_document_verification(
    verification: AnswerVerification,
    evidence_refs: tuple[str, ...],
) -> AnswerVerification:
    if not evidence_refs:
        return verification
    return replace(
        verification,
        evidence_refs=tuple(dict.fromkeys((*verification.evidence_refs, *evidence_refs))),
    )


__all__ = [
    "merge_document_verification",
    "with_document_evidence",
]

"""Validated immutable document references for web chat turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol
from uuid import UUID

from fdai.delivery.read_api.routes.chat_verification import AnswerVerification
from fdai.shared.providers.document_ingestion import ChatDocumentRef

_MAX_DOCUMENT_REFS = 8


class ChatDocumentEvidenceResolver(Protocol):
    async def resolve(
        self,
        *,
        principal_id: str,
        references: tuple[ChatDocumentRef, ...],
    ) -> tuple[str, ...]: ...


def parse_document_refs(body: Mapping[str, Any]) -> tuple[ChatDocumentRef, ...]:
    """Validate web-chat references without accepting file bytes or URLs."""
    raw = body.get("document_refs", [])
    if not isinstance(raw, list):
        raise ValueError("document_refs MUST be a list")
    if len(raw) > _MAX_DOCUMENT_REFS:
        raise ValueError(f"document_refs exceeds cap ({len(raw)} > {_MAX_DOCUMENT_REFS})")
    references: list[ChatDocumentRef] = []
    seen: set[tuple[UUID, UUID]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each document_refs entry MUST be an object")
        try:
            reference = ChatDocumentRef(
                document_id=UUID(str(item.get("document_id", ""))),
                version_id=UUID(str(item.get("version_id", ""))),
            )
        except ValueError as exc:
            raise ValueError("document_refs ids MUST be UUIDs") from exc
        key = (reference.document_id, reference.version_id)
        if key not in seen:
            seen.add(key)
            references.append(reference)
    return tuple(references)


async def resolve_document_refs(
    *,
    body: Mapping[str, Any],
    principal_id: str,
    resolver: ChatDocumentEvidenceResolver | None,
) -> tuple[str, ...]:
    references = parse_document_refs(body)
    if not references:
        return ()
    if resolver is None:
        raise RuntimeError("web chat document evidence is unavailable")
    resolved = await resolver.resolve(principal_id=principal_id, references=references)
    expected = tuple(
        f"doc:{reference.document_id}:{reference.version_id}" for reference in references
    )
    if resolved != expected:
        raise RuntimeError("web chat document evidence resolver returned invalid citations")
    return resolved


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
    "ChatDocumentEvidenceResolver",
    "ChatDocumentRef",
    "merge_document_verification",
    "parse_document_refs",
    "resolve_document_refs",
    "with_document_evidence",
]

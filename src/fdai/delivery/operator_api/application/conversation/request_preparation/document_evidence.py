"""Validated immutable document references for chat request preparation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from fdai.shared.providers.document_ingestion import ChatDocumentRef

_MAX_DOCUMENT_REFS = 8


class ChatDocumentEvidenceResolver(Protocol):
    """Resolve authorized document references into canonical evidence refs."""

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
    """Resolve validated document references without accepting provider output drift."""

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


__all__ = [
    "ChatDocumentEvidenceResolver",
    "ChatDocumentRef",
    "parse_document_refs",
    "resolve_document_refs",
]

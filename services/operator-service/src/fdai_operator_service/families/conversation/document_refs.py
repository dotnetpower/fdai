"""Principal-scoped `document_refs` parsing and resolution for chat turns.

The Operator API never accepts multipart files, raw bytes, storage URLs, or
channel attachment ids. A web chat turn may reference documents that the same
authenticated principal already uploaded through the ingestion gateway, and the
server resolves those references before semantic processing.

Resolution fails closed. Invalid syntax is a client error, a missing resolver is
an unavailable deployment, and every unauthorized, missing, held, failed, or
deleted version returns one identical denial so document existence is never
disclosed. A substituted, reordered, duplicated, or malformed provider result is
rejected before it can reach view context or terminal verification.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    JsonValue,
    PrincipalScope,
)
from fdai_service_contracts import (
    SemanticDocumentContext,
    SemanticDocumentContextSource,
    semantic_document_context_digest,
)

MAX_DOCUMENT_REFS = 8
ACCESS_DENIED_MESSAGE = "requested document version is not available to this principal"
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class DocumentRefSyntaxError(ConversationBoundaryError):
    """Malformed client input; the route answers 400."""

    def __init__(self, message: str) -> None:
        super().__init__(400, "invalid_document_refs", message)


class DocumentRefAccessDeniedError(ConversationBoundaryError):
    """Uniform denial that never discloses document existence."""

    def __init__(self) -> None:
        super().__init__(403, "document_ref_denied", ACCESS_DENIED_MESSAGE)


class DocumentRefResolverUnavailableError(ConversationBoundaryError):
    """No resolver is bound; the route answers 501."""

    def __init__(self, message: str = "document reference resolution is not implemented") -> None:
        super().__init__(501, "document_refs_unsupported", message)


class DocumentRefResolutionFailedError(ConversationBoundaryError):
    """The resolver failed; fail closed without leaking provider internals."""

    def __init__(self) -> None:
        super().__init__(502, "document_ref_unavailable", "document reference resolution failed")


class DocumentRefIntegrityError(ConversationBoundaryError):
    """The resolver returned citations that do not match the request."""

    def __init__(self, message: str) -> None:
        super().__init__(502, "document_ref_integrity", message)


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """One requested document version reference."""

    document_id: UUID
    version_id: UUID

    @property
    def citation(self) -> str:
        return f"doc:{self.document_id}:{self.version_id}"


class DocumentRefResolver(Protocol):
    """Re-read authoritative metadata for the authenticated principal only."""

    async def resolve(
        self,
        *,
        principal_id: str,
        refs: Sequence[DocumentRef],
    ) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class ResolvedDocumentAuthorization:
    """Bind ordered citations to one current server-owned authorization read."""

    citations: tuple[str, ...]
    authorization_digest: str

    def __post_init__(self) -> None:
        if not self.citations or len(self.citations) > MAX_DOCUMENT_REFS:
            raise ValueError("resolved document citations are outside the bounded count")
        if len(self.citations) != len(set(self.citations)):
            raise ValueError("resolved document citations MUST be unique")
        if _DIGEST.fullmatch(self.authorization_digest) is None:
            raise ValueError("resolved document authorization digest is invalid")


class DocumentContextResolver(Protocol):
    """Reauthorize exact Web references and attest the current metadata read."""

    async def resolve_context(
        self,
        *,
        principal_id: str,
        principal_groups: frozenset[str],
        refs: Sequence[DocumentRef],
    ) -> ResolvedDocumentAuthorization: ...


def parse_document_refs(value: JsonValue | None) -> tuple[DocumentRef, ...]:
    """Parse the bounded `document_refs` field from one chat request body."""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise DocumentRefSyntaxError("document_refs MUST be a list")
    if len(value) > MAX_DOCUMENT_REFS:
        raise DocumentRefSyntaxError(
            f"document_refs MUST contain at most {MAX_DOCUMENT_REFS} references"
        )
    refs: list[DocumentRef] = []
    seen: set[tuple[UUID, UUID]] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise DocumentRefSyntaxError("each document ref MUST be an object")
        if set(entry) != {"document_id", "version_id"}:
            raise DocumentRefSyntaxError(
                "each document ref MUST carry exactly document_id and version_id"
            )
        ref = DocumentRef(
            document_id=_uuid("document_id", entry["document_id"]),
            version_id=_uuid("version_id", entry["version_id"]),
        )
        key = (ref.document_id, ref.version_id)
        if key in seen:
            raise DocumentRefSyntaxError("document_refs MUST be unique")
        seen.add(key)
        refs.append(ref)
    return tuple(refs)


async def resolve_document_refs(
    *,
    scope: PrincipalScope,
    refs: Sequence[DocumentRef],
    resolver: DocumentRefResolver | None,
) -> tuple[str, ...]:
    """Return ordered canonical citations for authorized references."""

    if not refs:
        return ()
    if resolver is None:
        raise DocumentRefResolverUnavailableError("no document reference resolver is bound")
    try:
        resolved = await resolver.resolve(principal_id=scope.subject_id, refs=tuple(refs))
    except DocumentRefAccessDeniedError:
        raise
    except ConversationBoundaryError as exc:
        raise DocumentRefAccessDeniedError() from exc
    except Exception as exc:  # noqa: BLE001 - never surface provider internals to the caller
        raise DocumentRefResolutionFailedError() from exc
    citations = tuple(resolved)
    expected = tuple(ref.citation for ref in refs)
    if len(citations) != len(expected):
        raise DocumentRefAccessDeniedError()
    if citations != expected:
        raise DocumentRefIntegrityError(
            "resolver returned substituted, reordered, or malformed citations"
        )
    return citations


async def resolve_web_document_context(
    *,
    scope: PrincipalScope,
    refs: Sequence[DocumentRef],
    conversation_ref: str,
    resolver: DocumentContextResolver | None,
) -> SemanticDocumentContext | None:
    """Reauthorize Web refs and bind them to the authenticated conversation."""

    if not refs:
        return None
    if not conversation_ref.strip() or len(conversation_ref) > 256:
        raise DocumentRefSyntaxError(
            "session_id MUST be a bounded non-empty string when document_refs are present"
        )
    if resolver is None:
        raise DocumentRefResolverUnavailableError("no document context resolver is bound")
    try:
        resolved = await resolver.resolve_context(
            principal_id=scope.subject_id,
            principal_groups=scope.groups,
            refs=tuple(refs),
        )
    except DocumentRefAccessDeniedError:
        raise
    except ConversationBoundaryError as exc:
        raise DocumentRefAccessDeniedError() from exc
    except Exception as exc:  # noqa: BLE001 - never disclose provider internals
        raise DocumentRefResolutionFailedError() from exc
    expected = tuple(ref.citation for ref in refs)
    if resolved.citations != expected:
        raise DocumentRefIntegrityError(
            "resolver returned substituted, reordered, or malformed citations"
        )
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "source": SemanticDocumentContextSource.WEB_REFERENCE,
        "principal_ref": scope.subject_id,
        "conversation_ref": conversation_ref,
        "citations": resolved.citations,
        "authorization_digest": resolved.authorization_digest,
        "receipt_digests": (),
        "execution_authority": False,
    }
    provisional = SemanticDocumentContext.model_construct(
        schema_version="1.0.0",
        source=SemanticDocumentContextSource.WEB_REFERENCE,
        principal_ref=scope.subject_id,
        conversation_ref=conversation_ref,
        citations=resolved.citations,
        authorization_digest=resolved.authorization_digest,
        receipt_digests=(),
        context_digest="sha256:" + "0" * 64,
        execution_authority=False,
    )
    return SemanticDocumentContext.model_validate(
        {**material, "context_digest": semantic_document_context_digest(provisional)}
    )


def _uuid(name: str, value: JsonValue) -> UUID:
    if not isinstance(value, str):
        raise DocumentRefSyntaxError(f"{name} MUST be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise DocumentRefSyntaxError(f"{name} MUST be a UUID string") from exc
    if str(parsed) != value.lower():
        raise DocumentRefSyntaxError(f"{name} MUST be a canonical hyphenated UUID string")
    return parsed


__all__ = [
    "ACCESS_DENIED_MESSAGE",
    "MAX_DOCUMENT_REFS",
    "DocumentRef",
    "DocumentRefAccessDeniedError",
    "DocumentRefIntegrityError",
    "DocumentRefResolver",
    "DocumentRefResolutionFailedError",
    "DocumentRefResolverUnavailableError",
    "DocumentRefSyntaxError",
    "DocumentContextResolver",
    "ResolvedDocumentAuthorization",
    "parse_document_refs",
    "resolve_document_refs",
    "resolve_web_document_context",
]

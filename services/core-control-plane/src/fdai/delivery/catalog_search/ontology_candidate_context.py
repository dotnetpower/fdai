"""Lossless offline context preparation, not a proposer, promotion, or answer capability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.core.ontology_platform import QueryManifest

from .generation import SemanticGenerationBuild
from .ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    _candidate_proposal_content,
    _selection_context_document,
)
from .ontology_snapshot_store import OntologyStagedProjection
from .ontology_snapshot_validation import OntologySnapshotValidation

CONTEXT_PROTOCOL: Literal["typed-selection-context-transport.v1"] = (
    "typed-selection-context-transport.v1"
)
_MAX_CONTEXT_BYTES = 8 * 1024 * 1024
_MAX_PAGES = 512
_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ContextFailureReason = Literal[
    "invalid_source",
    "context_budget_exceeded",
    "page_budget_exceeded",
    "binding_changed",
    "context_corrupt",
    "request_budget_exceeded",
]


class CandidateContextError(ValueError):
    """A bounded preparation failure, with no partial payload or qualification authority."""

    def __init__(self, reason: ContextFailureReason) -> None:
        self.reason = reason
        super().__init__(f"candidate context preparation failed: {reason}")


class _ContextRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class CandidateContextLimits(_ContextRecord):
    max_context_bytes: int = Field(default=_MAX_CONTEXT_BYTES, ge=1, le=_MAX_CONTEXT_BYTES)
    max_page_bytes: int = Field(default=65536, ge=1024, le=65536)

    @property
    def fragment_bytes(self) -> int:
        return (self.max_page_bytes - 256) // 2


class CandidateContextBinding(_ContextRecord):
    protocol: Literal["typed-selection-context-transport.v1"] = CONTEXT_PROTOCOL
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_binding_digest: _Digest
    data_handling_policy_digest: _Digest
    query_digest: _Digest
    manifest_digest: _Digest
    snapshot_digest: _Digest
    generation_digest: _Digest
    source_generation: str = Field(min_length=1, max_length=256)
    source_projection_digest: _Digest
    source_validation_digest: _Digest


class CandidateContextPage(_ContextRecord):
    ordinal: int = Field(ge=0, lt=_MAX_PAGES)
    fragment: str = Field(min_length=1, max_length=65536)
    page_digest: _Digest


class CandidateProposalContext(_ContextRecord):
    """Immutable transport fragments. Never interpret a fragment as a semantic batch."""

    authority: Literal["transport_only"] = "transport_only"
    execution_authority: Literal[False] = False
    binding: CandidateContextBinding
    limits: CandidateContextLimits
    document_count: int = Field(ge=1, le=20000)
    payload_bytes: int = Field(ge=1, le=_MAX_CONTEXT_BYTES)
    payload_digest: _Digest
    pages: tuple[CandidateContextPage, ...] = Field(min_length=1, max_length=_MAX_PAGES)
    context_digest: _Digest


def prepare_candidate_proposal_context(
    *,
    query: str,
    manifest: QueryManifest,
    build: SemanticGenerationBuild,
    staged: OntologyStagedProjection,
    source_revision: str,
    model_binding: OntologyCandidateModelBinding,
    data_handling_policy_digest: str,
    source_validation: OntologySnapshotValidation,
    limits: CandidateContextLimits | None = None,
) -> CandidateProposalContext:
    """Prepare the complete finite domain without invoking a model or changing runtime state.

    Pins are supplied by the caller, not attested here. This package cannot establish model
    qualification, source admission, current graph freshness, or approval. Limits apply to
    canonical escaped bytes, including every property and catalog entry.
    """
    limits = limits or CandidateContextLimits()
    binding, encoded, document_count = _current_context(
        query=query,
        manifest=manifest,
        build=build,
        staged=staged,
        source_revision=source_revision,
        model_binding=model_binding,
        data_handling_policy_digest=data_handling_policy_digest,
        source_validation=source_validation,
        limits=limits,
    )
    # ASCII canonical text expands by at most two when embedded in a fragment envelope.
    fragment_bytes = (limits.max_page_bytes - 256) // 2
    if (len(encoded) + fragment_bytes - 1) // fragment_bytes > _MAX_PAGES:
        raise CandidateContextError("page_budget_exceeded")
    pages = []
    for ordinal, start in enumerate(range(0, len(encoded), fragment_bytes)):
        fragment = encoded[start : start + fragment_bytes]
        digest = _page_digest(ordinal, fragment, limits)
        pages.append(CandidateContextPage(ordinal=ordinal, fragment=fragment, page_digest=digest))
    context = CandidateProposalContext(
        binding=binding,
        limits=limits,
        document_count=document_count,
        payload_bytes=len(encoded),
        payload_digest=_text_digest(encoded),
        pages=tuple(pages),
        context_digest="sha256:" + "0" * 64,
    )
    return context.model_copy(update={"context_digest": _context_digest(context)})


def restore_candidate_proposal_context(
    context: CandidateProposalContext,
    *,
    query: str,
    manifest: QueryManifest,
    build: SemanticGenerationBuild,
    staged: OntologyStagedProjection,
    source_revision: str,
    model_binding: OntologyCandidateModelBinding,
    data_handling_policy_digest: str,
    source_validation: OntologySnapshotValidation,
    limits: CandidateContextLimits | None = None,
) -> dict[str, object]:
    """Release one complete payload only after comparison with independent current inputs.

    The caller supplies trusted expected inputs and budgets rather than taking them from the
    package. No partial payload is returned after drift, corruption, or an exceeded ceiling.
    The result deliberately has no legacy input_digest or executable selection.
    """
    limits = limits or CandidateContextLimits()
    try:
        CandidateProposalContext.model_validate(context.model_dump())
    except ValidationError:
        raise CandidateContextError("context_corrupt") from None
    binding, expected, document_count = _current_context(
        query=query,
        manifest=manifest,
        build=build,
        staged=staged,
        source_revision=source_revision,
        model_binding=model_binding,
        data_handling_policy_digest=data_handling_policy_digest,
        source_validation=source_validation,
        limits=limits,
    )
    if context.binding != binding or context.limits != limits:
        raise CandidateContextError("binding_changed")
    if (
        context.document_count != document_count
        or context.payload_bytes != len(expected)
        or context.payload_digest != _text_digest(expected)
    ):
        raise CandidateContextError("context_corrupt")
    total = 0
    fragments = []
    for ordinal, page in enumerate(context.pages):
        if page.ordinal != ordinal or page.page_digest != _page_digest(
            ordinal, page.fragment, limits
        ):
            raise CandidateContextError("context_corrupt")
        total += len(page.fragment.encode("utf-8"))
        if total > limits.max_context_bytes:
            raise CandidateContextError("context_budget_exceeded")
        fragments.append(page.fragment)
    encoded = "".join(fragments)
    if encoded != expected or _context_digest(context) != context.context_digest:
        raise CandidateContextError("context_corrupt")
    return json.loads(encoded)  # type: ignore[no-any-return]


def _current_context(
    *,
    query: str,
    manifest: QueryManifest,
    build: SemanticGenerationBuild,
    staged: OntologyStagedProjection,
    source_revision: str,
    model_binding: OntologyCandidateModelBinding,
    data_handling_policy_digest: str,
    source_validation: OntologySnapshotValidation,
    limits: CandidateContextLimits,
) -> tuple[CandidateContextBinding, str, int]:
    if (
        source_validation.snapshot_digest != staged.snapshot_digest
        or source_validation.generation_digest != build.metadata.generation_digest
        or source_validation.source_generation != staged.source_generation
        or source_validation.principal_scope_digest
        != manifest.coverage_receipt.principal_scope_digest
        or source_validation.manifest_digest != manifest.manifest_digest
        or source_validation.source_projection_digest != staged.source_projection_digest
    ):
        raise CandidateContextError("invalid_source")
    source_bytes = 0
    document_count = 0
    for document in build.documents:
        if _selection_context_document(document.rule_id):
            source_bytes += len(document.text.encode("utf-8"))
            document_count += 1
            if source_bytes > limits.max_context_bytes:
                raise CandidateContextError("context_budget_exceeded")
    try:
        binding = CandidateContextBinding(
            source_revision=source_revision,
            model_binding_digest=content_digest(asdict(model_binding)),
            data_handling_policy_digest=data_handling_policy_digest,
            query_digest=_text_digest(query),
            manifest_digest=manifest.manifest_digest,
            snapshot_digest=staged.snapshot_digest,
            generation_digest=build.metadata.generation_digest,
            source_generation=staged.source_generation,
            source_projection_digest=staged.source_projection_digest,
            source_validation_digest=source_validation.receipt_digest,
        )
        payload = _candidate_proposal_content(
            query=query, manifest=manifest, build=build, staged=staged
        )
        parts = []
        size = 0
        encoder = json.JSONEncoder(
            allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        for part in encoder.iterencode(payload):
            size += len(part)
            if size > limits.max_context_bytes:
                raise CandidateContextError("context_budget_exceeded")
            parts.append(part)
        return binding, "".join(parts), document_count
    except CandidateContextError:
        raise
    except (TypeError, ValueError):
        raise CandidateContextError("invalid_source") from None


def _page_digest(ordinal: int, fragment: str, limits: CandidateContextLimits) -> str:
    payload = {"ordinal": ordinal, "fragment": fragment}
    encoded = json.dumps(payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > limits.max_page_bytes:
        raise CandidateContextError("page_budget_exceeded")
    return content_digest(payload)


def _context_digest(context: CandidateProposalContext) -> str:
    return content_digest(
        {
            "binding": context.binding.model_dump(mode="json"),
            "limits": context.limits.model_dump(mode="json"),
            "document_count": context.document_count,
            "payload_bytes": context.payload_bytes,
            "payload_digest": context.payload_digest,
            "page_digests": tuple(page.page_digest for page in context.pages),
            "authority": context.authority,
            "execution_authority": context.execution_authority,
        }
    )


def _text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

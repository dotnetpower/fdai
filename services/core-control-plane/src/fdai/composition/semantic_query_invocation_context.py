"""Build principal-scoped invocation context for semantic query functions."""

from __future__ import annotations

from fdai_service_contracts.semantic_turn import SemanticDocumentContext

from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal
from fdai.core.ontology_platform import FunctionInvocationContext
from fdai.shared.contracts.models import CeilingRole


def semantic_query_invocation_context(
    *,
    principal: Principal,
    role: CeilingRole,
    purpose: str,
    document_context: SemanticDocumentContext | None,
) -> FunctionInvocationContext:
    """Bind function reads to one verified principal and optional exact document set."""

    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=role,
        purposes=(purpose,),
        principal_ref=principal.id,
        principal_groups=tuple(sorted(principal.groups)),
        principal_scope_digest=semantic_principal_scope_digest(
            principal=principal,
            purpose=purpose,
        ),
        document_refs=document_context.citations if document_context is not None else (),
        document_context_source=(
            document_context.source.value if document_context is not None else None
        ),
        document_conversation_ref=(
            document_context.conversation_ref if document_context is not None else None
        ),
        document_authorization_digest=(
            document_context.authorization_digest if document_context is not None else None
        ),
        document_context_digest=(
            document_context.context_digest if document_context is not None else None
        ),
    )


__all__ = ["semantic_query_invocation_context"]

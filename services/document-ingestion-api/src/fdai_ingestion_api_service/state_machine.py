"""Pure lifecycle transitions owned by the Document Ingestion API."""

from types import MappingProxyType

from fdai_service_contracts import DocumentState


class InvalidDocumentTransitionError(ValueError):
    """A requested lifecycle transition is not permitted."""


_TRANSITIONS = MappingProxyType(
    {
        DocumentState.CREATED: frozenset({DocumentState.UPLOADING, DocumentState.DELETING}),
        DocumentState.UPLOADING: frozenset(
            {DocumentState.RECEIVED, DocumentState.HELD, DocumentState.DELETING}
        ),
        DocumentState.RECEIVED: frozenset({DocumentState.DELETING}),
        DocumentState.QUARANTINED: frozenset({DocumentState.DELETING}),
        DocumentState.SCANNING: frozenset({DocumentState.DELETING}),
        DocumentState.PROTECTION_CHECK: frozenset({DocumentState.DELETING}),
        DocumentState.EXTRACTING: frozenset({DocumentState.DELETING}),
        DocumentState.INDEXING: frozenset({DocumentState.DELETING}),
        DocumentState.READY: frozenset({DocumentState.DELETING}),
        DocumentState.READY_WITH_WARNINGS: frozenset({DocumentState.DELETING}),
        DocumentState.HELD: frozenset({DocumentState.DELETING}),
        DocumentState.FAILED: frozenset({DocumentState.DELETING}),
        DocumentState.DELETING: frozenset(),
        DocumentState.DELETED: frozenset(),
    }
)


def transition(current: DocumentState, target: DocumentState) -> DocumentState:
    """Return the target state when the immutable lifecycle permits it."""
    if target not in _TRANSITIONS[current]:
        raise InvalidDocumentTransitionError(
            f"invalid document transition: {current.value} -> {target.value}"
        )
    return target

"""Pure lifecycle transitions owned by the Document Processing Worker."""

from types import MappingProxyType

from fdai_service_contracts import DocumentState


class InvalidDocumentTransitionError(ValueError):
    """A requested worker lifecycle transition is not permitted."""


_TRANSITIONS = MappingProxyType(
    {
        DocumentState.CREATED: frozenset(),
        DocumentState.UPLOADING: frozenset(),
        DocumentState.RECEIVED: frozenset({DocumentState.QUARANTINED}),
        DocumentState.QUARANTINED: frozenset({DocumentState.SCANNING}),
        DocumentState.SCANNING: frozenset({DocumentState.PROTECTION_CHECK}),
        DocumentState.PROTECTION_CHECK: frozenset(
            {
                DocumentState.EXTRACTING,
                DocumentState.READY,
                DocumentState.HELD,
            }
        ),
        DocumentState.EXTRACTING: frozenset({DocumentState.INDEXING, DocumentState.FAILED}),
        DocumentState.INDEXING: frozenset(
            {
                DocumentState.READY,
                DocumentState.READY_WITH_WARNINGS,
                DocumentState.FAILED,
            }
        ),
        DocumentState.READY: frozenset(),
        DocumentState.READY_WITH_WARNINGS: frozenset(),
        DocumentState.HELD: frozenset(),
        DocumentState.FAILED: frozenset(),
        DocumentState.DELETING: frozenset({DocumentState.DELETED}),
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

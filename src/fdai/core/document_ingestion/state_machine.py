"""Pure lifecycle transition rules for immutable document versions."""

from __future__ import annotations

from types import MappingProxyType

from fdai.shared.contracts import DocumentState


class InvalidDocumentTransitionError(ValueError):
    """A requested lifecycle transition is not permitted."""


_TRANSITIONS = MappingProxyType(
    {
        DocumentState.CREATED: frozenset({DocumentState.UPLOADING, DocumentState.DELETING}),
        DocumentState.UPLOADING: frozenset(
            {DocumentState.RECEIVED, DocumentState.HELD, DocumentState.DELETING}
        ),
        DocumentState.RECEIVED: frozenset(
            {DocumentState.QUARANTINED, DocumentState.HELD, DocumentState.DELETING}
        ),
        DocumentState.QUARANTINED: frozenset({DocumentState.SCANNING, DocumentState.DELETING}),
        DocumentState.SCANNING: frozenset(
            {DocumentState.PROTECTION_CHECK, DocumentState.HELD, DocumentState.DELETING}
        ),
        DocumentState.PROTECTION_CHECK: frozenset(
            {
                DocumentState.EXTRACTING,
                DocumentState.READY,
                DocumentState.HELD,
                DocumentState.DELETING,
            }
        ),
        DocumentState.EXTRACTING: frozenset(
            {DocumentState.INDEXING, DocumentState.FAILED, DocumentState.DELETING}
        ),
        DocumentState.INDEXING: frozenset(
            {
                DocumentState.READY,
                DocumentState.READY_WITH_WARNINGS,
                DocumentState.FAILED,
                DocumentState.DELETING,
            }
        ),
        DocumentState.READY: frozenset({DocumentState.DELETING}),
        DocumentState.READY_WITH_WARNINGS: frozenset({DocumentState.DELETING}),
        DocumentState.HELD: frozenset({DocumentState.DELETING}),
        DocumentState.FAILED: frozenset({DocumentState.DELETING}),
        DocumentState.DELETING: frozenset({DocumentState.DELETED}),
        DocumentState.DELETED: frozenset(),
    }
)


def transition(current: DocumentState, target: DocumentState) -> DocumentState:
    """Return ``target`` when allowed, otherwise fail without side effects."""
    if target not in _TRANSITIONS[current]:
        raise InvalidDocumentTransitionError(
            f"invalid document transition: {current.value} -> {target.value}"
        )
    return target


def can_transition(current: DocumentState, target: DocumentState) -> bool:
    return target in _TRANSITIONS[current]


__all__ = ["InvalidDocumentTransitionError", "can_transition", "transition"]

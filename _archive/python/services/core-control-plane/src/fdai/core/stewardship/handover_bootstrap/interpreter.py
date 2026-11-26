"""T2 interpreter seam - the model leg of handover extraction.

Deterministic structured extraction (:mod:`.extractor`) runs first. When it
cannot resolve a document's mappings, the bootstrap MAY consult a frontier
model behind this **async** Protocol. The model *proposes* grounded mappings;
it never applies anything, and an ungrounded / low-confidence proposal is
dropped by the orchestrator (abstain, never guess).

Upstream ships :class:`AbstainingInterpreter` (proposes nothing) so a
deployment without an LLM emits no model guesses. A fork binds a mixed-model,
grounded implementation (symmetric to the RCA reasoner seam in
:mod:`fdai.core.rca`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdai.core.stewardship.handover_bootstrap.contract import (
    ExtractedMapping,
    HandoverDocument,
)


@runtime_checkable
class HandoverInterpreter(Protocol):
    """Propose grounded person -> agent mappings from a document.

    Implementations MUST cite a source span for every proposed mapping and
    MUST NOT invent a person or agent absent from the document. A malformed or
    ungrounded proposal is discarded by the caller - the model proposes, the
    deterministic pipeline decides eligibility.
    """

    async def interpret(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
        """Return proposed mappings (each grounded), or an empty tuple to abstain."""
        ...


class AbstainingInterpreter:
    """The upstream default :class:`HandoverInterpreter` - proposes nothing.

    With no model wired, the bootstrap stays fully deterministic and never
    guesses. A fork replaces this with a grounded frontier-model interpreter.
    """

    async def interpret(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:  # noqa: ARG002
        return ()


__all__ = ["AbstainingInterpreter", "HandoverInterpreter"]

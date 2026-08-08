"""Handover-bootstrap contracts - pure dataclasses/enums (SRP: no I/O).

This subpackage turns uploaded operational documents (RACI matrices, on-call
schedules, org charts, runbooks, handover memos) into a **draft** human <->
agent steward map for review (issue #23). It never applies anything: the
output is a draft the deterministic stewardship core
(:mod:`fdai.core.stewardship.resolver`) can load and a human reviews as a
governance PR.

Design principles baked into these shapes:

- **Deterministic-first.** A mapping records its :class:`MappingSource` -
  ``deterministic`` (structured extraction) vs ``model`` (a T2 interpreter) -
  so the pipeline reaches the model only for what structure cannot resolve.
- **Grounding.** Every :class:`ExtractedMapping` cites the source span(s) it
  came from (:class:`SourceSpan`); an ungrounded mapping is not emitted.
- **Abstain, never guess.** Low-confidence mappings and unresolved people /
  agents are surfaced on the draft explicitly, not silently guessed.

Design authority:
[`docs/roadmap/interfaces/agent-stewardship-and-handover.md`]
(../../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from fdai.core.stewardship.model import Responsibility, StewardKind


class DocumentKind(StrEnum):
    """The kind of ingested operational document.

    Used by the extractor to pick a structured parse strategy; ``other``
    falls back to free-text scanning.
    """

    RACI = "raci"
    ON_CALL = "on_call"
    ORG_CHART = "org_chart"
    RUNBOOK = "runbook"
    HANDOVER_MEMO = "handover_memo"
    OTHER = "other"


class MappingSource(StrEnum):
    """How a mapping was produced - deterministic-first provenance."""

    DETERMINISTIC = "deterministic"
    """Structured extraction resolved the mapping without a model."""

    MODEL = "model"
    """A T2 :class:`~fdai.core.stewardship.handover_bootstrap.interpreter.HandoverInterpreter`
    proposed the mapping (grounded + gated)."""


class DraftOutcome(StrEnum):
    """Terminal outcome of one bootstrap run."""

    DRAFTED = "drafted"
    """At least one grounded mapping was produced."""

    ABSTAINED = "abstained"
    """No mapping cleared the confidence floor - nothing is guessed."""


@dataclass(frozen=True, slots=True)
class HandoverDocument:
    """One uploaded operational document, already decoded to text.

    ``doc_id`` is an opaque handle (never a raw path or secret). ``text`` is
    the extracted plain text; binary decoding / OCR happens in the delivery
    layer before this core sees it.
    """

    doc_id: str
    kind: DocumentKind
    text: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A citation back to the span of a source document a mapping came from.

    ``quote`` is the exact substring (bounded) so a reviewer can verify the
    grounding without opening the document; ``line`` is 1-based for display.
    """

    doc_id: str
    line: int
    quote: str

    def to_dict(self) -> dict[str, object]:
        return {"doc_id": self.doc_id, "line": self.line, "quote": self.quote}


@dataclass(frozen=True, slots=True)
class PersonRef:
    """A person or team mentioned in a document, and its resolution state.

    ``oid`` is the resolved Entra object id, or ``None`` when the directory
    could not resolve ``display_name`` - in which case ``unresolved`` is
    ``True`` and the name is surfaced for a human, never guessed into an id.
    """

    display_name: str
    kind: StewardKind = StewardKind.USER
    oid: str | None = None

    @property
    def unresolved(self) -> bool:
        """True iff no Entra object id was resolved for this person/team."""
        return self.oid is None

    def to_dict(self) -> dict[str, object]:
        return {
            "display_name": self.display_name,
            "kind": self.kind.value,
            "oid": self.oid,
            "unresolved": self.unresolved,
        }


@dataclass(frozen=True, slots=True)
class ExtractedMapping:
    """One candidate person -> agent mapping with grounding and confidence.

    ``confidence`` is a stated uncertainty in ``[0, 1]``; it never grants an
    autonomous apply. ``citations`` is non-empty for any emitted mapping
    (grounding is mandatory). ``rationale`` is a short English note.
    """

    agent_name: str
    person: PersonRef
    responsibility: Responsibility
    confidence: float
    source: MappingSource
    citations: tuple[SourceSpan, ...]
    rationale: str = ""

    @property
    def grounded(self) -> bool:
        """True iff at least one citation backs the mapping."""
        return len(self.citations) > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_name": self.agent_name,
            "person": self.person.to_dict(),
            "responsibility": self.responsibility.value,
            "confidence": self.confidence,
            "source": self.source.value,
            "citations": [c.to_dict() for c in self.citations],
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class StewardMapDraft:
    """The reviewable output of a bootstrap run.

    A draft is never applied. ``mappings`` are the grounded, above-threshold
    candidates; ``abstained`` are grounded but below-threshold candidates kept
    for a human to confirm; ``unresolved_people`` are names the directory
    could not resolve; ``unmapped_agents`` are pantheon agents with no
    confident mapping (they need a manual steward or ``accept_autonomous``).
    """

    version: int
    outcome: DraftOutcome
    mappings: tuple[ExtractedMapping, ...] = ()
    abstained: tuple[ExtractedMapping, ...] = ()
    unresolved_people: tuple[PersonRef, ...] = ()
    unmapped_agents: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "outcome": self.outcome.value,
            "mappings": [m.to_dict() for m in self.mappings],
            "abstained": [m.to_dict() for m in self.abstained],
            "unresolved_people": [p.to_dict() for p in self.unresolved_people],
            "unmapped_agents": list(self.unmapped_agents),
            "warnings": list(self.warnings),
        }


__all__ = [
    "DocumentKind",
    "DraftOutcome",
    "ExtractedMapping",
    "HandoverDocument",
    "MappingSource",
    "PersonRef",
    "SourceSpan",
    "StewardMapDraft",
]

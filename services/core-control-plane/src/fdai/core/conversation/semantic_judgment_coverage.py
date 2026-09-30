"""Blind second-reader coverage of one typed semantic judgment.

One model reading can drop a stated constraint and still pass every structural check:
the list it compiles is then wider than the question and reads as a correct answer. A
second model of another family therefore reads only the question, beside the judgment,
and quotes every constraint it states with a closed role. Code never interprets the
words; it checks structurally that each constraining quote shares a letter or digit
with a span the judgment copied.

A restriction, negation, comparison, order, or time that no copied span covers goes
back to the judgment as repair feedback naming its span and exact words, together with
every constraint the proposal must keep. If it stays uncovered the constraint cannot be
expressed faithfully, so the turn stops instead of answering a different question.
Named things and relation words may be the question's own subject or the cue of a
copied operand, so they never force a repair; a named thing that stands apart from
every copied span is offered to closed-choice grounding as a possibly omitted subtype.
An unavailable or malformed reading reviews nothing and is logged.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_reasoning_form import SourceSpan
from .semantic_reasoning_review import ConstraintExtraction, ConstraintRole, resolve_extraction

_LOGGER = logging.getLogger(__name__)
UNCOVERED_CONSTRAINT_REASON = "semantic proposal omits a stated constraint"
UNCOVERED_CONSTRAINT_CODE = "semantic_constraint_uncovered"
# Roles whose loss changes which rows or facts answer the question.
HARD_ROLES = frozenset(
    {
        ConstraintRole.RESTRICTS,
        ConstraintRole.NEGATES,
        ConstraintRole.COMPARES,
        ConstraintRole.ORDERS,
        ConstraintRole.TIMES,
    }
)


class ConstraintExtractorModel(Protocol):
    async def extract_constraints(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
    ) -> Mapping[str, Any] | None: ...


class UncoveredConstraintError(ValueError):
    """A proposal left a stated constraint uncovered.

    ``location`` names each code-point span, ``quote`` repeats the exact words there,
    and ``required`` lists every constraint to keep; all are words of the judged
    utterance, so they add no new input. ``roles`` names the closed constraint roles
    left uncovered, which diagnostics may record without any utterance text.
    """

    def __init__(
        self,
        spans: tuple[SourceSpan, ...],
        *,
        utterance: str,
        required: tuple[SourceSpan, ...] = (),
        roles: tuple[str, ...] = (),
    ) -> None:
        super().__init__(UNCOVERED_CONSTRAINT_REASON)
        self.spans = spans
        self.roles = roles
        self.location = ",".join(f"utterance[{span.start}:{span.end}]" for span in spans)
        self.quote = " | ".join(utterance[span.start : span.end] for span in spans)
        self.required = " | ".join(utterance[span.start : span.end] for span in required)


@dataclass(slots=True)
class JudgmentCoverage:
    """One turn's pending blind reading, resolved once and shared by every check."""

    future: concurrent.futures.Future[Mapping[str, Any] | None]
    utterance: str
    timeout_seconds: float
    _resolved: bool = False
    _extraction: ConstraintExtraction | None = None

    def check(self, proposal: SemanticJudgmentProposal) -> None:
        """Raise ``UncoveredConstraintError`` for a hard constraint the proposal left out."""

        extraction = self.reading()
        if extraction is None:
            return
        uncovered = uncovered_constraint_spans(proposal, extraction, self.utterance)
        if uncovered:
            required = tuple(
                item.quote
                for item in extraction.constraints
                if item.role in HARD_ROLES or item.role is ConstraintRole.NAMES
            )
            roles = tuple(
                sorted(
                    {item.role.value for item in extraction.constraints if item.quote in uncovered}
                )
            )
            raise UncoveredConstraintError(
                uncovered, utterance=self.utterance, required=required, roles=roles
            )

    def settled_reading(self) -> ConstraintExtraction | None:
        """Return the blind reading only when it has already arrived; never wait for it."""

        if not self._resolved and not self.future.done():
            return None
        return self.reading()

    def reading(self) -> ConstraintExtraction | None:
        """Return the located blind reading, or ``None`` when it cannot review."""

        if self._resolved:
            return self._extraction
        self._resolved = True
        try:
            raw = self.future.result(timeout=self.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - provider details remain inside the adapter
            self.future.cancel()
            _LOGGER.warning(
                "semantic_judgment_coverage_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return None
        self._extraction = resolve_extraction(raw, self.utterance) if raw is not None else None
        if self._extraction is None:
            _LOGGER.warning(
                "semantic_judgment_coverage_unavailable",
                extra={"failure_type": "reading_invalid" if raw is not None else "no_reading"},
            )
        return self._extraction


class JudgmentCoverageReview:
    """Start one blind reading per operational turn on the owner event loop."""

    def __init__(
        self,
        *,
        extractor: ConstraintExtractorModel,
        owner_loop: asyncio.AbstractEventLoop,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not 0 < timeout_seconds <= 120:
            raise ValueError("coverage timeout_seconds MUST be in (0, 120]")
        self._extractor = extractor
        self._owner_loop = owner_loop
        self._timeout_seconds = timeout_seconds

    def start(self, *, utterance: str, locale: str) -> JudgmentCoverage:
        """Begin the reading before the judgment so both run concurrently."""

        future = asyncio.run_coroutine_threadsafe(
            self._extractor.extract_constraints(utterance=utterance, context=(), locale=locale),
            self._owner_loop,
        )
        return JudgmentCoverage(future, utterance, self._timeout_seconds)


def start_coverage(
    review: JudgmentCoverageReview | None,
    *,
    utterance: str,
    locale: str,
) -> JudgmentCoverage | None:
    """Return one started reading when the review is enabled."""

    return None if review is None else review.start(utterance=utterance, locale=locale)


def detached_spans(
    coverage: JudgmentCoverage | None,
    proposal: SemanticJudgmentProposal,
) -> tuple[SourceSpan, ...]:
    """Return the detached named-thing quotes of an accepted proposal, if reviewed."""

    if coverage is None:
        return ()
    reading = coverage.reading()
    return () if reading is None else detached_named_spans(proposal, reading, coverage.utterance)


_NAME_OPERAND_KINDS = frozenset(
    {"affected_target", "resource", "resource_group", "resource_name_filter"}
)


def settled_proposal(
    coverage: JudgmentCoverage | None,
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    """Drop a name-filter facet that neither reading gives an operand.

    Only a reviewed proposal reaches this point, so every stated restriction is already
    copied; a ``name_filter`` facet without any copied name operand then names nothing.
    """

    if (
        coverage is None
        or coverage.reading() is None
        or "name_filter" not in proposal.requested_facets
        or any(target.kind in _NAME_OPERAND_KINDS for target in proposal.targets)
    ):
        return proposal
    facets = tuple(facet for facet in proposal.requested_facets if facet != "name_filter")
    return proposal.model_copy(update={"requested_facets": facets})


def uncovered_constraint_spans(
    proposal: SemanticJudgmentProposal,
    extraction: ConstraintExtraction,
    utterance: str,
) -> tuple[SourceSpan, ...]:
    """Return hard constraint quotes that share no letter or digit with a copied span."""

    copied = _copied_spans(proposal)
    return tuple(
        constraint.quote
        for constraint in extraction.constraints
        if constraint.role in HARD_ROLES
        and not any(
            _shares_meaning(utterance, constraint.quote, start, end)
            # "only", "not", or "만" is quoted alone but binds the operand it touches.
            or (
                constraint.role is ConstraintRole.NEGATES
                and _touches(utterance, constraint.quote, start, end)
            )
            for start, end in copied
        )
    )


def detached_named_spans(
    proposal: SemanticJudgmentProposal,
    extraction: ConstraintExtraction,
    utterance: str,
) -> tuple[SourceSpan, ...]:
    """Return named-thing quotes that neither share with nor directly touch a copied span.

    A name written right beside a copied span, with only spaces between, is that
    span's own head word, such as the kind word after a named group.
    """

    copied = _copied_spans(proposal)
    return tuple(
        constraint.quote
        for constraint in extraction.constraints
        if constraint.role is ConstraintRole.NAMES
        and not any(
            _shares_meaning(utterance, constraint.quote, start, end)
            or _touches(utterance, constraint.quote, start, end)
            for start, end in copied
        )
    )


def _copied_spans(proposal: SemanticJudgmentProposal) -> tuple[tuple[int, int], ...]:
    spans = tuple(
        (target.source_start, target.source_end)
        for target in (*proposal.targets, *proposal.forbidden_actions)
    )
    # A span stretched over another copied span merges two constraints into one operand,
    # so it covers nothing; only the separately copied operands count.
    return tuple(
        span
        for span in spans
        if not any(other != span and span[0] <= other[0] and other[1] <= span[1] for other in spans)
    )


def _shares_meaning(utterance: str, quote: SourceSpan, start: int, end: int) -> bool:
    low, high = max(quote.start, start), min(quote.end, end)
    return any(character.isalnum() for character in utterance[low:high])


def _touches(utterance: str, quote: SourceSpan, start: int, end: int) -> bool:
    gap = utterance[end : quote.start] if end <= quote.start else utterance[quote.end : start]
    return (end <= quote.start or quote.end <= start) and not gap.strip()


__all__ = [
    "HARD_ROLES",
    "UNCOVERED_CONSTRAINT_CODE",
    "UNCOVERED_CONSTRAINT_REASON",
    "ConstraintExtractorModel",
    "JudgmentCoverage",
    "JudgmentCoverageReview",
    "UncoveredConstraintError",
    "detached_named_spans",
    "detached_spans",
    "settled_proposal",
    "start_coverage",
    "uncovered_constraint_spans",
]

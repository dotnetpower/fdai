"""The one review repair of a single admitted reading the blind review found unfaithful.

The repair names each uncovered or absorbed constraint and each mention that merges separate
constraints, as the independent extraction quoted them. The proposer may only add information,
except that a merged mention is replaced by one mention per extracted part; a literal is never
moved, so a reading with a disagreeing literal gets no repair.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .semantic_reasoning_admission import (
    AdmissionDisposition,
    SpanAccounting,
    admit_question_form,
)
from .semantic_reasoning_form import SemanticQuestionForm
from .semantic_reasoning_proposal import FormResolution, resolve_question_form
from .semantic_reasoning_relabel import relabel_mentions
from .semantic_reasoning_repair import FormProposal, FormRepair, repair_keeps_operands
from .semantic_reasoning_review import (
    FormReview,
    describe_merged,
    describe_uncovered,
    describe_unexpressible,
    literal_disagreements,
    merged_mentions,
    quoted_form,
    resolve_extraction,
    unacknowledged_constraints,
    uncovered_constraints,
)


@dataclass(frozen=True, slots=True)
class ReviewRepair:
    """The admitted form the review found incomplete, and the constraints it must state."""

    previous: Mapping[str, Any]
    typed: SemanticQuestionForm
    violations: tuple[str, ...]
    reasons: tuple[str, ...]
    # Mentions the independent reading found merging separate constraints; the repair
    # replaces each with one mention per part.
    split: frozenset[str] = frozenset()


def review_repair(
    review: FormReview,
    raw: Mapping[str, Any] | None,
    forms: list[SemanticQuestionForm],
    *,
    passes: int,
    repairs: int,
    utterance: str,
) -> ReviewRepair | None:
    """Return one repair for a single admitted pass whose review found uncovered words."""

    if review.outcome != "unfaithful" or raw is None or repairs < 1:
        return None
    if len(forms) != 1 or passes != 1:
        return None
    extraction = resolve_extraction(raw, utterance)
    if extraction is None:
        return None
    uncovered = uncovered_constraints(forms, extraction, utterance)
    unacknowledged = unacknowledged_constraints(forms, extraction, utterance)
    merged = merged_mentions(forms, extraction)
    # A repair only adds information, except that it may split a mention holding separate
    # constraints along the independent reader's disjoint quotes; it never moves a literal,
    # so that turn is held instead.
    if not (uncovered or unacknowledged or merged) or literal_disagreements(forms, extraction):
        return None
    form = forms[0]
    violations = (
        *(
            describe_merged(mention_id, form.mention(mention_id).span, parts, utterance)
            for mention_id, parts in merged.items()
        ),
        *(describe_uncovered(item, utterance, forms) for item in uncovered),
        *(describe_unexpressible(item, utterance) for item in unacknowledged),
    )
    return ReviewRepair(
        previous=quoted_form(form, utterance),
        typed=form,
        violations=tuple(dict.fromkeys(violations)),
        reasons=review.reasons,
        split=frozenset(merged),
    )


async def propose_review_repair(
    propose: Callable[..., Any],
    repair: ReviewRepair,
    *,
    utterance: str,
    accounting: SpanAccounting,
) -> FormProposal:
    """Ask the proposer to state the uncovered constraints, adding information only."""

    raw = await propose(repair=FormRepair(previous=repair.previous, violations=repair.violations))
    if raw is None:
        return FormProposal(None, None, "unavailable", repair.reasons)
    resolution = resolve_question_form(raw, utterance=utterance)
    if resolution.form is None:
        return FormProposal(resolution, None, "invalid", repair.reasons)
    form = relabel_mentions(repair.typed, resolution.form, split=repair.split)
    resolution = replace(resolution, form=form)
    if not repair_keeps_operands(
        repair.previous,
        form,
        utterance=utterance,
        typed=repair.typed,
        extension_only=True,
        split=repair.split,
    ):
        dropped = FormResolution(None, ("review_repair_operand_dropped",))
        return FormProposal(dropped, None, "operand_dropped", repair.reasons)
    applied = "review_split_applied" if repair.split else "review_applied"
    admission = admit_question_form(form, utterance=utterance, accounting=accounting)
    if admission.disposition is AdmissionDisposition.INVALID and all(
        reason.startswith("span_unaccounted:") for reason in admission.reasons
    ):
        # This is the turn's one repair, and the review reads the repaired form again, so
        # a word it leaves unplaced is judged there, as after a first-pass repair.
        relaxed = admit_question_form(
            form, utterance=utterance, accounting=SpanAccounting(required=False)
        )
        return FormProposal(resolution, relaxed, f"{applied}_unaccounted", repair.reasons)
    return FormProposal(resolution, admission, applied, repair.reasons)


__all__ = ["ReviewRepair", "propose_review_repair", "review_repair"]

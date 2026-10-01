"""Follow-up references: bind anaphors and ordinals to the rows the operator saw.

Core issues a ``ResultSetHandle`` after it renders a result, so a handle holds exactly
the rows the operator saw, in the order shown. A later question that says them, 그중에서,
or the first one refers to those rows. The model only marks a mention as an anaphor or
an ordinal with a typed position; Core decides which rows it names. A handle binds only
inside its own conversation, principal, purpose, and manifest, and only before it
expires; anything else is one typed clarification, never a guess. The rows are then
read again through the secured gateway, so a row the principal can no longer see never
reaches the answer.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.ontology_query import content_digest

from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_binding import AnchorBinding, AnchorBindingReceipt, AnchorOutcome
from .semantic_reasoning_form import FormGoal, GoalOperation, MentionForm, SubjectScope

MAX_HANDLE_ROWS = 1000
# The row restriction must fit one plan node's canonical arguments with room to spare.
MAX_REFERENCE_BYTES = 32_768
_REFERENCE_FORMS = frozenset({MentionForm.ANAPHOR, MentionForm.ORDINAL})
_STARTING_OPERATIONS = frozenset(
    {GoalOperation.LOOKUP, GoalOperation.HISTORY, GoalOperation.IMPACT}
)


@dataclass(frozen=True, slots=True)
class ResultSetHandle:
    """The rows one rendered answer showed, bound to who saw them and under which release."""

    handle_id: str
    conversation_id: str
    principal_id: str
    purpose: str
    manifest_digest: str
    expires_at: datetime
    object_type: str
    row_ids: tuple[str, ...]
    truncated: bool = False
    source_generation: str | None = None

    def __post_init__(self) -> None:
        if not self.handle_id or not self.conversation_id or not self.principal_id:
            raise ValueError("result handle MUST name its handle, conversation, and principal")
        if self.expires_at.tzinfo is None:
            raise ValueError("result handle expiry MUST be timezone-aware")
        if len(self.row_ids) > MAX_HANDLE_ROWS or len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("result handle rows MUST be unique and bounded")
        if any(not isinstance(item, str) or not item for item in self.row_ids):
            raise ValueError("result handle rows MUST be non-empty identifiers")


@dataclass(frozen=True, slots=True)
class HandleScope:
    """Who asks now, so a handle binds only where it was issued."""

    conversation_id: str
    principal_id: str
    purpose: str
    manifest_digest: str
    now: datetime

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("handle scope time MUST be timezone-aware")


class ReferenceOutcome(StrEnum):
    BOUND = "bound"
    UNAVAILABLE = "unavailable"
    FOREIGN = "foreign"
    CHANGED = "changed"
    EXPIRED = "expired"
    OUT_OF_RANGE = "out_of_range"
    AMBIGUOUS = "ambiguous"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class ReferenceBinding:
    """The rows one reference mention names, or why it names none."""

    mention_id: str
    outcome: ReferenceOutcome
    form: MentionForm
    row_ids: tuple[str, ...] = ()
    handle_id: str | None = None
    truncated: bool = False
    source_generation: str | None = None
    # The reauthorized row's Resource type, when the binder reread it; never from words.
    resource_type: str | None = None

    @property
    def bound(self) -> bool:
        return self.outcome is ReferenceOutcome.BOUND


@dataclass(frozen=True, slots=True)
class ReferenceReceipt:
    """Per-mention reference outcomes; empty when the turn carries no reference."""

    bindings: tuple[ReferenceBinding, ...] = ()

    def binding(self, mention_id: str | None) -> ReferenceBinding | None:
        return next((item for item in self.bindings if item.mention_id == mention_id), None)

    @property
    def digest(self) -> str:
        return content_digest(
            [
                {
                    "mention": item.mention_id,
                    "outcome": item.outcome.value,
                    "handle": item.handle_id,
                    "rows": list(item.row_ids),
                    "truncated": item.truncated,
                }
                for item in self.bindings
            ]
        )


def reference_mention(admission: FormAdmission, goal_id: str) -> str | None:
    """Return the reference mention a prior-result goal ranges over, if any."""

    form = admission.form
    goal = next(item for item in form.goals if item.id == goal_id)
    if goal.subject_scope is not SubjectScope.PRIOR_RESULT:
        return None
    if goal.subject is not None:
        return goal.subject
    references = [mention.id for mention in form.mentions if mention.form in _REFERENCE_FORMS]
    # Admission lets a subject-less prior-result goal stand only with one reference mention.
    return references[0] if len(references) == 1 else None


def starts_from_reference(goal: FormGoal, reference: str | None) -> bool:
    """Return whether a prior-result goal starts its read from the referenced rows.

    A relation starts from the reference when its anchor, or the goal subject when the
    anchor is left unstated, is the reference mention itself; a relation anchored on
    another mention only narrows its results. Without a relation, a lookup, a history,
    and an impact read start from the subject, and a collection read narrows.
    """

    if reference is None:
        return False
    relation = goal.relation
    if relation is not None:
        anchor = relation.anchor if relation.anchor is not None else goal.subject
        return anchor == reference
    return goal.effective_operation in _STARTING_OPERATIONS


def restricting_rows(
    admission: FormAdmission, references: ReferenceReceipt, goal: FormGoal
) -> tuple[str, ...] | None:
    """Return the rows every result read of a prior-result goal must be restricted to.

    A reference that names exactly one row, an ordinal or an anaphor over a one-row
    answer, anchors a read it starts; otherwise it narrows the results to its rows, so a
    reference is never dropped.
    """

    if goal.subject_scope is not SubjectScope.PRIOR_RESULT:
        return None
    mention_id = reference_mention(admission, goal.id)
    binding = references.binding(mention_id)
    if binding is None or not binding.bound:
        return None
    if len(binding.row_ids) == 1 and starts_from_reference(goal, mention_id):
        return None
    return binding.row_ids


def reference_bytes(rows: Sequence[str]) -> int:
    """Return the encoded size of a row restriction, measured without a size cap."""

    return len(json.dumps(list(rows), ensure_ascii=False, separators=(",", ":")).encode())


def bind_references(
    admission: FormAdmission,
    handles: Sequence[ResultSetHandle],
    scope: HandleScope | None,
) -> ReferenceReceipt:
    """Bind every reference mention of a prior-result goal to the most recent handle.

    A follow-up refers to the answer just shown; naming an older answer is not a form
    the model can express yet, so an older handle never binds.
    """

    handle = handles[-1] if handles else None
    bindings: dict[str, ReferenceBinding] = {}
    for goal in admission.form.goals:
        mention_id = reference_mention(admission, goal.id)
        if mention_id is None or mention_id in bindings:
            continue
        mention = admission.form.mention(mention_id)
        bindings[mention_id] = _bind(mention_id, mention.form, mention.position, handle, scope)
    return ReferenceReceipt(tuple(bindings.values()))


def reference_anchors(
    anchors: AnchorBindingReceipt, references: ReferenceReceipt
) -> AnchorBindingReceipt:
    """Add each bound reference that names exactly one row as an anchor on that row."""

    extra = tuple(
        AnchorBinding(
            item.mention_id,
            AnchorOutcome.BOUND,
            object_id=item.row_ids[0],
            source_generation=item.source_generation,
            resource_type=item.resource_type,
        )
        for item in references.bindings
        if item.bound and len(item.row_ids) == 1 and anchors.binding(item.mention_id) is None
    )
    return AnchorBindingReceipt((*anchors.bindings, *extra)) if extra else anchors


def _bind(
    mention_id: str,
    form: MentionForm,
    position: int | None,
    handle: ResultSetHandle | None,
    scope: HandleScope | None,
) -> ReferenceBinding:
    def outcome(value: ReferenceOutcome) -> ReferenceBinding:
        return ReferenceBinding(mention_id, value, form)

    if handle is None or scope is None:
        return outcome(ReferenceOutcome.UNAVAILABLE)
    if (handle.conversation_id, handle.principal_id, handle.purpose) != (
        scope.conversation_id,
        scope.principal_id,
        scope.purpose,
    ):
        return outcome(ReferenceOutcome.FOREIGN)
    if handle.manifest_digest != scope.manifest_digest:
        return outcome(ReferenceOutcome.CHANGED)
    if handle.expires_at <= scope.now:
        return outcome(ReferenceOutcome.EXPIRED)
    if not handle.row_ids:
        return outcome(ReferenceOutcome.EMPTY)
    rows = handle.row_ids
    truncated = handle.truncated
    if form is MentionForm.ORDINAL:
        if position is None or position == 0 or abs(position) > len(rows):
            return outcome(ReferenceOutcome.OUT_OF_RANGE)
        # Counting from the end of a shortened answer could mean the last row shown or
        # the last row of the whole result, so it clarifies instead of picking one.
        if position < 0 and truncated:
            return outcome(ReferenceOutcome.AMBIGUOUS)
        # A row counted from the start is one the operator saw, whatever was cut after it.
        rows, truncated = (rows[position - 1] if position > 0 else rows[position],), False
    return ReferenceBinding(
        mention_id,
        ReferenceOutcome.BOUND,
        form,
        row_ids=rows,
        handle_id=handle.handle_id,
        truncated=truncated,
        source_generation=handle.source_generation,
    )


__all__ = [
    "MAX_HANDLE_ROWS",
    "MAX_REFERENCE_BYTES",
    "HandleScope",
    "ReferenceBinding",
    "ReferenceOutcome",
    "ReferenceReceipt",
    "ResultSetHandle",
    "bind_references",
    "reference_anchors",
    "reference_bytes",
    "reference_mention",
    "restricting_rows",
    "starts_from_reference",
]

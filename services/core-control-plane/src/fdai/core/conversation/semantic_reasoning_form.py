"""Closed question logical form proposed by the model and validated by Core.

The form carries only closed enums, bounded integers, mention references, and
exact source spans. It never carries a FunctionType, LinkType, ObjectType
operand, instance identity, or canonical instance value; deterministic code
binds those after admission.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FORM_MENTIONS = 16
MAX_FORM_GOALS = 4
MAX_FORM_ALTERNATIVES = 3
MAX_ALTERNATIVE_ATOMS = 6
MAX_FORM_BYTES = 6 * 1024
MAX_CONTEXT_SPANS = 32
MAX_UNSUPPORTED_CONSTRAINTS = 8
_MENTION_ID = r"^m[0-9]{1,2}$"
_GOAL_ID = r"^g[0-9]{1,2}$"


class MentionForm(StrEnum):
    IDENTIFIER = "identifier"
    NAME = "name"
    CONCEPT = "concept"
    VALUE = "value"
    ANAPHOR = "anaphor"
    ORDINAL = "ordinal"


class MentionDomain(StrEnum):
    INSTANCE = "instance"
    OBJECT_TYPE = "object_type"
    RESOURCE_TYPE = "resource_type"
    RESOURCE_CLASS = "resource_class"
    STATE = "state"
    HEALTH = "health"
    METRIC = "metric"
    REGION = "region"
    DECLARATION_KIND = "declaration_kind"
    PROPERTY = "property"


class GoalLevel(StrEnum):
    INSTANCE = "instance"
    SCHEMA = "schema"


class GoalOperation(StrEnum):
    SELECT = "select"
    COUNT = "count"
    LOOKUP = "lookup"
    TRAVERSE = "traverse"
    PATH = "path"
    AGGREGATE = "aggregate"
    RANK = "rank"
    HISTORY = "history"
    COMPARE_WINDOWS = "compare_windows"
    COMPARE_ENTITIES = "compare_entities"
    DIFF_VERSIONS = "diff_versions"
    IMPACT = "impact"
    EXPLAIN_CAUSE = "explain_cause"
    VERIFY_EVIDENCE = "verify_evidence"
    DESCRIBE_SCHEMA = "describe_schema"
    DIAGNOSE = "diagnose"
    DRAFT_ACTION = "draft_action"


class SubjectScope(StrEnum):
    ANCHOR = "anchor"
    COLLECTION = "collection"
    PRIOR_RESULT = "prior_result"
    GOAL_OUTPUT = "goal_output"


class FilterRole(StrEnum):
    TYPE = "type"
    STATE = "state"
    HEALTH = "health"
    REGION = "region"
    NAME_FRAGMENT = "name_fragment"
    SCOPE = "scope"


class RelationSense(StrEnum):
    CONTAINMENT = "containment"
    ATTACHMENT = "attachment"
    DEPENDENCY = "dependency"
    CONNECTIVITY = "connectivity"
    TRAFFIC = "traffic"
    CLASSIFICATION = "classification"
    COMPOSITION = "composition"
    OWNERSHIP = "ownership"
    AUTHORIZATION = "authorization"
    EVIDENCE = "evidence"


class RelationScope(StrEnum):
    ONE_SENSE = "one_sense"
    ALL_KINDS = "all_kinds"


class SubjectPosition(StrEnum):
    """Stored LinkType end of the anchor; derived by Core, never proposed."""

    SOURCE = "source"
    TARGET = "target"
    EITHER = "either"


class SubjectRole(StrEnum):
    """Meaning-level role of the goal subject inside its relation."""

    CONTAINER = "container"
    MEMBER = "member"
    DEPENDENT = "dependent"
    DEPENDENCY = "dependency"
    SENDER = "sender"
    RECEIVER = "receiver"
    ATTACHED = "attached"
    HOST = "host"
    INSTANCE = "instance"
    CATEGORY = "category"
    EVIDENCE = "evidence"
    EVIDENCED = "evidenced"
    OWNER = "owner"
    OWNED = "owned"
    WHOLE = "whole"
    PART = "part"
    GRANTEE = "grantee"
    GRANTED = "granted"
    EITHER = "either"


class RelationReach(StrEnum):
    ONE_HOP = "one_hop"
    TRANSITIVE = "transitive"


class MeasureKind(StrEnum):
    COUNT = "count"
    STATE = "state"
    HEALTH = "health"
    METRIC = "metric"
    CHANGE = "change"
    EVENT = "event"
    FORECAST = "forecast"
    COST = "cost"
    PROPERTY = "property"


class GroupBy(StrEnum):
    ENDPOINT = "endpoint"
    TYPE = "type"
    CONTAINER = "container"
    NONE = "none"


class OrderDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class TimeKind(StrEnum):
    CURRENT = "current"
    WINDOW = "window"
    AS_OF = "as_of"
    TWO_WINDOWS = "two_windows"
    VERSIONS = "versions"
    FUTURE = "future"
    UNSPECIFIED = "unspecified"


class Want(StrEnum):
    FACT = "fact"
    CAUSE = "cause"
    VERIFICATION = "verification"
    COMPLETENESS = "completeness"


class _FormModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceSpan(_FormModel):
    """One half-open character range in the current utterance."""

    start: int = Field(ge=0, le=32_000)
    end: int = Field(gt=0, le=32_000)

    @model_validator(mode="after")
    def _ordered(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("source span end MUST follow its start")
        return self


class FormQualifier(_FormModel):
    """Scope one mention through an earlier mention and a relation sense."""

    mention: Annotated[str, Field(pattern=_MENTION_ID)]
    sense: RelationSense


class FormMention(_FormModel):
    id: Annotated[str, Field(pattern=_MENTION_ID)]
    form: MentionForm
    domain: MentionDomain
    span: SourceSpan
    qualifier: FormQualifier | None = None
    # An ordinal's 1-based position in the rows shown before; a negative one counts from the end.
    position: int | None = Field(default=None, ge=-1000, le=1000)


class FormFilter(_FormModel):
    role: FilterRole
    mention: Annotated[str, Field(pattern=_MENTION_ID)]
    cue: SourceSpan | None = None


# Reviewed role convention per sense: (role of the stored from-end, role of the to-end).
SENSE_ROLES: dict[RelationSense, tuple[SubjectRole, SubjectRole]] = {
    RelationSense.CONTAINMENT: (SubjectRole.CONTAINER, SubjectRole.MEMBER),
    RelationSense.ATTACHMENT: (SubjectRole.ATTACHED, SubjectRole.HOST),
    RelationSense.DEPENDENCY: (SubjectRole.DEPENDENT, SubjectRole.DEPENDENCY),
    RelationSense.CONNECTIVITY: (SubjectRole.SENDER, SubjectRole.RECEIVER),
    RelationSense.TRAFFIC: (SubjectRole.SENDER, SubjectRole.RECEIVER),
    RelationSense.CLASSIFICATION: (SubjectRole.INSTANCE, SubjectRole.CATEGORY),
    RelationSense.COMPOSITION: (SubjectRole.WHOLE, SubjectRole.PART),
    RelationSense.OWNERSHIP: (SubjectRole.OWNER, SubjectRole.OWNED),
    RelationSense.AUTHORIZATION: (SubjectRole.GRANTEE, SubjectRole.GRANTED),
    RelationSense.EVIDENCE: (SubjectRole.EVIDENCE, SubjectRole.EVIDENCED),
}


class FormRelation(_FormModel):
    """One relation between a named anchor and the requested results.

    ``anchor`` names the instance the relation starts from; when omitted the goal
    subject is the anchor. ``counterpart`` names the other end when the operator
    names both, as in a path or a verification question. ``anchor_role`` and
    ``result_role`` state both ends so Core can reject a contradicting direction.
    """

    sense: RelationSense
    scope: RelationScope = RelationScope.ONE_SENSE
    anchor: Annotated[str, Field(pattern=_MENTION_ID)] | None = None
    counterpart: Annotated[str, Field(pattern=_MENTION_ID)] | None = None
    anchor_role: SubjectRole
    result_role: SubjectRole
    reach: RelationReach = RelationReach.ONE_HOP
    cue: SourceSpan
    # Words that state the reach apart from the relation words, as in 하위 리소스까지.
    reach_cue: SourceSpan | None = None

    @property
    def roles_consistent(self) -> bool:
        """Return whether the two stated roles are the two ends of the sense."""

        if SubjectRole.EITHER in {self.anchor_role, self.result_role}:
            return self.anchor_role is self.result_role
        return {self.anchor_role, self.result_role} == set(SENSE_ROLES[self.sense])

    @property
    def anchor_position(self) -> SubjectPosition | None:
        """Return the stored end the anchor occupies, or ``None`` for a role mismatch."""

        if self.anchor_role is SubjectRole.EITHER:
            return SubjectPosition.EITHER
        source_role, target_role = SENSE_ROLES[self.sense]
        if self.anchor_role is source_role:
            return SubjectPosition.SOURCE
        if self.anchor_role is target_role:
            return SubjectPosition.TARGET
        return None


class FormOrder(_FormModel):
    direction: OrderDirection
    limit: int = Field(default=10, ge=1, le=50)
    cue: SourceSpan | None = None


class FormMeasure(_FormModel):
    kind: MeasureKind
    group_by: GroupBy = GroupBy.NONE
    mention: Annotated[str, Field(pattern=_MENTION_ID)] | None = None
    order: FormOrder | None = None
    cue: SourceSpan | None = None


class DurationUnit(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"


class DurationValue(_FormModel):
    """One bounded relative duration, such as the last three days."""

    amount: int = Field(ge=1, le=10_000)
    unit: DurationUnit


class TemporalValue(_FormModel):
    """One typed temporal value; code computes instants from the trusted clock."""

    duration: DurationValue | None = None
    calendar_offset_days: int | None = Field(default=None, ge=-366, le=0)

    @model_validator(mode="after")
    def _one_value(self) -> TemporalValue:
        if (self.duration is None) == (self.calendar_offset_days is None):
            raise ValueError("temporal value MUST carry exactly one of duration or offset")
        return self


class FormTime(_FormModel):
    kind: TimeKind = TimeKind.CURRENT
    value: TemporalValue | None = None
    windows: Annotated[tuple[TemporalValue, ...], Field(max_length=2)] = ()
    cue: SourceSpan | None = None

    @model_validator(mode="after")
    def _value_matches_kind(self) -> FormTime:
        needs_value = self.kind in {TimeKind.WINDOW, TimeKind.AS_OF}
        if needs_value and (self.value is None or self.cue is None):
            raise ValueError("windowed and as-of time need a typed value and a cue span")
        if not needs_value and self.value is not None:
            raise ValueError("only windowed and as-of time carry a typed value")
        if self.kind is TimeKind.TWO_WINDOWS and (len(self.windows) != 2 or self.cue is None):
            raise ValueError("two-window time needs two typed windows and a cue span")
        if self.kind is not TimeKind.TWO_WINDOWS and self.windows:
            raise ValueError("only two-window time carries two typed windows")
        return self


class FormGoal(_FormModel):
    id: Annotated[str, Field(pattern=_GOAL_ID)]
    level: GoalLevel
    operation: GoalOperation
    subject: Annotated[str, Field(pattern=_MENTION_ID)] | None = None
    subject_scope: SubjectScope
    counterpart: Annotated[str, Field(pattern=_MENTION_ID)] | None = None
    filters: Annotated[tuple[FormFilter, ...], Field(max_length=8)] = ()
    relation: FormRelation | None = None
    measure: FormMeasure | None = None
    time: FormTime = FormTime()
    want: Want = Want.FACT
    depends_on: Annotated[
        tuple[Annotated[str, Field(pattern=_GOAL_ID)], ...], Field(max_length=3)
    ] = ()
    cue: SourceSpan
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def effective_operation(self) -> GoalOperation:
        """Return the canonical operation; an aggregate of a plain count is a count."""

        if (
            self.operation is GoalOperation.AGGREGATE
            and self.measure is not None
            and self.measure.kind is MeasureKind.COUNT
        ):
            return GoalOperation.COUNT
        return self.operation

    @property
    def restated_subject(self) -> bool:
        """Return whether one of the goal's own filters restates its subject."""

        return self.subject is not None and any(
            item.mention == self.subject for item in self.filters
        )


class AtomDiff(_FormModel):
    """One changed closed field of a goal in a competing reading."""

    field: Literal[
        "level",
        "operation",
        "subject",
        "subject_scope",
        "relation.sense",
        "relation.anchor",
        "relation.counterpart",
        "relation.anchor_role",
        "relation.result_role",
        "relation.reach",
        "measure.kind",
        "time.kind",
        "want",
    ]
    value: Annotated[str, Field(min_length=1, max_length=64)]


class FormAlternative(_FormModel):
    goal: Annotated[str, Field(pattern=_GOAL_ID)]
    atoms: Annotated[tuple[AtomDiff, ...], Field(min_length=1, max_length=MAX_ALTERNATIVE_ATOMS)]


class SemanticQuestionForm(_FormModel):
    """One bounded judgment pass over the current utterance."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    mentions: Annotated[tuple[FormMention, ...], Field(max_length=MAX_FORM_MENTIONS)] = ()
    goals: Annotated[tuple[FormGoal, ...], Field(min_length=1, max_length=MAX_FORM_GOALS)]
    alternatives: Annotated[
        tuple[FormAlternative, ...], Field(max_length=MAX_FORM_ALTERNATIVES)
    ] = ()
    # Runs of words the model judges to state no constraint; admission accounts every word.
    context: Annotated[tuple[SourceSpan, ...], Field(max_length=MAX_CONTEXT_SPANS)] = ()
    # Words that state a constraint no closed field expresses; they force a clarification.
    unsupported_constraints: Annotated[
        tuple[SourceSpan, ...], Field(max_length=MAX_UNSUPPORTED_CONSTRAINTS)
    ] = ()
    remaining_goals: bool = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _references_resolve(self) -> SemanticQuestionForm:
        mention_ids = [mention.id for mention in self.mentions]
        if len(mention_ids) != len(set(mention_ids)):
            raise ValueError("form mention ids MUST be unique")
        known_mentions = set(mention_ids)
        for mention in self.mentions:
            if mention.qualifier is not None and (
                mention.qualifier.mention not in known_mentions
                or mention.qualifier.mention == mention.id
            ):
                raise ValueError("form qualifier MUST cite another declared mention")
        goal_ids: list[str] = []
        for goal in self.goals:
            if goal.id in goal_ids:
                raise ValueError("form goal ids MUST be unique")
            if not set(goal.depends_on) <= set(goal_ids):
                raise ValueError("form goals MAY depend only on earlier goals")
            cited = {goal.subject} if goal.subject is not None else set()
            if goal.counterpart is not None:
                cited.add(goal.counterpart)
            cited.update(item.mention for item in goal.filters)
            if goal.relation is not None:
                cited.update(
                    item
                    for item in (goal.relation.anchor, goal.relation.counterpart)
                    if item is not None
                )
            if goal.measure is not None and goal.measure.mention is not None:
                cited.add(goal.measure.mention)
            if not cited <= known_mentions:
                raise ValueError("form goal cites an undeclared mention")
            goal_ids.append(goal.id)
        if any(alternative.goal not in goal_ids for alternative in self.alternatives):
            raise ValueError("form alternative cites an undeclared goal")
        if len(self.canonical_json().encode("utf-8")) > MAX_FORM_BYTES:
            raise ValueError("serialized question form exceeds its 6 KiB pass budget")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))

    def mention(self, mention_id: str) -> FormMention:
        return next(mention for mention in self.mentions if mention.id == mention_id)

    def literal_mentions(self) -> frozenset[str]:
        """Return the mentions whose quotes a plan uses verbatim as literal operands.

        A name-fragment filter reads its mention as the characters a name must contain.
        Any other mention is grounded, bound, or unsupported, so a wrong extent there
        cannot silently change a query.
        """

        return frozenset(
            item.mention
            for goal in self.goals
            for item in goal.filters
            if item.role is FilterRole.NAME_FRAGMENT and item.mention is not None
        )

    def declared_spans(self, *, context: bool = True) -> tuple[SourceSpan, ...]:
        """Return every span the form quotes: mentions, goal, filter, relation, time,
        and measure cues, unsupported constraints, and, unless excluded, context."""

        spans = [mention.span for mention in self.mentions]
        for goal in self.goals:
            spans.append(goal.cue)
            spans.extend(item.cue for item in goal.filters if item.cue is not None)
            if goal.relation is not None:
                spans.append(goal.relation.cue)
                if goal.relation.reach_cue is not None:
                    spans.append(goal.relation.reach_cue)
            if goal.time.cue is not None:
                spans.append(goal.time.cue)
            if goal.measure is not None and goal.measure.cue is not None:
                spans.append(goal.measure.cue)
            if (
                goal.measure is not None
                and goal.measure.order is not None
                and goal.measure.order.cue is not None
            ):
                spans.append(goal.measure.order.cue)
        spans.extend(self.unsupported_constraints)
        if context:
            spans.extend(self.context)
        return tuple(spans)

    def cited_mentions(self) -> frozenset[str]:
        """Return every mention a goal, filter, relation, measure, or qualifier cites."""

        cited: set[str] = set()
        for goal in self.goals:
            if goal.subject is not None:
                cited.add(goal.subject)
            if goal.counterpart is not None:
                cited.add(goal.counterpart)
            cited.update(item.mention for item in goal.filters)
            if goal.relation is not None:
                cited.update(
                    item
                    for item in (goal.relation.anchor, goal.relation.counterpart)
                    if item is not None
                )
            if goal.measure is not None and goal.measure.mention is not None:
                cited.add(goal.measure.mention)
        # Follow qualifier chains to a fixed point, so mention order never matters.
        while True:
            qualifiers = {
                mention.qualifier.mention
                for mention in self.mentions
                if mention.qualifier is not None and mention.id in cited
            }
            if qualifiers <= cited:
                return frozenset(cited)
            cited |= qualifiers


__all__ = [
    "MAX_CONTEXT_SPANS",
    "MAX_FORM_BYTES",
    "MAX_FORM_GOALS",
    "MAX_FORM_MENTIONS",
    "MAX_UNSUPPORTED_CONSTRAINTS",
    "AtomDiff",
    "DurationUnit",
    "DurationValue",
    "FilterRole",
    "FormAlternative",
    "FormFilter",
    "FormGoal",
    "FormMeasure",
    "FormMention",
    "FormQualifier",
    "FormRelation",
    "FormTime",
    "GoalLevel",
    "GoalOperation",
    "GroupBy",
    "MeasureKind",
    "MentionDomain",
    "MentionForm",
    "RelationReach",
    "RelationScope",
    "RelationSense",
    "SemanticQuestionForm",
    "SourceSpan",
    "SENSE_ROLES",
    "SubjectPosition",
    "SubjectRole",
    "SubjectScope",
    "TemporalValue",
    "TimeKind",
    "Want",
]

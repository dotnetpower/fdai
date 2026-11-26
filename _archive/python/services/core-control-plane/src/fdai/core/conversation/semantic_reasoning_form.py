"""Compatibility module for the shared semantic question-form contract.

The closed question form now lives in the service contracts; Core modules keep importing it
from here, and each name is re-exported explicitly so type checking sees it.
"""

from __future__ import annotations

from fdai_service_contracts.semantic_question_form import (
    MAX_CONTEXT_SPANS as MAX_CONTEXT_SPANS,
)
from fdai_service_contracts.semantic_question_form import (
    MAX_FORM_BYTES as MAX_FORM_BYTES,
)
from fdai_service_contracts.semantic_question_form import (
    MAX_FORM_GOALS as MAX_FORM_GOALS,
)
from fdai_service_contracts.semantic_question_form import (
    MAX_FORM_MENTIONS as MAX_FORM_MENTIONS,
)
from fdai_service_contracts.semantic_question_form import (
    MAX_UNSUPPORTED_CONSTRAINTS as MAX_UNSUPPORTED_CONSTRAINTS,
)
from fdai_service_contracts.semantic_question_form import (
    SENSE_ROLES as SENSE_ROLES,
)
from fdai_service_contracts.semantic_question_form import (
    AtomDiff as AtomDiff,
)
from fdai_service_contracts.semantic_question_form import (
    Comparator as Comparator,
)
from fdai_service_contracts.semantic_question_form import (
    DurationUnit as DurationUnit,
)
from fdai_service_contracts.semantic_question_form import (
    DurationValue as DurationValue,
)
from fdai_service_contracts.semantic_question_form import (
    FilterRole as FilterRole,
)
from fdai_service_contracts.semantic_question_form import (
    FormAlternative as FormAlternative,
)
from fdai_service_contracts.semantic_question_form import (
    FormFilter as FormFilter,
)
from fdai_service_contracts.semantic_question_form import (
    FormGoal as FormGoal,
)
from fdai_service_contracts.semantic_question_form import (
    FormMeasure as FormMeasure,
)
from fdai_service_contracts.semantic_question_form import (
    FormMention as FormMention,
)
from fdai_service_contracts.semantic_question_form import (
    FormQualifier as FormQualifier,
)
from fdai_service_contracts.semantic_question_form import (
    FormRelation as FormRelation,
)
from fdai_service_contracts.semantic_question_form import (
    FormTime as FormTime,
)
from fdai_service_contracts.semantic_question_form import (
    GoalLevel as GoalLevel,
)
from fdai_service_contracts.semantic_question_form import (
    GoalOperation as GoalOperation,
)
from fdai_service_contracts.semantic_question_form import (
    GroupBy as GroupBy,
)
from fdai_service_contracts.semantic_question_form import (
    MeasureKind as MeasureKind,
)
from fdai_service_contracts.semantic_question_form import (
    MentionDomain as MentionDomain,
)
from fdai_service_contracts.semantic_question_form import (
    MentionForm as MentionForm,
)
from fdai_service_contracts.semantic_question_form import (
    MetricComparison as MetricComparison,
)
from fdai_service_contracts.semantic_question_form import (
    MetricQualifier as MetricQualifier,
)
from fdai_service_contracts.semantic_question_form import (
    MetricUnit as MetricUnit,
)
from fdai_service_contracts.semantic_question_form import (
    RelationAnchorScope as RelationAnchorScope,
)
from fdai_service_contracts.semantic_question_form import (
    RelationReach as RelationReach,
)
from fdai_service_contracts.semantic_question_form import (
    RelationScope as RelationScope,
)
from fdai_service_contracts.semantic_question_form import (
    RelationSense as RelationSense,
)
from fdai_service_contracts.semantic_question_form import (
    SemanticQuestionForm as SemanticQuestionForm,
)
from fdai_service_contracts.semantic_question_form import (
    SourceSpan as SourceSpan,
)
from fdai_service_contracts.semantic_question_form import (
    SubjectPosition as SubjectPosition,
)
from fdai_service_contracts.semantic_question_form import (
    SubjectRole as SubjectRole,
)
from fdai_service_contracts.semantic_question_form import (
    SubjectScope as SubjectScope,
)
from fdai_service_contracts.semantic_question_form import (
    TemporalValue as TemporalValue,
)
from fdai_service_contracts.semantic_question_form import (
    TimeKind as TimeKind,
)
from fdai_service_contracts.semantic_question_form import (
    Want as Want,
)

__all__ = [
    "MAX_CONTEXT_SPANS",
    "MAX_FORM_BYTES",
    "MAX_FORM_GOALS",
    "MAX_FORM_MENTIONS",
    "MAX_UNSUPPORTED_CONSTRAINTS",
    "AtomDiff",
    "Comparator",
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
    "MetricComparison",
    "MetricQualifier",
    "MetricUnit",
    "RelationAnchorScope",
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

"""Deterministic answer-shape planning for read-only operator conversations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile


class AnswerIntent(StrEnum):
    DEFINITION = "definition"
    WHY = "why"
    PROCEDURE = "procedure"
    COMPARISON = "comparison"
    DIAGNOSIS = "diagnosis"
    STATUS = "status"
    LIST = "list"
    SUMMARY = "summary"
    PROPOSAL = "proposal"
    OPEN_QUESTION = "open_question"
    GREETING = "greeting"


class DetailLevel(StrEnum):
    BRIEF = "brief"
    STANDARD = "standard"
    DEEP = "deep"


class AnswerFormat(StrEnum):
    PROSE = "prose"
    BULLETS = "bullets"
    NUMBERED_STEPS = "numbered_steps"
    TABLE = "table"
    CHART = "chart"
    CHECKLIST = "checklist"
    MIXED = "mixed"


class EvidenceRequirement(StrEnum):
    NONE = "none"
    SCREEN = "screen"
    CATALOG = "catalog"
    SERVER_READ_MODEL = "server_read_model"
    AGENT_OWNED = "agent_owned"


class AudienceLevel(StrEnum):
    GENERAL = "general"
    BEGINNER = "beginner"
    TECHNICAL = "technical"


class DiscussPolicy(StrEnum):
    SKIP = "skip"
    SHADOW = "shadow"
    SELECTIVE = "selective"


class AnswerModifier(StrEnum):
    """Schema-ready presentation facet selected by semantic judgment."""

    BRIEF = "brief"
    DEEP = "deep"
    TABLE = "table"
    CHART = "chart"
    STEPS = "steps"
    EVIDENCE = "evidence"
    BEGINNER = "beginner"
    TECHNICAL = "technical"
    MULTIPLE_PERSPECTIVES = "multiple_perspectives"


class AnswerSection(StrEnum):
    DEFINITION = "definition"
    PURPOSE = "purpose"
    CONTROL_LOOP_POSITION = "control_loop_position"
    CORE_PARTS = "core_parts"
    EXAMPLE = "example"
    CONCLUSION = "conclusion"
    DIRECT_CAUSE = "direct_cause"
    EVIDENCE = "evidence"
    CONSTRAINTS = "constraints"
    PRECONDITIONS = "preconditions"
    STEPS = "steps"
    VERIFICATION = "verification"
    RECOVERY = "recovery"
    CRITERIA = "criteria"
    TRADE_OFFS = "trade_offs"
    RECOMMENDATION = "recommendation"
    SYMPTOMS = "symptoms"
    HYPOTHESES = "hypotheses"
    CHECKS = "checks"
    FIX = "fix"
    STATE = "state"
    METRICS = "metrics"
    ATTENTION = "attention"
    LINKS = "links"
    ITEMS = "items"
    TARGET_SCOPE = "target_scope"
    MODE = "mode"
    SAFETY_INVARIANTS = "safety_invariants"
    RESULT = "result"
    OUTCOME = "outcome"
    IMPORTANT_FACTS = "important_facts"
    UNRESOLVED = "unresolved"
    NEXT_STEP = "next_step"
    ASSUMPTIONS = "assumptions"
    BOUNDED_ANSWER = "bounded_answer"
    UNCERTAINTY = "uncertainty"
    GREETING = "greeting"


@dataclass(frozen=True, slots=True)
class AnswerPlan:
    intent: AnswerIntent
    detail_level: DetailLevel
    format: AnswerFormat
    sections: tuple[AnswerSection, ...]
    evidence_requirement: EvidenceRequirement
    audience_level: AudienceLevel
    clarification: str | None
    max_words: int
    discuss: DiscussPolicy
    subject: str
    explicit_overrides: tuple[str, ...] = ()
    preference_applied: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "detail_level": self.detail_level.value,
            "format": self.format.value,
            "sections": [section.value for section in self.sections],
            "evidence_requirement": self.evidence_requirement.value,
            "audience_level": self.audience_level.value,
            "clarification": self.clarification,
            "max_words": self.max_words,
            "discuss": self.discuss.value,
            "subject": self.subject,
            "explicit_overrides": list(self.explicit_overrides),
            "preference_applied": self.preference_applied,
        }


_SECTIONS: Final[dict[AnswerIntent, tuple[AnswerSection, ...]]] = {
    AnswerIntent.DEFINITION: (
        AnswerSection.DEFINITION,
        AnswerSection.PURPOSE,
        AnswerSection.CONTROL_LOOP_POSITION,
        AnswerSection.CORE_PARTS,
        AnswerSection.EXAMPLE,
    ),
    AnswerIntent.WHY: (
        AnswerSection.CONCLUSION,
        AnswerSection.DIRECT_CAUSE,
        AnswerSection.EVIDENCE,
        AnswerSection.CONSTRAINTS,
    ),
    AnswerIntent.PROCEDURE: (
        AnswerSection.PRECONDITIONS,
        AnswerSection.STEPS,
        AnswerSection.VERIFICATION,
        AnswerSection.RECOVERY,
    ),
    AnswerIntent.COMPARISON: (
        AnswerSection.CRITERIA,
        AnswerSection.ITEMS,
        AnswerSection.TRADE_OFFS,
        AnswerSection.RECOMMENDATION,
    ),
    AnswerIntent.DIAGNOSIS: (
        AnswerSection.SYMPTOMS,
        AnswerSection.HYPOTHESES,
        AnswerSection.CHECKS,
        AnswerSection.FIX,
        AnswerSection.VERIFICATION,
    ),
    AnswerIntent.STATUS: (
        AnswerSection.STATE,
        AnswerSection.METRICS,
        AnswerSection.ATTENTION,
        AnswerSection.LINKS,
    ),
    AnswerIntent.LIST: (AnswerSection.ITEMS,),
    AnswerIntent.PROPOSAL: (
        AnswerSection.RESULT,
        AnswerSection.TARGET_SCOPE,
        AnswerSection.MODE,
        AnswerSection.SAFETY_INVARIANTS,
    ),
    AnswerIntent.SUMMARY: (
        AnswerSection.OUTCOME,
        AnswerSection.IMPORTANT_FACTS,
        AnswerSection.UNRESOLVED,
        AnswerSection.NEXT_STEP,
    ),
    AnswerIntent.OPEN_QUESTION: (
        AnswerSection.ASSUMPTIONS,
        AnswerSection.BOUNDED_ANSWER,
        AnswerSection.UNCERTAINTY,
    ),
    AnswerIntent.GREETING: (
        AnswerSection.GREETING,
        AnswerSection.NEXT_STEP,
    ),
}


def build_answer_plan(
    subject: str,
    *,
    intent: AnswerIntent = AnswerIntent.OPEN_QUESTION,
    requested_facets: Sequence[AnswerModifier | str] = (),
    route_id: str | None = None,
    preferences: ResponsePreferenceProfile | None = None,
) -> AnswerPlan:
    """Build one response plan from a schema-validated semantic judgment."""
    modifiers = tuple(AnswerModifier(item) for item in requested_facets)
    if len(modifiers) != len(set(modifiers)):
        raise ValueError("answer plan requested facets MUST be unique")
    detail = (
        DetailLevel.BRIEF
        if intent in {AnswerIntent.STATUS, AnswerIntent.LIST, AnswerIntent.GREETING}
        else DetailLevel.STANDARD
    )
    format_ = _default_format(intent)
    evidence = _default_evidence(intent, route_id)
    audience = AudienceLevel.GENERAL
    overrides: list[str] = []
    normalized_subject = subject.strip()
    preference_applied = False

    if preferences is not None:
        preferred_detail = preferences.detail_for(intent)
        preferred_format = preferences.format_for(intent)
        if preferred_detail is not None:
            detail = preferred_detail
            preference_applied = True
        if preferred_format is not None:
            format_ = preferred_format
            preference_applied = True

    discuss = DiscussPolicy.SKIP
    for modifier in modifiers:
        overrides.append(modifier.value)
        if modifier is AnswerModifier.BRIEF:
            detail = DetailLevel.BRIEF
        elif modifier is AnswerModifier.DEEP:
            detail = DetailLevel.DEEP
        elif modifier is AnswerModifier.TABLE:
            format_ = AnswerFormat.TABLE
        elif modifier is AnswerModifier.CHART:
            format_ = AnswerFormat.CHART
        elif modifier is AnswerModifier.STEPS:
            format_ = AnswerFormat.NUMBERED_STEPS
        elif modifier is AnswerModifier.EVIDENCE:
            evidence = max(evidence, EvidenceRequirement.SERVER_READ_MODEL, key=_evidence_rank)
        elif modifier is AnswerModifier.BEGINNER:
            audience = AudienceLevel.BEGINNER
        elif modifier is AnswerModifier.TECHNICAL:
            audience = AudienceLevel.TECHNICAL
        elif modifier is AnswerModifier.MULTIPLE_PERSPECTIVES:
            discuss = DiscussPolicy.SELECTIVE
    return AnswerPlan(
        intent=intent,
        detail_level=detail,
        format=format_,
        sections=_SECTIONS[intent],
        evidence_requirement=evidence,
        audience_level=audience,
        clarification=None,
        max_words={DetailLevel.BRIEF: 80, DetailLevel.STANDARD: 260, DetailLevel.DEEP: 650}[detail],
        discuss=discuss,
        subject=normalized_subject,
        explicit_overrides=tuple(overrides),
        preference_applied=preference_applied,
    )


def answer_plan_directive(plan: AnswerPlan) -> str:
    """Render a bounded instruction block for Bragi's prose synthesis."""
    sections = ", ".join(section.value for section in plan.sections)
    return (
        "AnswerPlan (presentation only; never changes evidence authority):\n"
        f"intent={plan.intent.value}; detail={plan.detail_level.value}; "
        f"format={plan.format.value}; audience={plan.audience_level.value}; "
        f"max_words={plan.max_words}; sections={sections}.\n"
        "Honor the requested shape, omit a section when evidence is unavailable, "
        "and never fill a missing section by guessing."
    )


def _default_format(intent: AnswerIntent) -> AnswerFormat:
    if intent is AnswerIntent.COMPARISON:
        return AnswerFormat.TABLE
    if intent is AnswerIntent.PROCEDURE:
        return AnswerFormat.NUMBERED_STEPS
    if intent in {AnswerIntent.LIST, AnswerIntent.STATUS}:
        return AnswerFormat.BULLETS
    if intent in {AnswerIntent.DIAGNOSIS, AnswerIntent.PROPOSAL, AnswerIntent.SUMMARY}:
        return AnswerFormat.MIXED
    return AnswerFormat.PROSE


def _default_evidence(intent: AnswerIntent, route_id: str | None) -> EvidenceRequirement:
    if intent is AnswerIntent.GREETING:
        # A greeting is not a question about the screen - never force screen
        # evidence, so the narrator answers briefly instead of reciting facts.
        return EvidenceRequirement.NONE
    if intent is AnswerIntent.DEFINITION:
        return EvidenceRequirement.CATALOG
    if intent in {AnswerIntent.WHY, AnswerIntent.DIAGNOSIS, AnswerIntent.PROPOSAL}:
        return EvidenceRequirement.SERVER_READ_MODEL
    if route_id:
        return EvidenceRequirement.SCREEN
    return EvidenceRequirement.NONE


def _evidence_rank(value: EvidenceRequirement) -> int:
    return list(EvidenceRequirement).index(value)


__all__ = [
    "AnswerFormat",
    "AnswerIntent",
    "AnswerModifier",
    "AnswerPlan",
    "AnswerSection",
    "AudienceLevel",
    "DetailLevel",
    "DiscussPolicy",
    "EvidenceRequirement",
    "answer_plan_directive",
    "build_answer_plan",
]

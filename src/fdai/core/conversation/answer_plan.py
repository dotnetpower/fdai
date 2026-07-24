"""Deterministic answer-shape planning for read-only operator conversations."""

from __future__ import annotations

import re
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

_INTENT_PATTERNS: Final[tuple[tuple[AnswerIntent, re.Pattern[str]], ...]] = (
    (
        # Greeting / smalltalk only when the WHOLE utterance is a pleasantry
        # (anchored, no operational keyword follows). A mixed prompt like
        # "hi, what's the status?" does not match and falls through to STATUS.
        AnswerIntent.GREETING,
        re.compile(
            r"^[\s\W]*(?:"
            r"annyeong|"
            r"안녕(?:하세요|하십니까|하셔요)?|"
            r"반가워(?:요)?|반갑습니다|"
            r"하이|헬로|"
            r"hello|hi|hey|good\s+(?:morning|afternoon|evening)|"
            r"고맙습니다|고마워(?:요)?|"
            r"감사(?:합니다|해요|드려요)?|"
            r"thank\s*you|thanks|"
            r"잘\s*지내(?:세요|셔어요)?|"
            r"좋은\s*(?:아침|하루)"
            r")[\s\W]*$",
            re.I,
        ),
    ),
    (
        AnswerIntent.COMPARISON,
        re.compile(r"\b(compare|comparison|versus|vs\.?|difference)\b|비교|차이", re.I),
    ),
    (
        AnswerIntent.PROCEDURE,
        re.compile(
            r"\b(how (?:do|can|should|to)|steps?|procedure|runbook)\b|어떻게|단계|절차",
            re.I,
        ),
    ),
    (AnswerIntent.WHY, re.compile(r"\bwhy\b|이유|왜", re.I)),
    (
        AnswerIntent.DIAGNOSIS,
        re.compile(
            r"\b(diagnos|troubleshoot|investigat|root cause|broken|failing)\w*\b"
            r"|진단|조사|원인",
            re.I,
        ),
    ),
    (AnswerIntent.STATUS, re.compile(r"\b(status|state|current|pending|health)\b|상태|현황", re.I)),
    (AnswerIntent.LIST, re.compile(r"\b(list|show all|what are all|which)\b|목록|나열", re.I)),
    (
        AnswerIntent.PROPOSAL,
        re.compile(r"\b(propose|proposal|request action|remediate)\w*\b|제안|조치 요청", re.I),
    ),
    (AnswerIntent.SUMMARY, re.compile(r"\b(summari[sz]e|summary|recap)\b|요약|정리", re.I)),
    (
        AnswerIntent.DEFINITION,
        re.compile(
            r"\b(what is|what are|define|definition|meaning|explain)\b"
            r"|무엇|뭐야|정의|설명",
            re.I,
        ),
    ),
)

_MODIFIERS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("brief", re.compile(r"\b(briefly|short answer|concise)\b|결론만|짧게", re.I)),
    ("deep", re.compile(r"\b(in detail|deep dive|thoroughly)\b|자세히|심층적으로", re.I)),
    ("table", re.compile(r"\b(as a table|table format)\b|표로|비교표", re.I)),
    ("steps", re.compile(r"\b(step by step|as steps)\b|단계별로|절차로", re.I)),
    (
        "evidence",
        re.compile(r"\b(with evidence|cite sources?|with citations?)\b|근거까지|인용", re.I),
    ),
    ("beginner", re.compile(r"\b(for a beginner|beginner friendly)\b|초보자 기준", re.I)),
    ("technical", re.compile(r"\b(technically|technical detail)\b|기술적으로", re.I)),
)


def build_answer_plan(
    prompt: str,
    *,
    route_id: str | None = None,
    preferences: ResponsePreferenceProfile | None = None,
) -> AnswerPlan:
    """Build one deterministic response plan without model or provider calls."""
    intent = _intent(prompt)
    detail = (
        DetailLevel.BRIEF
        if intent in {AnswerIntent.STATUS, AnswerIntent.LIST, AnswerIntent.GREETING}
        else DetailLevel.STANDARD
    )
    format_ = _default_format(intent)
    evidence = _default_evidence(intent, route_id)
    audience = AudienceLevel.GENERAL
    overrides: list[str] = []
    subject = prompt.strip()
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

    matched = sorted(
        (
            (match.start(), name, pattern)
            for name, pattern in _MODIFIERS
            if (match := pattern.search(subject)) is not None
        ),
        key=lambda item: item[0],
    )
    for _, name, _ in matched:
        overrides.append(name)
        if name == "brief":
            detail = DetailLevel.BRIEF
        elif name == "deep":
            detail = DetailLevel.DEEP
        elif name == "table":
            format_ = AnswerFormat.TABLE
        elif name == "steps":
            format_ = AnswerFormat.NUMBERED_STEPS
        elif name == "evidence":
            evidence = max(evidence, EvidenceRequirement.SERVER_READ_MODEL, key=_evidence_rank)
        elif name == "beginner":
            audience = AudienceLevel.BEGINNER
        elif name == "technical":
            audience = AudienceLevel.TECHNICAL

    for _, _, pattern in matched:
        subject = pattern.sub(" ", subject)
    subject = re.sub(r"\s+", " ", subject).strip(" ,.-") or prompt.strip()
    return AnswerPlan(
        intent=intent,
        detail_level=detail,
        format=format_,
        sections=_SECTIONS[intent],
        evidence_requirement=evidence,
        audience_level=audience,
        clarification=None,
        max_words={DetailLevel.BRIEF: 80, DetailLevel.STANDARD: 260, DetailLevel.DEEP: 650}[detail],
        discuss=DiscussPolicy.SKIP,
        subject=subject,
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


def _intent(prompt: str) -> AnswerIntent:
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(prompt):
            return intent
    return AnswerIntent.OPEN_QUESTION


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
    "AnswerPlan",
    "AnswerSection",
    "AudienceLevel",
    "DetailLevel",
    "DiscussPolicy",
    "EvidenceRequirement",
    "answer_plan_directive",
    "build_answer_plan",
]

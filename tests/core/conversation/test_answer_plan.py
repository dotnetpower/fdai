"""Bilingual frozen corpus for deterministic AnswerPlan construction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.conversation.answer_plan import (
    AnswerFormat,
    AnswerIntent,
    AudienceLevel,
    DetailLevel,
    DiscussPolicy,
    EvidenceRequirement,
    build_answer_plan,
)
from fdai.core.conversation.answer_preferences import ResponsePreferenceProfile


@pytest.mark.parametrize(
    ("prompt", "intent"),
    [
        ("What is ActionType?", AnswerIntent.DEFINITION),
        ("ActionType이 무엇인지 설명해줘", AnswerIntent.DEFINITION),
        ("Why was this denied?", AnswerIntent.WHY),
        ("왜 거부됐어?", AnswerIntent.WHY),
        ("How do I investigate this?", AnswerIntent.PROCEDURE),
        ("이걸 어떻게 조사해?", AnswerIntent.PROCEDURE),
        ("Compare T1 and T2", AnswerIntent.COMPARISON),
        ("T1과 T2 차이를 비교해줘", AnswerIntent.COMPARISON),
        ("Diagnose this failing workflow", AnswerIntent.DIAGNOSIS),
        ("실패한 workflow 원인을 진단해줘", AnswerIntent.DIAGNOSIS),
        ("Show current status", AnswerIntent.STATUS),
        ("현재 상태 알려줘", AnswerIntent.STATUS),
        ("List the agents", AnswerIntent.LIST),
        ("agent 목록 보여줘", AnswerIntent.LIST),
        ("Propose remediation", AnswerIntent.PROPOSAL),
        ("교정 조치를 제안해줘", AnswerIntent.PROPOSAL),
        ("Summarize the incident", AnswerIntent.SUMMARY),
        ("incident를 요약해줘", AnswerIntent.SUMMARY),
        ("Tell me about this screen", AnswerIntent.OPEN_QUESTION),
        ("이 화면 알려줘", AnswerIntent.OPEN_QUESTION),
        ("안녕", AnswerIntent.GREETING),
        ("안녕하세요", AnswerIntent.GREETING),
        ("hi", AnswerIntent.GREETING),
        ("hello", AnswerIntent.GREETING),
        ("good morning", AnswerIntent.GREETING),
        ("고마워", AnswerIntent.GREETING),
        ("thanks", AnswerIntent.GREETING),
    ],
)
def test_bilingual_intent_corpus(prompt: str, intent: AnswerIntent) -> None:
    plan = build_answer_plan(prompt, route_id="audit")

    assert plan.intent is intent
    assert plan.sections
    assert plan.discuss is DiscussPolicy.SKIP


def test_explicit_modifiers_override_defaults_and_are_removed_from_subject() -> None:
    plan = build_answer_plan(
        "Compare T1 and T2 briefly, step by step, with evidence, for a beginner"
    )

    assert plan.intent is AnswerIntent.COMPARISON
    assert plan.detail_level is DetailLevel.BRIEF
    assert plan.format is AnswerFormat.NUMBERED_STEPS
    assert plan.evidence_requirement is EvidenceRequirement.SERVER_READ_MODEL
    assert plan.audience_level is AudienceLevel.BEGINNER
    assert plan.explicit_overrides == ("brief", "steps", "evidence", "beginner")
    assert "briefly" not in plan.subject


def test_korean_deep_table_and_technical_modifiers() -> None:
    plan = build_answer_plan("T1과 T2를 자세히 비교표로 기술적으로 설명해줘")

    assert plan.detail_level is DetailLevel.DEEP
    assert plan.format is AnswerFormat.TABLE
    assert plan.audience_level is AudienceLevel.TECHNICAL
    assert plan.max_words == 650


@pytest.mark.parametrize(
    "prompt",
    [
        "DB 목록을 테이블로 보여줘",
        "DB 목록을 테이블 형식으로 보여줘",
        "DB 목록을 표로 보여줘",
    ],
)
def test_korean_table_synonyms_preserve_inventory_subject(prompt: str) -> None:
    plan = build_answer_plan(prompt)

    assert plan.format is AnswerFormat.TABLE
    assert plan.explicit_overrides == ("table",)
    assert "DB 목록" in plan.subject


@pytest.mark.parametrize("prompt", ["리소스를 그래프로 보여줘", "Show resources as a chart"])
def test_explicit_chart_modifier_selects_chart_format(prompt: str) -> None:
    plan = build_answer_plan(prompt)

    assert plan.format is AnswerFormat.CHART
    assert plan.explicit_overrides == ("chart",)


@pytest.mark.parametrize(
    "prompt",
    [
        "Could you plot the past week's measured chat token consumption as a "
        "daily time-series chart, using current read-only usage evidence?",
        "Show this as a weekly bar graph, please.",
        "Plot the trend as a monthly line chart.",
        "일주일치 사용량을 하루 단위 꺾은선 차트로 보여줘",
    ],
)
def test_chart_modifier_allows_descriptive_words_before_chart_noun(prompt: str) -> None:
    # A real request rarely says the bare phrase "as a chart" - it usually
    # qualifies the chart with a cadence/style word ("daily time-series",
    # "weekly bar", "monthly line"). The modifier must still select CHART.
    plan = build_answer_plan(prompt)

    assert plan.format is AnswerFormat.CHART
    assert plan.explicit_overrides == ("chart",)


def test_definition_standard_shape_is_not_one_line() -> None:
    plan = build_answer_plan("What is ActionType?")

    assert plan.detail_level is DetailLevel.STANDARD
    assert len(plan.sections) == 5
    assert plan.sections[0].value == "definition"
    assert plan.sections[-1].value == "example"


def test_last_current_turn_detail_modifier_wins() -> None:
    plan = build_answer_plan("In detail, but briefly explain ActionType")

    assert plan.detail_level is DetailLevel.BRIEF
    assert plan.explicit_overrides == ("deep", "brief")

    reversed_plan = build_answer_plan("Briefly, but in detail explain ActionType")
    assert reversed_plan.detail_level is DetailLevel.DEEP
    assert reversed_plan.explicit_overrides == ("brief", "deep")


def test_current_turn_overrides_stored_intent_preferences() -> None:
    preferences = ResponsePreferenceProfile(
        locale="en",
        default_detail=DetailLevel.DEEP,
        default_format=AnswerFormat.BULLETS,
        intent_detail={AnswerIntent.COMPARISON: DetailLevel.DEEP},
        intent_format={AnswerIntent.COMPARISON: AnswerFormat.TABLE},
        explicit_only=False,
        updated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )

    preferred = build_answer_plan("Compare T1 and T2", preferences=preferences)
    default_format = build_answer_plan("What is ActionType?", preferences=preferences)
    overridden = build_answer_plan(
        "Compare T1 and T2 briefly, step by step",
        preferences=preferences,
    )

    assert preferred.detail_level is DetailLevel.DEEP
    assert preferred.format is AnswerFormat.TABLE
    assert preferred.preference_applied is True
    assert default_format.format is AnswerFormat.BULLETS
    assert overridden.detail_level is DetailLevel.BRIEF
    assert overridden.format is AnswerFormat.NUMBERED_STEPS
    assert overridden.preference_applied is True


def test_explicit_only_profile_does_not_change_plan_defaults() -> None:
    preferences = ResponsePreferenceProfile(
        locale="ko",
        default_detail=DetailLevel.DEEP,
        default_format=AnswerFormat.BULLETS,
        intent_detail={AnswerIntent.DEFINITION: DetailLevel.DEEP},
        intent_format={AnswerIntent.DEFINITION: AnswerFormat.CHECKLIST},
        explicit_only=True,
        updated_at=datetime(2026, 7, 17, tzinfo=UTC),
    )

    plan = build_answer_plan("ActionType이 뭐야?", preferences=preferences)

    assert plan.detail_level is DetailLevel.STANDARD
    assert plan.format is AnswerFormat.PROSE
    assert plan.preference_applied is False


def test_greeting_is_brief_and_needs_no_screen_evidence() -> None:
    # A bare greeting must not force screen evidence, so the narrator answers
    # briefly instead of reciting screen facts (which would spawn atomic
    # claims and risk a false "unverified" on a friendly reply).
    plan = build_answer_plan("안녕", route_id="overview")

    assert plan.intent is AnswerIntent.GREETING
    assert plan.detail_level is DetailLevel.BRIEF
    assert plan.evidence_requirement is EvidenceRequirement.NONE
    assert plan.max_words == 80


@pytest.mark.parametrize(
    ("prompt", "intent"),
    [
        # A greeting followed by a real question keeps the operational intent.
        ("안녕, 현재 상태 알려줘", AnswerIntent.STATUS),
        ("hi, what is ActionType?", AnswerIntent.DEFINITION),
        ("hello, why was this denied?", AnswerIntent.WHY),
    ],
)
def test_greeting_prefix_does_not_swallow_operational_intent(
    prompt: str, intent: AnswerIntent
) -> None:
    assert build_answer_plan(prompt, route_id="overview").intent is intent

"""Bilingual frozen corpus for deterministic AnswerPlan construction."""

from __future__ import annotations

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

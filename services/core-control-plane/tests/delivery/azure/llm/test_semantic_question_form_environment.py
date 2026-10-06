"""Only the question form and its blind reader receive the safe environment context."""

from __future__ import annotations

from fdai.core.conversation.semantic_environment_context import bind_environment_context
from fdai.delivery.azure.llm.semantic_question_form_environment import with_environment

_CONTEXT = {
    "kind": "resource_groups",
    "complete": True,
    "resource_groups": [
        {"name": "rg-fdai-dev-krc", "location": "koreacentral"},
        {"name": "rg-held", "location": "koreacentral"},
    ],
}


def test_eligible_calls_receive_the_context_and_others_are_unchanged() -> None:
    payload = {"utterance": "fdai 관련 리소스 그룹"}

    with bind_environment_context(_CONTEXT):
        form = with_environment("semantic-question-form", payload, hides=lambda _text: False)
        reader = with_environment(
            "semantic-constraint-extraction", payload, hides=lambda _text: False
        )
        concept = with_environment("semantic-concept-selection", payload, hides=lambda _text: False)

    assert form["environment"]["resource_groups"][0]["name"] == "rg-fdai-dev-krc"
    assert form["environment"]["complete"] is True
    assert reader["environment"] == form["environment"]
    assert concept is payload
    assert payload == {"utterance": "fdai 관련 리소스 그룹"}


def test_without_a_bound_context_the_payload_is_unchanged() -> None:
    payload = {"utterance": "fdai"}

    assert with_environment("semantic-question-form", payload, hides=lambda _t: False) is payload


def test_a_name_the_detectors_flag_is_withheld_and_the_list_is_incomplete() -> None:
    with bind_environment_context(_CONTEXT):
        form = with_environment(
            "semantic-question-form", {"utterance": "q"}, hides=lambda text: text == "rg-held"
        )

    assert [item["name"] for item in form["environment"]["resource_groups"]] == ["rg-fdai-dev-krc"]
    assert form["environment"]["withheld"] == 1
    assert form["environment"]["complete"] is False


def test_a_name_the_provider_redactor_rewrites_is_withheld() -> None:
    context = {
        "kind": "resource_groups",
        "complete": True,
        "resource_groups": [
            {"name": "rg-app", "location": "koreacentral"},
            {
                "name": "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/x",
                "location": "koreacentral",
            },
        ],
    }

    with bind_environment_context(context):
        form = with_environment(
            "semantic-question-form", {"utterance": "q"}, hides=lambda _t: False
        )

    assert [item["name"] for item in form["environment"]["resource_groups"]] == ["rg-app"]
    assert form["environment"]["withheld"] == 1

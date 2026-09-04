"""Strict structured-output contracts for semantic judgment."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.conversation.conversation_preflight import ConversationPreflightProposal
from fdai.delivery.azure.llm.semantic_judgment import _strict_response_format
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def _assert_strict_objects(value: object) -> None:
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        assert not {
            "default",
            "title",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
        }.intersection(value)
        for nested in value.values():
            _assert_strict_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_strict_objects(nested)


def test_semantic_judgment_uses_strict_structured_output() -> None:
    response_format = _strict_response_format(
        SemanticJudgmentProposal.model_json_schema(),
        name="semantic-judgment",
    )

    assert response_format["type"] == "json_schema"
    envelope = response_format["json_schema"]
    assert isinstance(envelope, Mapping)
    assert envelope["name"] == "semantic-judgment"
    assert envelope["strict"] is True
    _assert_strict_objects(envelope["schema"])


def test_conversation_preflight_uses_the_same_strict_contract() -> None:
    response_format = _strict_response_format(
        ConversationPreflightProposal.model_json_schema(),
        name="conversation-preflight",
    )

    envelope = response_format["json_schema"]
    assert isinstance(envelope, Mapping)
    _assert_strict_objects(envelope["schema"])

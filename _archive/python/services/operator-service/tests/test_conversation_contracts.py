"""Regression contracts for conversation family boundary types."""

from fdai_operator_service.families.conversation.contracts import ConversationEventStream


def test_conversation_event_stream_is_a_protocol() -> None:
    assert ConversationEventStream._is_protocol

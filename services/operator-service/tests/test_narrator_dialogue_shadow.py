"""Shadow dialogue-state behavior of the service-local narrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai_operator_service.adapters.local_narrator import LocalAzureNarratorAdapters
from fdai_operator_service.adapters.narrator_dialogue_shadow import (
    dialogue_shadow_receipt,
    retain_dialogue_shadow,
    shadow_dialogue_state,
)
from fdai_operator_service.adapters.narrator_payloads import narrator_message_plan
from fdai_operator_service.families.conversation.contracts import (
    ConversationStreamRequest,
    PrincipalScope,
)
from fdai_operator_service.postgres_dialogue_snapshot import DialogueSnapshotStoreError
from fdai_service_contracts.dialogue_state import DialogueState

from .test_local_narrator import FallbackAdapters, RecordingHttpClient, _artifact

NOW = datetime(2026, 10, 28, tzinfo=UTC)
SECRET = "고혈압·당뇨병 SECRET-CONTENT"


class _Writer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, DialogueState]] = []

    async def append(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        state: DialogueState,
        recorded_at: datetime,
    ) -> bool:
        assert recorded_at.tzinfo is not None
        if self.error is not None:
            raise self.error
        self.calls.append((principal_id, conversation_id, state))
        return True


def _long_history(count: int = 12) -> list[dict[str, str]]:
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"{SECRET} {index} " + "나" * 8_000,
        }
        for index in range(count)
    ]


def test_plan_accounts_for_every_turn_the_request_does_not_carry() -> None:
    history = _long_history()
    plan = narrator_message_plan(
        "Continue.",
        {"view_context": {"headline": "Dashboard"}, "history": history},
        model="gpt-5-mini",
    )

    state = plan.dialogue_state
    assert plan.receipt.omitted_history_items > 0
    assert state.source_turn_count == len(history)
    assert len(state.kept_turn_ids) == plan.receipt.included_history_items
    assert len(state.compacted_turn_ids) == len(history) - plan.receipt.included_history_items
    assert state.kept_turn_ids[-1] == f"history:{len(history) - 1}"
    assert state.tier == "T0" and state.fallback_reason == "t1_unconfigured"
    assert state.execution_authority is False
    assert len(plan.messages) == 2 + plan.receipt.included_history_items + 1


def test_short_history_compacts_nothing() -> None:
    plan = narrator_message_plan(
        "Continue.",
        {"history": [{"role": "user", "content": "hello"}]},
        model="gpt-5-mini",
    )

    assert plan.dialogue_state.compacted_turn_ids == ()
    assert plan.dialogue_state.fallback_reason is None


def test_receipt_is_content_free() -> None:
    state = shadow_dialogue_state([("user", SECRET), ("assistant", SECRET), ("user", "x")], kept=1)

    receipt = dialogue_shadow_receipt(state)

    assert receipt["compacted_turns"] == 2 and receipt["kept_turns"] == 1
    assert receipt["mode"] == "shadow"
    assert "SECRET" not in repr(receipt)


@pytest.mark.parametrize("conversation_id", [None, "", "   ", 7, "x" * 300])
async def test_retention_skips_unusable_conversation_ids(conversation_id: object) -> None:
    writer = _Writer()
    state = shadow_dialogue_state([("user", "a"), ("assistant", "b")], kept=1)

    await retain_dialogue_shadow(
        writer, principal_id="p", conversation_id=conversation_id, state=state, clock=lambda: NOW
    )

    assert writer.calls == []


async def test_retention_writes_only_compacted_state_and_swallows_store_errors() -> None:
    writer = _Writer()
    compacted = shadow_dialogue_state([("user", "a"), ("assistant", "b")], kept=1)
    nothing = shadow_dialogue_state([("user", "a")], kept=1)

    await retain_dialogue_shadow(
        writer, principal_id="p", conversation_id=" c1 ", state=compacted, clock=lambda: NOW
    )
    await retain_dialogue_shadow(
        writer, principal_id="p", conversation_id="c1", state=nothing, clock=lambda: NOW
    )
    await retain_dialogue_shadow(
        None, principal_id="p", conversation_id="c1", state=compacted, clock=lambda: NOW
    )
    failing = _Writer(DialogueSnapshotStoreError("down"))
    await retain_dialogue_shadow(
        failing, principal_id="p", conversation_id="c1", state=compacted, clock=lambda: NOW
    )

    assert [(p, c) for p, c, _ in writer.calls] == [("p", "c1")]


async def test_narrator_turn_retains_a_snapshot_and_reports_only_counts(tmp_path: Path) -> None:
    writer = _Writer()
    fallback = FallbackAdapters()
    client = RecordingHttpClient()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=client,
    )
    adapter.dialogue_snapshots = writer
    source = await adapter.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Owner"})),
            body={
                "prompt": "Continue.",
                "conversation_id": "conv-1",
                "history": _long_history(),
            },
        )
    )
    events = [event async for event in source]

    receipt = events[1].data["context_selection"]
    assert isinstance(receipt, dict)
    shadow = receipt["dialogue_state_shadow"]
    assert isinstance(shadow, dict)
    assert shadow["mode"] == "shadow" and shadow["compacted_turns"] > 0
    assert "SECRET" not in repr(shadow)
    assert len(writer.calls) == 1
    principal, conversation, state = writer.calls[0]
    assert (principal, conversation) == ("operator-1", "conv-1")
    assert len(state.compacted_turn_ids) == shadow["compacted_turns"]
    sent = client.calls[0][1]["json"]["messages"]  # type: ignore[index]
    assert len(sent) == 2 + len(state.kept_turn_ids) + 1


async def _token() -> str:
    return "test-token"

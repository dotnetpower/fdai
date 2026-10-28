"""T1 dialogue-state proposer: verbatim quotes, strict flag, background retention."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fdai_operator_service.adapters.local_narrator import LocalAzureNarratorAdapters
from fdai_operator_service.adapters.narrator_dialogue_proposer import (
    DIALOGUE_T1_ENV,
    MAX_PROPOSER_PROMPT_CHARS,
    NarratorDialogueProposer,
    dialogue_t1_enabled,
)
from fdai_operator_service.adapters.narrator_dialogue_shadow import (
    DialogueStateRetention,
    history_dialogue_turns,
    shadow_dialogue_state,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationStreamRequest,
    PrincipalScope,
)
from fdai_service_contracts.dialogue_state import DialogueState, DialogueTurn

from .test_local_narrator import FallbackAdapters, RecordingHttpClient, _artifact

HISTORY = [
    ("user", "prod-eastus 구독의 고혈압 서비스 지연을 확인해줘"),
    ("assistant", "최근 1시간 기준으로 확인합니다"),
    ("user", "다른 질문입니다"),
    ("assistant", "네"),
]


def _turns() -> tuple[DialogueTurn, ...]:
    return history_dialogue_turns(HISTORY)


class _Writer:
    def __init__(self) -> None:
        self.states: list[DialogueState] = []

    async def append(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        state: DialogueState,
        recorded_at: datetime,
    ) -> bool:
        self.states.append(state)
        return True


def _completion(answer: str | None) -> Any:
    async def complete(messages: list[dict[str, Any]]) -> str | None:
        assert messages[0]["role"] == "system"
        return answer

    return complete


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", False), ("false", False), ("0", False), ("true", True), (" ON ", True), ("1", True)],
)
def test_flag_is_strict(raw: str, expected: bool) -> None:
    assert dialogue_t1_enabled({DIALOGUE_T1_ENV: raw}) is expected
    assert dialogue_t1_enabled({}) is False


def test_unrecognized_flag_fails_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="boolean"):
        dialogue_t1_enabled({DIALOGUE_T1_ENV: "maybe"})


async def test_verbatim_quote_becomes_a_verified_span() -> None:
    payload = json.dumps(
        {"anchors": [{"kind": "scope", "value": "prod-eastus", "turn_id": "history:0"}]}
    )

    proposal = await NarratorDialogueProposer(_completion(payload)).propose(_turns())

    assert proposal is not None
    anchor = proposal.anchors[0]
    assert (anchor.turn_id, anchor.start, anchor.end) == ("history:0", 0, 11)
    assert HISTORY[0][1][anchor.start : anchor.end] == "prod-eastus"


@pytest.mark.parametrize(
    "answer",
    [
        None,
        "not json",
        "[]",
        '{"anchors":"x"}',
        '{"anchors":[1]}',
        '{"anchors":[{"kind":"nope","value":"a","turn_id":"history:0"}]}',
        '{"anchors":[{"kind":"scope","value":"","turn_id":"history:0"}]}',
        '{"anchors":[{"kind":"scope","value":"a","turn_id":7}]}',
    ],
)
async def test_malformed_output_abstains(answer: str | None) -> None:
    assert await NarratorDialogueProposer(_completion(answer)).propose(_turns()) is None


async def test_oversized_range_abstains_instead_of_truncating() -> None:
    big = history_dialogue_turns([("user", "x" * (MAX_PROPOSER_PROMPT_CHARS + 1))])

    async def never(_messages: list[dict[str, Any]]) -> str | None:
        raise AssertionError("an oversized range MUST NOT reach the model")

    assert await NarratorDialogueProposer(never).propose(big) is None


async def test_retention_keeps_a_verified_t1_state_off_the_answer_path() -> None:
    writer = _Writer()
    payload = json.dumps(
        {"anchors": [{"kind": "scope", "value": "prod-eastus", "turn_id": "history:0"}]}
    )
    retention = DialogueStateRetention(writer, NarratorDialogueProposer(_completion(payload)))
    state = shadow_dialogue_state(HISTORY, kept=2)

    scheduled = await retention.retain(
        principal_id="p", conversation_id="c", state=state, turns=_turns()
    )
    assert scheduled is True and writer.states == []
    await asyncio.gather(*retention._tasks)

    assert [s.tier for s in writer.states] == ["T1"]
    assert writer.states[0].anchors[0].value == "prod-eastus"


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (None, "t1_abstained"),
        (
            json.dumps(
                {"anchors": [{"kind": "scope", "value": "paraphrase", "turn_id": "history:0"}]}
            ),
            "t1_rejected_unverified_anchor",
        ),
    ],
)
async def test_unverified_or_absent_proposal_keeps_the_t0_state_with_a_typed_reason(
    answer: str | None, reason: str
) -> None:
    writer = _Writer()
    retention = DialogueStateRetention(writer, NarratorDialogueProposer(_completion(answer)))

    await retention.retain(
        principal_id="p",
        conversation_id="c",
        state=shadow_dialogue_state(HISTORY, kept=2),
        turns=_turns(),
    )
    await asyncio.gather(*retention._tasks)

    assert [(s.tier, s.fallback_reason) for s in writer.states] == [("T0", reason)]


async def test_failing_proposer_never_raises_into_the_turn() -> None:
    writer = _Writer()

    async def boom(_messages: list[dict[str, Any]]) -> str | None:
        raise RuntimeError("provider down")

    retention = DialogueStateRetention(writer, NarratorDialogueProposer(boom))
    await retention.retain(
        principal_id="p",
        conversation_id="c",
        state=shadow_dialogue_state(HISTORY, kept=2),
        turns=_turns(),
    )
    await asyncio.gather(*retention._tasks)

    assert [s.fallback_reason for s in writer.states] == ["t1_failed"]


async def test_without_a_proposer_or_compaction_no_task_is_scheduled() -> None:
    writer = _Writer()
    state = shadow_dialogue_state(HISTORY, kept=2)
    none_compacted = shadow_dialogue_state(HISTORY, kept=10)

    sync = DialogueStateRetention(writer)
    assert (
        await sync.retain(principal_id="p", conversation_id="c", state=state, turns=_turns())
        is False
    )
    assert len(writer.states) == 1
    with_proposer = DialogueStateRetention(writer, NarratorDialogueProposer(_completion(None)))
    assert (
        await with_proposer.retain(
            principal_id="p", conversation_id="c", state=none_compacted, turns=_turns()
        )
        is False
    )
    assert DialogueStateRetention(None).writer is None
    await with_proposer.aclose()


async def test_aclose_cancels_in_flight_proposals() -> None:
    started = asyncio.Event()

    async def hang(_messages: list[dict[str, Any]]) -> str | None:
        started.set()
        await asyncio.sleep(60)
        return None

    writer = _Writer()
    retention = DialogueStateRetention(writer, NarratorDialogueProposer(hang))
    await retention.retain(
        principal_id="p",
        conversation_id="c",
        state=shadow_dialogue_state(HISTORY, kept=2),
        turns=_turns(),
    )
    await started.wait()
    await retention.aclose()

    assert writer.states == [] and not retention._tasks


async def test_narrator_with_t1_enabled_schedules_and_reports_it(tmp_path: Path) -> None:
    writer = _Writer()
    fallback = FallbackAdapters()
    client = RecordingHttpClient()

    async def token(_audience: str) -> str:
        return "test-token"

    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=token,
        http_client=client,
        dialogue_snapshots=writer,
        dialogue_t1=True,
    )
    history = [{"role": r, "content": f"{c} " + "나" * 8_000} for r, c in HISTORY * 3]
    source = await adapter.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Owner"})),
            body={"prompt": "Continue.", "conversation_id": "c1", "history": history},
        )
    )
    events = [event async for event in source]
    shadow = events[1].data["context_selection"]["dialogue_state_shadow"]  # type: ignore[index]
    await asyncio.gather(*adapter._retention._tasks)

    assert shadow["t1_scheduled"] is True  # type: ignore[index]
    assert len(writer.states) == 1
    assert writer.states[0].fallback_reason in {"t1_abstained", "t1_rejected_unverified_anchor"}

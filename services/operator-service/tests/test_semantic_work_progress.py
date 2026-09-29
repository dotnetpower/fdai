"""Work progress presentation: the pin frame, trajectory fields, and the Console envelope."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fdai_operator_service.families.conversation.contracts import (
    ConversationStreamRequest,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_progress_relay import (
    MAX_PROGRESS_UPDATES_PER_REQUEST,
    SemanticProgressRelay,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data,
)
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnBridge,
    SemanticTurnProjectionConsumer,
    _SemanticEventIterator,
)
from fdai_operator_service.postgres_semantic_turn_store import (
    StoredSemanticResult,
    StoredSemanticTurn,
)
from fdai_service_contracts import (
    OperatorRole,
    SemanticConversationModelTier,
    SemanticTurnPrincipal,
    SemanticTurnRequest,
)
from fdai_service_contracts.semantic_work_progress import conversation_model_tier_receipt
from pydantic import ValidationError

from .test_semantic_query_progress_relay import _progress
from .test_semantic_turn_bridge import _committed, _MemorySemanticStore, _projection, _proposal

GOLDEN = Path(__file__).parent / "fixtures" / "semantic_work_progress_trajectory.json"
_RECORDED = datetime(2026, 9, 28, 10, 41, 6, 296_000, tzinfo=UTC)
_PIN = {"schema_version": 1, "density": "procedural", "waves": 2, "planned_reads": 3}
_BUDGET = {
    "schema_version": 1,
    "model_calls": {"used": 3, "reserved": 0, "maximum": 5},
    "tokens": {"used": 4382, "reserved": 0, "maximum": 48000},
    "elapsed_ms": {"used": 3136, "reserved": 0, "maximum": 60000},
    "as_of": "2026-09-28T10:41:06.296+00:00",
    "complete": True,
}


def _receipt(tier: str = "t2") -> dict[str, object]:
    return conversation_model_tier_receipt(
        SemanticConversationModelTier(tier),
        observed_at=_RECORDED - timedelta(seconds=8),
    ).model_dump(mode="json")


def _pin_record(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "record_kind": "work_progress_shape",
        "request_id": "request-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "progress_sequence": 1,
        "work_progress_shape": {**_PIN},
        "execution_authority": False,
    }
    value.update(updates)
    return value


def _three_read_projection(*, locale_payload: dict[str, object] | None = None) -> dict[str, Any]:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: _RECORDED).build(_proposal())
    projection = _projection(envelope, disposition="answered", answered_evidence=True)
    semantic = cast(dict[str, Any], projection["semantic_result"])
    receipt = cast(list[dict[str, Any]], semantic["intent_graph_evidence"]["goals"])[0]
    goal = cast(list[dict[str, Any]], semantic["intent_graph"]["goals"])[0]
    semantic["intent_graph"]["goals"] = [
        {**goal, "goal_id": "goal-1", "depends_on": []},
        {**goal, "goal_id": "goal-2", "depends_on": []},
        {**goal, "goal_id": "goal-3", "depends_on": ["goal-1", "goal-2"]},
    ]
    semantic["intent_graph_evidence"]["goals"] = [
        {**receipt, "task_id": "query:resources", "goal_id": "goal-1"},
        {**receipt, "task_id": "query:health", "goal_id": "goal-2"},
        {
            **receipt,
            "task_id": "query:compare",
            "goal_id": "goal-3",
            "depends_on": ["goal-1", "goal-2"],
        },
    ]
    projection["payload"] = {
        "work_progress_shape": {**_PIN},
        "turn_budget": {**_BUDGET},
        "context_receipts": [_receipt()],
        **(locale_payload or {}),
    }
    return projection


def _trajectory(projection: dict[str, Any], *, locale: str = "en") -> dict[str, Any] | None:
    done = semantic_done_event_data(projection, locale=locale)
    return cast(dict[str, Any] | None, done.get("trajectory_detail"))


def test_golden_trajectory_detail_carries_the_three_work_progress_fields() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert _trajectory(_three_read_projection()) == golden["trajectory_detail"]
    detail = golden["trajectory_detail"]
    assert detail["work_progress_shape"] == _PIN
    assert detail["turn_budget"] == _BUDGET
    assert detail["context_receipts"][0]["label"] == "Conversation model: T2"
    assert len(detail["context_receipts"][0]["digest"]) == 64


def test_receipt_labels_follow_the_request_locale() -> None:
    detail = _trajectory(_three_read_projection(), locale="ko")

    assert detail is not None
    assert detail["context_receipts"][0]["label"] == "대화 모델: T2"
    assert detail["context_receipts"][0]["kind"] == "operator_preference"


@pytest.mark.parametrize(
    ("field", "value", "kept"),
    [
        ("work_progress_shape", {**_PIN, "waves": 3}, ("turn_budget", "context_receipts")),
        (
            "turn_budget",
            {**_BUDGET, "elapsed_ms": {"used": 61000, "reserved": 0, "maximum": 60000}},
            ("work_progress_shape", "context_receipts"),
        ),
        (
            "context_receipts",
            [{**_receipt(), "digest": "0" * 64}],
            ("work_progress_shape", "turn_budget"),
        ),
    ],
)
def test_a_malformed_field_is_dropped_alone(
    field: str, value: object, kept: tuple[str, ...]
) -> None:
    projection = _three_read_projection()
    projection["payload"][field] = value

    detail = _trajectory(projection)

    assert detail is not None
    assert field not in detail
    assert all(name in detail for name in kept)
    assert len(detail["activities"]) == 3


def test_budget_or_receipts_alone_never_create_a_trajectory() -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: _RECORDED).build(_proposal())
    projection = _projection(envelope, disposition="held")
    projection["payload"] = {"turn_budget": {**_BUDGET}, "context_receipts": [_receipt()]}

    assert _trajectory(projection) is None


def test_a_pinned_turn_without_reads_replays_an_empty_base_detail() -> None:
    envelope = SemanticTurnEnvelopeBuilder(clock=lambda: _RECORDED).build(_proposal())
    projection = _projection(envelope, disposition="held")
    projection["payload"] = {"work_progress_shape": {**_PIN}}

    detail = _trajectory(projection)

    assert detail is not None
    assert detail["activities"] == []
    assert detail["omitted"] == {"activities": 0, "branches": 0, "milestones": 0}
    assert detail["work_progress_shape"] == _PIN


def test_detail_stays_inside_the_console_envelope() -> None:
    projection = _three_read_projection()
    semantic = projection["semantic_result"]
    goal = semantic["intent_graph"]["goals"][0]
    receipt = semantic["intent_graph_evidence"]["goals"][0]
    semantic["intent_graph"]["goals"] = [
        {**goal, "goal_id": f"goal-{index}", "depends_on": []} for index in range(9)
    ]
    semantic["intent_graph_evidence"]["goals"] = [
        {**receipt, "task_id": f"query:node-{index}", "goal_id": f"goal-{index}", "depends_on": []}
        for index in range(9)
    ]
    projection["payload"]["work_progress_shape"] = {
        "schema_version": 1,
        "density": "procedural",
        "waves": 1,
        "planned_reads": 9,
    }

    detail = _trajectory(projection)

    assert detail is not None
    assert len(detail["activities"]) == 8
    assert detail["omitted"]["activities"] == 1
    assert detail["work_progress_shape"]["planned_reads"] == 9
    assert len(json.dumps(detail, ensure_ascii=False, separators=(",", ":")).encode()) <= 64 * 1024


def test_relay_keeps_the_pin_out_of_the_bounded_node_timeline() -> None:
    relay = SemanticProgressRelay()

    assert relay.consume(_pin_record()) is True
    assert relay.consume(_pin_record()) is False
    for sequence in range(2, MAX_PROGRESS_UPDATES_PER_REQUEST + 3):
        relay.consume(_progress(sequence=sequence, status="running"))

    pin = relay.pin("request-1")
    assert pin is not None
    assert pin.work_progress_shape.planned_reads == 3
    with pytest.raises(ValidationError):
        relay.consume(_pin_record(request_id="request-2", execution_authority=True))
    relay.discard("request-1")
    assert relay.pin("request-1") is None


async def test_live_pin_frame_precedes_the_first_query_activity() -> None:
    class EmptyStore:
        async def replay_semantic_turn(self, **kwargs: object) -> tuple[()]:
            del kwargs
            return ()

    request = SemanticTurnRequest(
        utterance="Show the current state.",
        principal=SemanticTurnPrincipal(subject_id="operator-1", roles=(OperatorRole.READER,)),
        session_id="session-1",
        turn_id="turn-1",
        turn_sequence=1,
        locale="en",
        purpose="operations-review",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    stored = StoredSemanticTurn(
        key="semantic-turn:request-1",
        proposal_id="proposal-1",
        request_id="request-1",
        principal_id="operator-1",
        envelope={"semantic_turn": request.model_dump(mode="json")},
        duplicate=False,
    )
    relay = SemanticProgressRelay()
    relay.consume(_pin_record())
    relay.consume(_progress(sequence=2, status="running"))
    store = EmptyStore()
    iterator = _SemanticEventIterator(
        store=cast(Any, store),
        consumer=SemanticTurnProjectionConsumer(cast(Any, store)),
        progress_relay=relay,
        stored=stored,
        principal_id="operator-1",
        cursor=None,
        retry_seconds=0.01,
    )

    events = [await anext(iterator) for _ in range(4)]
    await iterator.aclose()

    assert [event.event for event in events] == ["status", "status", "work_progress", "activity"]
    assert events[2].data["work_progress_shape"] == _PIN
    assert events[2].event_id == "0:planning"
    assert events[2].data["seq"] < events[3].data["seq"]


async def test_live_pin_wakes_a_waiting_stream() -> None:
    relay = SemanticProgressRelay()
    waiting = asyncio.create_task(
        relay.wait_for_update("request-1", 0, timeout=1.0, pin_pending=True)
    )
    await asyncio.sleep(0)

    relay.consume(_pin_record())

    await asyncio.wait_for(waiting, timeout=0.1)


async def _replayed_events(after_event_id: str | None = None) -> list[Any]:
    store = _MemorySemanticStore()
    bridge = SemanticTurnBridge(
        store=store,
        publisher=cast(Any, object()),
        result_source=cast(Any, object()),
        builder=SemanticTurnEnvelopeBuilder(clock=lambda: datetime.now(UTC)),
    )
    receipt = await bridge.append(_proposal())
    envelope = store.turns[receipt.proposal_id].envelope
    projection = _projection(envelope, disposition="answered", answered_evidence=True)
    projection["payload"] = {
        "work_progress_shape": {
            "schema_version": 1,
            "density": "compact",
            "waves": 1,
            "planned_reads": 1,
        }
    }
    await SemanticTurnProjectionConsumer(store).consume(_committed(projection))
    stream = await bridge.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            proposal_id=receipt.proposal_id,
            after_event_id=after_event_id,
        )
    )
    return [event async for event in stream]


async def test_replay_pins_density_before_the_terminal_goal_activities() -> None:
    events = await _replayed_events()

    names = [event.event for event in events]
    first_activity = names.index("activity")
    assert names.count("work_progress") == 1
    assert names.index("work_progress") < first_activity
    pin = events[names.index("work_progress")]
    assert pin.event_id.endswith(":planning")
    assert pin.data["work_progress_shape"]["density"] == "compact"
    assert (
        events[-1].data["trajectory_detail"]["work_progress_shape"]
        == pin.data["work_progress_shape"]
    )


async def test_replay_after_the_pin_does_not_repeat_it() -> None:
    first = await _replayed_events()
    pin = next(event for event in first if event.event == "work_progress")

    resumed = await _replayed_events(after_event_id=pin.event_id)

    assert "work_progress" not in [event.event for event in resumed]
    assert resumed[-1].event == "done"


async def test_a_live_pin_is_not_repeated_when_the_terminal_arrives() -> None:
    events = await _late_terminal_events(pin_first=True)

    names = [event.event for event in events]
    assert names.count("work_progress") == 1
    assert names.index("work_progress") < names.index("activity")
    assert names[-1] == "done"
    assert events[-1].data["trajectory_detail"]["work_progress_shape"] == _PIN


async def test_a_pin_is_never_sent_after_the_first_query_activity() -> None:
    events = await _late_terminal_events(pin_first=False)

    names = [event.event for event in events]
    assert "work_progress" not in names
    assert names[2] == "activity"
    assert names[-1] == "done"


async def _late_terminal_events(*, pin_first: bool) -> list[Any]:
    projection = _three_read_projection()

    class LateStore:
        def __init__(self) -> None:
            self.reads = 0

        async def replay_semantic_turn(self, **kwargs: object) -> tuple[StoredSemanticResult, ...]:
            del kwargs
            self.reads += 1
            if self.reads <= 2:
                return ()
            return (
                StoredSemanticResult(
                    sequence=1,
                    event="done",
                    request_id="request-1",
                    principal_id="operator-1",
                    projection_id=cast(str, projection["projection_id"]),
                    data=projection,
                    duplicate=False,
                ),
            )

    request = SemanticTurnRequest(
        utterance="Show the current state.",
        principal=SemanticTurnPrincipal(subject_id="operator-1", roles=(OperatorRole.READER,)),
        session_id="session-1",
        turn_id="turn-1",
        turn_sequence=1,
        locale="en",
        purpose="operations-review",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    relay = SemanticProgressRelay()
    if pin_first:
        relay.consume(_pin_record())
    relay.consume(_progress(sequence=2, status="running"))
    store = LateStore()
    iterator = _SemanticEventIterator(
        store=cast(Any, store),
        consumer=SemanticTurnProjectionConsumer(cast(Any, store)),
        progress_relay=relay,
        stored=StoredSemanticTurn(
            key="semantic-turn:request-1",
            proposal_id="proposal-1",
            request_id="request-1",
            principal_id="operator-1",
            envelope={"semantic_turn": request.model_dump(mode="json")},
            duplicate=False,
        ),
        principal_id="operator-1",
        cursor=None,
        retry_seconds=0.01,
    )

    events = [await anext(iterator) for _ in range(3)]
    if not pin_first:
        relay.consume(_pin_record())
    events.extend([event async for event in iterator])
    return events

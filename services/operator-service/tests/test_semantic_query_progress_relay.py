"""Best-effort semantic query progress relay tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnProjectionConsumer,
    _progress_query_activity,
    _SemanticEventIterator,
    _SemanticProgressRelay,
)
from fdai_operator_service.postgres_semantic_turn_store import StoredSemanticTurn
from fdai_service_contracts import OperatorRole, SemanticTurnPrincipal, SemanticTurnRequest


def _progress(*, sequence: int, status: str, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "request_id": "request-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "progress_sequence": sequence,
        "node_id": "current-state-target",
        "node_kind": "object_set",
        "capability": "query.object_set",
        "arguments": {"object_type": "Resource"},
        "status": status,
        "step_index": 1,
        "step_total": 2,
        "depends_on": [],
        "started_at": "2026-08-26T11:00:00Z",
        "execution_authority": False,
    }
    value.update(updates)
    return value


def test_progress_relay_keeps_monotonic_actual_query_activity() -> None:
    relay = _SemanticProgressRelay()

    assert relay.consume(_progress(sequence=1, status="running")) is True
    assert relay.consume(_progress(sequence=1, status="running")) is False
    assert (
        relay.consume(
            _progress(
                sequence=2,
                status="completed",
                completed_at="2026-08-26T11:00:01Z",
                duration_ms=1000,
                evidence_refs=["ontology-object-set:current-state-target:1"],
            )
        )
        is True
    )

    updates = relay.after("request-1", 0)
    assert [str(item.status) for item in updates] == ["running", "completed"]
    activity = _progress_query_activity(updates[0], locale="ko")
    assert activity["activity_id"] == "semantic:goal:current-state-target"
    assert activity["status"] == "running"
    assert activity["completed"] == 0
    assert activity["total"] == 2
    assert activity["execution"]["command"] == (
        '{"arguments":{"object_type":"Resource"},"capability":"query.object_set"}'
    )

    relay.discard("request-1")
    assert relay.after("request-1", 0) == ()


async def test_progress_relay_wakes_active_stream_without_poll_delay() -> None:
    relay = _SemanticProgressRelay()
    waiting = asyncio.create_task(relay.wait_for_update("request-1", 0, timeout=1.0))
    await asyncio.sleep(0)

    relay.consume(_progress(sequence=1, status="running"))

    await asyncio.wait_for(waiting, timeout=0.1)
    assert len(relay.after("request-1", 0)) == 1


async def test_semantic_iterator_streams_query_progress_before_terminal() -> None:
    class EmptyStore:
        async def replay_semantic_turn(self, **kwargs: object) -> tuple[()]:
            del kwargs
            return ()

    request = SemanticTurnRequest(
        utterance="현재 상태를 확인해줘",
        principal=SemanticTurnPrincipal(
            subject_id="operator-1",
            roles=(OperatorRole.READER,),
        ),
        session_id="session-1",
        turn_id="turn-1",
        turn_sequence=1,
        locale="ko",
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
    relay = _SemanticProgressRelay()
    relay.consume(
        _progress(
            sequence=1,
            status="running",
            session_id="another-session",
        )
    )
    relay.consume(_progress(sequence=2, status="running"))
    relay.consume(
        _progress(
            sequence=3,
            status="completed",
            completed_at="2026-08-26T11:00:01Z",
            duration_ms=1000,
        )
    )
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

    assert (await anext(iterator)).event == "status"
    assert (await anext(iterator)).event == "status"
    progress_event = await anext(iterator)

    assert progress_event.event == "activity"
    assert progress_event.data["kind"] == "ontology_query"
    assert progress_event.data["status"] == "running"
    assert progress_event.data["activity_id"] == "semantic:goal:current-state-target"
    completed_event = await anext(iterator)
    assert completed_event.event == "activity"
    assert completed_event.data["status"] == "completed"
    await iterator.aclose()

"""Focused owner-scoped replay checks for interactive investigations."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.families.operations.contracts import ReplayQuery
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayStore,
)


async def test_replay_merges_progress_and_terminal_with_owner_predicate() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        calls.append((statement, parameters))
        return [
            {
                "sequence": 2,
                "event": "resource.resolved",
                "data": {"task_id": "background-one", "kind": "resource.resolved"},
            },
            {
                "sequence": 1007,
                "event": "investigation.completed",
                "data": {"completion_id": "completion-one"},
            },
        ]

    replay = await PostgresReadInvestigationReplayStore(fetch_all=fetch_all).replay(
        ReplayQuery(
            stream="read-investigation:request-one",
            principal_id="principal-one",
            after_sequence=1,
            limit=100,
        )
    )

    assert [event.sequence for event in replay.events] == [2, 1007]
    assert replay.watermark == 1007
    statement, parameters = calls[0]
    assert "owner_principal_id = %(principal_id)s" in statement
    assert "progress.owner_principal_id = %(principal_id)s" in statement
    assert "request ->> 'conversation_ref' = %(request_id)s" in statement
    assert "1000 + completion.sequence" in statement
    assert parameters == {
        "principal_id": "principal-one",
        "request_id": "request-one",
        "stream": "read-investigation:request-one",
        "after_sequence": 1,
        "limit": 100,
    }


async def test_empty_replay_preserves_last_event_watermark() -> None:
    async def fetch_all(
        _statement: str,
        _parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return []

    replay = await PostgresReadInvestigationReplayStore(fetch_all=fetch_all).replay(
        ReplayQuery(
            stream="read-investigation:request-one",
            principal_id="principal-one",
            after_sequence=17,
            limit=100,
        )
    )

    assert replay.events == ()
    assert replay.watermark == 17

"""Focused owner-scoped replay checks for interactive investigations."""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
import pytest
from fdai_operator_service.families.operations.contracts import ReplayQuery
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayConfig,
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


class _Cursor:
    async def fetchall(self) -> list[dict[str, object]]:
        return []


class _Connection:
    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def execute(
        self,
        statement: str,
        parameters: object,
    ) -> object:
        del parameters
        return object() if "set_config" in statement else _Cursor()


async def test_configured_replay_normalizes_sqlalchemy_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    async def connect(dsn: str, **kwargs: object) -> _Connection:
        observed.append(dsn)
        assert kwargs["connect_timeout"] == 10
        return _Connection()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresReadInvestigationReplayStore(
        config=PostgresReadInvestigationReplayConfig(
            dsn="postgresql+psycopg://user@example.invalid/fdai"
        )
    )

    await store.replay(
        ReplayQuery(
            stream="read-investigation:request-one",
            principal_id="principal-one",
            after_sequence=None,
            limit=100,
        )
    )

    assert observed == ["postgresql://user@example.invalid/fdai"]

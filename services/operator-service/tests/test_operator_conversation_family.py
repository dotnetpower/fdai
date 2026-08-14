"""Contract tests for the independently packaged Operator conversation family."""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fdai_operator_service.families.conversation import (
    CONVERSATION_ROUTE_MANIFEST,
    ConversationFamilyDependencies,
    ConversationProjectionReader,
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    JsonObject,
    OutboxReceipt,
    PrincipalScope,
    StreamEvent,
    build_conversation_routes,
)
from fdai_operator_service.family_adapters import PostgresConversationAdapters
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[3]


class _Authorizer:
    async def authorize(self, request: Request, *, operation: str) -> PrincipalScope:
        assert operation
        return PrincipalScope(
            subject_id=request.headers.get("x-principal", "principal-a"),
            roles=frozenset({"Contributor"}),
        )


class _Reader:
    def __init__(self) -> None:
        self.queries: list[ConversationQuery] = []

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        self.queries.append(query)
        bodies: dict[str, JsonObject] = {
            "chat.health": {
                "available": True,
                "mode": "test",
                "endpoint": "private.example.invalid",
            },
            "busy.inspect": {
                "session_id": "session-one",
                "mode": "queue",
                "active": False,
                "revision": 1,
                "pending": [],
            },
            "workers.list": {"workers": []},
            "user.context": {
                "preference": None,
                "memories": [],
                "policies": [],
                "subscriptions": [],
                "briefing_runs": [],
                "scheduled_continuations": [],
                "conversations": [],
                "conversation_page": {"has_more": False, "next_cursor": None},
            },
            "assurance.list": {
                "source": "conversation-assurance-ledger",
                "read_only": True,
                "disputes_available": True,
                "policy_mutations_available": False,
                "summary": {"total": 0, "fail": 0},
                "assessments": [],
                "disputes": [],
            },
        }
        return ConversationResponse(body=bodies.get(query.operation, {"items": []}))


class _SearchStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.context_rows: list[dict[str, Any]] = []
        self.lineage_row: dict[str, Any] | None = None

    async def search_conversation_turns(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("search", dict(kwargs)))
        return [
            {
                "turn_id": "turn-one",
                "conversation_id": "conversation-one",
                "turn_index": 1,
                "role": "assistant",
                "content": "Database latency changed after deployment.",
                "recorded_at": datetime(2026, 8, 14, 7, 0, tzinfo=UTC),
                "metadata": {
                    "incident_id": "incident-one",
                    "correlation_id": "correlation-one",
                    "evidence_refs": ["audit:one"],
                },
                "channel_id": "web",
            }
        ]

    async def measure_conversation_turns(self, **kwargs: Any) -> dict[str, int]:
        self.calls.append(("measure", dict(kwargs)))
        return {"index_rows": 7, "index_bytes": 321}

    async def read_conversation_search_context(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("context", dict(kwargs)))
        return list(self.context_rows)

    async def read_conversation_lineage(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(("lineage", dict(kwargs)))
        return self.lineage_row


class _Outbox:
    def __init__(self) -> None:
        self.proposals: list[ConversationProposal] = []

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        duplicate = any(item.idempotency_key == proposal.idempotency_key for item in self.proposals)
        self.proposals.append(proposal)
        if proposal.operation == "busy.submit":
            response = ConversationResponse(
                body={
                    "disposition": "queued",
                    "session_id": str(proposal.body["session_id"]),
                    "input_id": str(proposal.body["input_id"]),
                    "sequence": 0,
                    "reason": None,
                    "duplicate": duplicate,
                },
                status_code=202,
            )
        elif proposal.operation == "user.preferences.put":
            response = ConversationResponse(
                body={
                    "principal_id": proposal.scope.subject_id,
                    "locale": str(proposal.body.get("locale", "en")),
                }
            )
        elif proposal.operation == "background.create":
            response = ConversationResponse(
                body={"task_id": "task-one", "status": "queued"}, status_code=202
            )
        elif proposal.operation == "assurance.dispute":
            response = ConversationResponse(
                body={"dispute": {"reason": proposal.body["reason"]}, "duplicate": duplicate},
                status_code=200 if duplicate else 201,
            )
        else:
            response = ConversationResponse(body={"accepted": True})
        return OutboxReceipt(
            proposal_id=f"proposal-{len(self.proposals)}",
            duplicate=duplicate,
            response=response,
        )


class _EventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> _EventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _Streams:
    def __init__(self) -> None:
        self.requests: list[ConversationStreamRequest] = []
        self.last_iterator: _EventIterator | None = None

    async def open(self, request: ConversationStreamRequest) -> _EventIterator:
        self.requests.append(request)
        self.last_iterator = _EventIterator(
            (
                StreamEvent(
                    event="progress",
                    event_id="5",
                    data={"sequence": 5, "kind": "investigation.started", "token": "secret"},
                ),
                StreamEvent(
                    event="terminal",
                    event_id="6",
                    data={"task_id": "task-one", "status": "succeeded"},
                ),
            )
        )
        return self.last_iterator


def _app(
    *,
    reader: ConversationProjectionReader | None = None,
    outbox: _Outbox | None = None,
    streams: _Streams | None = None,
) -> Starlette:
    return Starlette(
        routes=list(
            build_conversation_routes(
                ConversationFamilyDependencies(
                    authorizer=_Authorizer(),
                    projections=reader,
                    outbox=outbox,
                    streams=streams,
                )
            )
        )
    )


def _search_app(store: _SearchStore) -> Starlette:
    adapter = PostgresConversationAdapters(cast(PostgresFamilyStore, store))
    return _app(reader=adapter)


async def test_representative_read_envelopes_are_scoped_and_redacted() -> None:
    reader = _Reader()
    async with AsyncClient(
        transport=ASGITransport(app=_app(reader=reader)), base_url="http://test"
    ) as client:
        health = await client.get("/chat/health")
        busy = await client.get("/chat/busy-input?session_id=session-one")
        workers = await client.get("/task-workers")
        context = await client.get("/me/context")
        assurance = await client.get("/conversation-assurance")

    assert health.json() == {
        "available": True,
        "mode": "test",
        "endpoint": "[REDACTED]",
    }
    assert busy.json()["pending"] == []
    assert workers.json() == {"workers": []}
    assert context.json()["conversation_page"] == {"has_more": False, "next_cursor": None}
    assert assurance.json()["source"] == "conversation-assurance-ledger"
    assert all(item.scope.subject_id == "principal-a" for item in reader.queries)


async def test_conversation_search_materializes_scoped_bounded_projection() -> None:
    store = _SearchStore()
    async with AsyncClient(
        transport=ASGITransport(app=_search_app(store)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/me/conversations/search",
            params=[
                ("q", "database latency"),
                ("mode", "terms"),
                ("limit", "5"),
                ("channel", "web"),
                ("role", "assistant"),
                ("conversation_id", "conversation-one"),
                ("incident_id", "incident-one"),
                ("after", "2026-08-14T06:00:00+00:00"),
                ("before", "2026-08-14T08:00:00+00:00"),
            ],
            headers={"x-principal": "principal-authenticated"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "hits": [
            {
                "result_id": "conversation-search:turn-one",
                "turn_id": "turn-one",
                "conversation_id": "conversation-one",
                "channel_id": "web",
                "role": "assistant",
                "snippet": {
                    "text": "Database latency changed after deployment.",
                    "highlights": [{"start": 0, "end": 8}, {"start": 9, "end": 16}],
                },
                "recorded_at": "2026-08-14T07:00:00+00:00",
                "rank": 1.0,
                "incident_id": "incident-one",
                "correlation_id": "correlation-one",
                "evidence_refs": ["audit:one"],
            }
        ],
        "result_cap": 5,
        "index_rows": 7,
        "index_bytes": 321,
    }
    assert "query_ms" not in payload
    search_call = store.calls[0]
    assert search_call[0] == "search"
    assert search_call[1]["principal_id"] == "principal-authenticated"
    assert search_call[1]["channels"] == ("web",)
    assert search_call[1]["roles"] == ("assistant",)


async def test_conversation_search_context_lineage_and_not_found_are_scope_bound() -> None:
    store = _SearchStore()
    target = {
        "turn_id": "turn-one",
        "conversation_id": "conversation-one",
        "turn_index": 1,
        "role": "operator",
        "content": "Investigate latency.",
        "recorded_at": datetime(2026, 8, 14, 7, 0, tzinfo=UTC),
        "metadata": {},
        "channel_id": "web",
        "section": "hit",
    }
    store.context_rows = [target]
    store.lineage_row = {
        "conversation_id": "conversation-one",
        "channel_id": "web",
        "started_at": datetime(2026, 8, 14, 6, 0, tzinfo=UTC),
        "last_active": datetime(2026, 8, 14, 7, 0, tzinfo=UTC),
        "turn_ids": ["turn-zero", "turn-one"],
    }
    async with AsyncClient(
        transport=ASGITransport(app=_search_app(store)), base_url="http://test"
    ) as client:
        context = await client.get(
            "/me/conversations/search/conversation-search:turn-one/context?before=1&after=1"
        )
        lineage = await client.get("/me/conversations/conversation-one/lineage")
        store.context_rows = []
        store.lineage_row = None
        missing_context = await client.get(
            "/me/conversations/search/conversation-search:missing/context"
        )
        missing_lineage = await client.get("/me/conversations/missing/lineage")

    assert context.status_code == lineage.status_code == 200
    assert context.json()["hit"]["turn_id"] == "turn-one"
    assert lineage.json()["turn_ids"] == ["turn-zero", "turn-one"]
    assert missing_context.status_code == missing_lineage.status_code == 404
    assert (
        missing_context.json()
        == missing_lineage.json()
        == {
            "error": {
                "code": "not_found",
                "message": "conversation search resource is unavailable",
            }
        }
    )
    assert all(call[1]["principal_id"] == "principal-a" for call in store.calls)


async def test_conversation_search_rejects_invalid_requests_before_storage() -> None:
    store = _SearchStore()
    async with AsyncClient(
        transport=ASGITransport(app=_search_app(store)), base_url="http://test"
    ) as client:
        responses = [
            await client.get("/me/conversations/search?q=%%%___"),
            await client.get("/me/conversations/search?q=valid&mode=unknown"),
            await client.get("/me/conversations/search?q=valid&limit=51"),
            await client.get("/me/conversations/search?q=valid&principal_id=other"),
            await client.get(
                "/me/conversations/search/conversation-search:turn-one/context?before=4"
            ),
        ]

    assert {response.status_code for response in responses} == {400}
    assert not store.calls


async def test_mutations_only_append_scoped_idempotent_proposals() -> None:
    outbox = _Outbox()
    async with AsyncClient(
        transport=ASGITransport(app=_app(outbox=outbox)), base_url="http://test"
    ) as client:
        payload = {
            "principal_id": "principal-b",
            "session_id": "session-one",
            "content": "check the latest evidence",
            "input_id": "input-one",
            "idempotency_key": "busy-one",
        }
        accepted = await client.post("/chat/busy-input", json=payload)
        duplicate = await client.post("/chat/busy-input", json=payload)
        preference = await client.put(
            "/me/preferences",
            json={"principal_id": "principal-b", "locale": "ko"},
        )
        cancelled = await client.post(
            "/background-tasks/task-one/cancel",
            headers={"Idempotency-Key": "cancel-one"},
        )

    assert accepted.status_code == duplicate.status_code == 202
    assert accepted.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert preference.json() == {"principal_id": "principal-a", "locale": "ko"}
    assert all(item.scope.subject_id == "principal-a" for item in outbox.proposals)
    assert all("principal_id" not in item.body for item in outbox.proposals)
    assert cancelled.status_code == 200
    assert outbox.proposals[-1].cancellation is True


async def test_confirmation_body_caps_and_unavailable_dependencies_fail_closed() -> None:
    outbox = _Outbox()
    async with AsyncClient(
        transport=ASGITransport(app=_app(outbox=outbox)), base_url="http://test"
    ) as client:
        confirmation = await client.post(
            "/me/memories", json={"body": "Remember this", "confirmed": False}
        )
        oversized = await client.post(
            "/conversation-assurance/assessment-one/disputes",
            content=b"x" * 8_001,
        )
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as unavailable_client:
        read_unavailable = await unavailable_client.get("/me/context")
        write_unavailable = await unavailable_client.put("/me/preferences", json={})
        stream_unavailable = await unavailable_client.get(
            "/background-tasks/task-one/progress/stream"
        )

    assert confirmation.status_code == 409
    assert oversized.status_code == 413
    assert not outbox.proposals
    unavailable_statuses = {
        read_unavailable.status_code,
        write_unavailable.status_code,
        stream_unavailable.status_code,
    }
    assert unavailable_statuses == {503}
    assert read_unavailable.json()["error"]["code"] == "unavailable"


async def test_sse_frames_support_replay_redaction_and_close() -> None:
    streams = _Streams()
    async with AsyncClient(
        transport=ASGITransport(app=_app(streams=streams)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/background-tasks/task-one/progress/stream",
            headers={"Last-Event-ID": "4"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 5\nevent: progress" in response.text
    assert (
        'data: {"kind":"investigation.started","sequence":5,"token":"[REDACTED]"}' in response.text
    )
    assert "secret" not in response.text
    assert streams.requests[0].after_event_id == "4"
    assert streams.requests[0].scope.subject_id == "principal-a"
    assert streams.last_iterator is not None and streams.last_iterator.closed is True


async def test_post_stream_appends_proposal_before_observation() -> None:
    outbox = _Outbox()
    streams = _Streams()
    async with AsyncClient(
        transport=ASGITransport(app=_app(outbox=outbox, streams=streams)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/chat/stream",
            json={"prompt": "Inspect bounded evidence.", "idempotency_key": "chat-stream-one"},
        )

    assert response.status_code == 200
    assert [item.operation for item in outbox.proposals] == ["chat.stream"]
    assert streams.requests[0].proposal_id == "proposal-1"
    assert streams.requests[0].idempotency_key == "chat-stream-one"


def test_manifest_is_complete_without_legacy_route_sources() -> None:
    manifest = {(item.method, item.path, item.name) for item in CONVERSATION_ROUTE_MANIFEST}

    assert len(CONVERSATION_ROUTE_MANIFEST) == 38
    assert len(manifest) == 38
    assert {
        ("GET", "/chat/health", "handler"),
        ("POST", "/chat/stream", "handler"),
        ("GET", "/conversation-assurance", "get_assurance"),
        ("GET", "/me/context", "context"),
    } <= manifest
    assert not (ROOT / "src" / "fdai" / "delivery" / "operator_api").exists()


def test_family_has_no_fdai_imports() -> None:
    family_root = ROOT / "services/operator-service/src/fdai_operator_service/families/conversation"
    imported_roots: set[str] = set()
    for source in family_root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots.add(node.module.split(".")[0])

    assert "fdai" not in imported_roots

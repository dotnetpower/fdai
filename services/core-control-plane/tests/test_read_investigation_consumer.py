"""Focused Core consumption checks for versioned read investigations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.core.background_task import (
    BackgroundTaskOrigin,
    BackgroundTaskQuotaPolicy,
    BackgroundTaskService,
    InMemoryBackgroundTaskStore,
)
from fdai.shared.providers.event_bus import EventEnvelope
from fdai_core_service.read_investigation_consumer import consume_read_investigations
from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_REQUEST_TOPIC,
    ReadInvestigationIntent,
    ReadInvestigationOrigin,
    ReadInvestigationSelector,
    build_read_investigation_cancellation,
    build_read_investigation_request,
    read_investigation_task_id,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _Coordinator:
    def __init__(self) -> None:
        self.wakes = 0
        self.cancellations: list[tuple[str, str, bool]] = []

    def wake(self) -> None:
        self.wakes += 1

    async def cancel(self, task_id: str, *, actor: str, is_admin: bool) -> None:
        self.cancellations.append((task_id, actor, is_admin))


class _Stream:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> EventEnvelope:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _Bus:
    def __init__(self, events: list[EventEnvelope]) -> None:
        self.stream = _Stream(events)
        self.dead_letters: list[tuple[str, str]] = []

    def subscribe(self, topic: str, group_id: str) -> _Stream:
        assert topic == READ_INVESTIGATION_REQUEST_TOPIC
        assert group_id == "core-read-investigation-v1"
        return self.stream

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: object,
        reason: str,
    ) -> None:
        del topic, payload
        self.dead_letters.append((key, reason))


def _payload(
    *,
    prompt: str = "Inspect",
    requested_at: datetime = NOW,
    request_id: str = "request-one",
    idempotency_key: str = "idempotency-one",
) -> dict[str, object]:
    return build_read_investigation_request(
        request_id=request_id,
        owner_principal_id="principal-one",
        idempotency_key=idempotency_key,
        correlation_id="correlation-one",
        prompt=prompt,
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ReadInvestigationSelector(name="service-one"),
        origin=ReadInvestigationOrigin(
            conversation_id="request-one",
            channel_kind="operator-api",
            channel_id="principal-one",
        ),
        requested_at=requested_at,
    ).model_dump(mode="json")


def _cancellation_payload(*, owner: str = "principal-one") -> dict[str, object]:
    return build_read_investigation_cancellation(
        request_id="cancel-one",
        owner_principal_id=owner,
        task_id="background-one",
        idempotency_key="cancel-idempotency",
        requested_at=NOW,
        admin_override=False,
    ).model_dump(mode="json")


async def test_consumer_persists_before_wake_and_deduplicates_redelivery() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    audit = _Audit()
    service = BackgroundTaskService(store=store, audit=audit, clock=lambda: NOW)
    coordinator = _Coordinator()
    envelope = EventEnvelope(
        READ_INVESTIGATION_REQUEST_TOPIC,
        read_investigation_task_id("principal-one", "idempotency-one"),
        _payload(),
        1,
    )
    bus = _Bus([envelope, envelope])

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=service,
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    attempts = await store.list(owner="principal-one")
    assert len(attempts) == 1
    assert attempts[0].task.context_digest == _payload()["request_digest"]
    assert attempts[0].task.investigation is not None
    assert attempts[0].task.investigation.intent.value == "resource_state"
    assert attempts[0].task.investigation.scope_ref == "scope:configured-reader"
    assert coordinator.wakes == 2
    assert len(audit.events) == 1
    assert bus.dead_letters == []
    assert bus.stream.closed is True


async def test_consumer_dead_letters_invalid_key_without_persistence() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    audit = _Audit()
    coordinator = _Coordinator()
    bus = _Bus(
        [
            EventEnvelope(
                READ_INVESTIGATION_REQUEST_TOPIC,
                "different-key",
                _payload(),
                1,
            )
        ]
    )

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=BackgroundTaskService(store=store, audit=audit, clock=lambda: NOW),
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    assert await store.list() == ()
    assert coordinator.wakes == 0
    assert bus.dead_letters == [("different-key", "read_investigation_request_rejected")]


async def test_consumer_dead_letters_quota_denial_and_continues() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    service = BackgroundTaskService(
        store=store,
        audit=_Audit(),
        quota_policy=BackgroundTaskQuotaPolicy(max_active_tasks=1),
        clock=lambda: NOW,
    )
    first = EventEnvelope(
        READ_INVESTIGATION_REQUEST_TOPIC,
        read_investigation_task_id("principal-one", "idempotency-one"),
        _payload(),
        1,
    )
    denied = EventEnvelope(
        READ_INVESTIGATION_REQUEST_TOPIC,
        read_investigation_task_id("principal-one", "idempotency-two"),
        _payload(request_id="request-two", idempotency_key="idempotency-two"),
        2,
    )
    bus = _Bus([first, denied])
    coordinator = _Coordinator()

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=service,
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    assert len(await store.list(owner="principal-one")) == 1
    assert coordinator.wakes == 1
    assert bus.dead_letters == [
        (
            read_investigation_task_id("principal-one", "idempotency-two"),
            "read_investigation_quota_denied",
        )
    ]


async def test_consumer_durably_cancels_before_stopping_active_execution() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    audit = _Audit()
    service = BackgroundTaskService(store=store, audit=audit, clock=lambda: NOW)
    await service.create(
        owner_principal_id="principal-one",
        origin=BackgroundTaskOrigin("conversation-one", "operator-api", "principal-one"),
        prompt="Inspect",
        context_digest="sha256:context",
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        now=NOW,
    )
    attempt = (await store.list(owner="principal-one"))[0]
    payload = build_read_investigation_cancellation(
        request_id="cancel-one",
        owner_principal_id="principal-one",
        task_id=attempt.task.task_id,
        idempotency_key="cancel-idempotency",
        requested_at=NOW,
        admin_override=False,
    ).model_dump(mode="json")
    coordinator = _Coordinator()
    bus = _Bus([EventEnvelope(READ_INVESTIGATION_REQUEST_TOPIC, attempt.task.task_id, payload, 2)])

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=service,
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    cancelled = await store.get(attempt.task.task_id)
    assert cancelled is not None
    assert cancelled.status.value == "cancelled"
    assert coordinator.cancellations == [(attempt.task.task_id, "principal-one", False)]
    assert audit.events[-1]["action_kind"] == "background-task.cancelled"
    assert bus.dead_letters == []


async def test_consumer_denies_cancellation_without_disclosing_task_state() -> None:
    coordinator = _Coordinator()
    bus = _Bus(
        [
            EventEnvelope(
                READ_INVESTIGATION_REQUEST_TOPIC,
                "background-one",
                _cancellation_payload(owner="other-principal"),
                2,
            )
        ]
    )

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=BackgroundTaskService(
            store=InMemoryBackgroundTaskStore(clock=lambda: NOW),
            audit=_Audit(),
            clock=lambda: NOW,
        ),
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    assert coordinator.cancellations == []
    assert bus.dead_letters == [("background-one", "read_investigation_cancellation_denied")]


async def test_consumer_uses_core_time_for_delayed_durable_request() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    bus = _Bus(
        [
            EventEnvelope(
                READ_INVESTIGATION_REQUEST_TOPIC,
                read_investigation_task_id("principal-one", "idempotency-one"),
                _payload(requested_at=NOW - timedelta(minutes=10)),
                1,
            )
        ]
    )

    await consume_read_investigations(
        bus=bus,  # type: ignore[arg-type]
        topic=READ_INVESTIGATION_REQUEST_TOPIC,
        group_id="core-read-investigation-v1",
        service=BackgroundTaskService(store=store, audit=_Audit(), clock=lambda: NOW),
        coordinator=_Coordinator(),
        stop=asyncio.Event(),
    )

    attempt = (await store.list(owner="principal-one"))[0]
    assert attempt.task.created_at == NOW
    assert bus.dead_letters == []

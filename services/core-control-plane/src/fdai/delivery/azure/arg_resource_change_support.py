"""Pure value helpers for the Azure Resource Graph change feed."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import Event
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_store import StateStore

_CURSOR_SEP: Final[str] = "\x1f"
_CURSOR_PREFIX: Final[str] = "arg_resource_change_cursor:"
DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS: Final[float] = 60.0
_OPERATIONAL_STATUS_CHANGE_PATHS: Final[Mapping[str, tuple[str, ...]]] = {
    "properties.powerState.code": ("properties", "powerState", "code"),
    "properties.runningStatus": ("properties", "runningStatus"),
    "properties.operationalState": ("properties", "operationalState"),
    "properties.dnsResolverState": ("properties", "dnsResolverState"),
    "properties.resourceState": ("properties", "resourceState"),
    "properties.state": ("properties", "state"),
    "properties.status": ("properties", "status"),
    "properties.userVisibleState": ("properties", "userVisibleState"),
}


class ArgResourceChangeError(RuntimeError):
    """Raised when a change-feed poll or hydration result is unusable."""


class ResourceChangeIngestionFence(Protocol):
    async def contains(self, event_ids: tuple[str, ...]) -> bool: ...


@dataclass(frozen=True, slots=True)
class ChangeRow:
    """One validated ``resourcechanges`` record."""

    change_id: str
    change_time: datetime
    change_kind: str
    arm_id: str
    arm_type: str | None
    neutral_id: str
    operational_status_change: tuple[tuple[str, ...], str] | None


@dataclass(frozen=True, slots=True)
class HydrationResult:
    """Mapped records plus every provider identity returned by hydration."""

    records: Mapping[str, ResourceRecord]
    seen_provider_refs: frozenset[str]


@dataclass(frozen=True, slots=True)
class ResourceChangeFeedResult:
    """One bounded poll result: the events to publish and the next cursor."""

    events: tuple[Event, ...]
    next_cursor: str
    complete: bool = True
    last_event_cursor: str | None = None
    recovery_cursor: str | None = None


class ResourceChangeFeed(Protocol):
    """Bounded change-feed surface required by the forwarding loop."""

    @property
    def max_hydration_retries(self) -> int: ...

    def initial_cursor(self) -> str: ...

    async def poll(self, cursor: str) -> ResourceChangeFeedResult: ...


def event_uuid(scope: str, change_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fdai.arg-resource-change://{scope}/{change_id}")


def pending_event_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or len(value) > 1_000
        or any(not isinstance(item, str) or not item or len(item) > 128 for item in value)
        or len(set(value)) != len(value)
    ):
        raise ArgResourceChangeError("resource change ingestion fence is malformed")
    return tuple(sorted(value))


def hydration_retry_count(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10:
        raise ArgResourceChangeError("resourcechanges hydration retry state is malformed")
    return value


def coverage_gap_at(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = parse_ts(value)
    if parsed is None:
        raise ArgResourceChangeError("resourcechanges coverage gap state is malformed")
    return parsed


def encode_cursor(change_time: datetime, change_id: str) -> str:
    return f"{change_time.astimezone(UTC).isoformat()}{_CURSOR_SEP}{change_id}"


def decode_cursor(cursor: str) -> tuple[datetime | None, str | None]:
    trimmed = cursor.strip()
    if not trimmed:
        return None, None
    if _CURSOR_SEP not in trimmed:
        raise ArgResourceChangeError("resourcechanges cursor is malformed")
    ts_part, _, id_part = trimmed.partition(_CURSOR_SEP)
    parsed = parse_ts(ts_part)
    if parsed is None or not id_part:
        raise ArgResourceChangeError("resourcechanges cursor is malformed")
    return parsed, id_part


def parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00") if raw.strip().endswith("Z") else raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def operational_status_change(
    changes: Mapping[str, Any],
) -> tuple[tuple[str, ...], str] | None:
    for source_path, target_path in _OPERATIONAL_STATUS_CHANGE_PATHS.items():
        raw_change = changes.get(source_path)
        if not isinstance(raw_change, Mapping):
            continue
        raw_value = raw_change.get("newValue")
        candidate = raw_value.get("code") if isinstance(raw_value, Mapping) else raw_value
        if isinstance(candidate, str) and candidate.strip():
            return target_path, candidate.strip()
    return None


def with_nested_value(
    value: Mapping[str, Any],
    path: tuple[str, ...],
    replacement: str,
) -> dict[str, Any]:
    updated = dict(value)
    cursor = updated
    for component in path[:-1]:
        existing = cursor.get(component)
        child = dict(existing) if isinstance(existing, Mapping) else {}
        cursor[component] = child
        cursor = child
    cursor[path[-1]] = replacement
    return updated


async def forward_arg_resource_changes(
    *,
    feed: ResourceChangeFeed,
    state_store: StateStore,
    event_bus: EventBus,
    topic: str,
    scope: str,
    ingestion_fence: ResourceChangeIngestionFence | None = None,
    deadline_seconds: float = DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Publish one bounded poll and advance its cursor after every event succeeds."""

    if deadline_seconds <= 0:
        raise ValueError("resource change feed deadline_seconds MUST be > 0")
    cursor_key = f"{_CURSOR_PREFIX}{scope}"
    saved = await state_store.read_state(cursor_key) or {}
    pending_ids = pending_event_ids(saved.get("pending_event_ids"))
    retry_count = hydration_retry_count(saved.get("hydration_retry_count"))
    gap_at = coverage_gap_at(saved.get("coverage_gap_at"))
    if pending_ids and (ingestion_fence is None or not await ingestion_fence.contains(pending_ids)):
        return 0
    cursor = str(saved.get("cursor") or "")
    if not cursor:
        cursor = feed.initial_cursor()
        await state_store.write_state(
            cursor_key,
            {
                "complete": False,
                "coverage_gap_at": gap_at.isoformat() if gap_at is not None else None,
                "cursor": cursor,
                "hydration_retry_count": retry_count,
                "last_event_cursor": None,
                "pending_event_ids": [],
                "published_event_count": 0,
            },
        )
    result: ResourceChangeFeedResult | None = None
    try:
        async with asyncio.timeout(deadline_seconds):
            result = await feed.poll(cursor)
            for event in result.events:
                await event_bus.publish(
                    topic,
                    event.resource_ref or scope,
                    event.model_dump(mode="json"),
                )
    except TimeoutError as exc:
        raise RuntimeError("resource change feed poll exceeded its deadline") from exc
    if result is None:
        raise RuntimeError("resource change feed poll produced no result")
    polled_at = (clock or (lambda: datetime.now(tz=UTC)))()
    if polled_at.tzinfo is None:
        raise RuntimeError("resource change feed clock MUST be timezone-aware")
    next_cursor = result.next_cursor
    if result.recovery_cursor is not None:
        retry_count += 1
        if retry_count >= feed.max_hydration_retries:
            next_cursor = result.recovery_cursor
            recovered_at, _gap_id = decode_cursor(result.recovery_cursor)
            if recovered_at is None:
                raise RuntimeError("resource change recovery cursor is malformed")
            gap_at = max(candidate for candidate in (gap_at, recovered_at) if candidate is not None)
            retry_count = 0
    else:
        retry_count = 0
    await state_store.write_state(
        cursor_key,
        {
            "complete": result.complete,
            "coverage_gap_at": gap_at.astimezone(UTC).isoformat() if gap_at is not None else None,
            "cursor": next_cursor,
            "hydration_retry_count": retry_count,
            "last_event_cursor": result.last_event_cursor,
            "last_polled_at": polled_at.astimezone(UTC).isoformat(),
            "pending_event_ids": [str(event.event_id) for event in result.events],
            "published_event_count": len(result.events),
        },
    )
    return len(result.events)

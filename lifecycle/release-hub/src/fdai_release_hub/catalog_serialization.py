"""Bounded streaming primitives for Release Hub catalog reads."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes
from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from fdai_release_hub.database import catalog_metadata, events, membership, releases

CATALOG_VIEW_LIMIT_MESSAGE = "Catalog view exceeds the 16 MiB service limit."
EXPORT_LIMIT_MESSAGE = "Catalog export exceeds the 8 MiB consumer limit."
BUILT_IN_CHANNELS = ("DEV", "RELEASE_CANDIDATE", "RELEASE")


class CatalogError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class BoundedJson:
    def __init__(self, limit: int, message: str) -> None:
        self._limit = limit
        self._message = message
        self._buffer = bytearray()

    @property
    def remaining(self) -> int:
        return self._limit - len(self._buffer)

    @property
    def message(self) -> str:
        return self._message

    def write(self, value: bytes) -> None:
        if len(value) > self.remaining:
            raise CatalogError(self._message, 503)
        self._buffer.extend(value)

    def value(self, value: object) -> None:
        self.write(canonical_bytes(value))

    def finish(self) -> bytes:
        return bytes(self._buffer)


def stream(db: Connection, statement: Any) -> Iterator[Any]:
    result = db.execute(
        statement.execution_options(stream_results=True, max_row_buffer=1, yield_per=1)
    )
    yield from result.mappings().yield_per(1)


def catalog_position(db: Connection) -> tuple[int, str]:
    latest = db.execute(
        select(events.c.revision, events.c.occurred_at).order_by(events.c.revision.desc()).limit(1)
    ).one_or_none()
    if latest is not None:
        return int(latest.revision), str(latest.occurred_at)
    created_at = db.execute(select(catalog_metadata.c.created_at)).scalar_one()
    return 0, str(created_at)


def ensure_row_bound(
    db: Connection,
    *,
    maximum: int,
    message: str,
    export_only: bool,
) -> None:
    release_filter = releases.c.signature.is_not(None) if export_only else None
    event_filter = (
        events.c.action.in_(("recall", "recall_capability", "lift_capability"))
        if export_only
        else None
    )
    release_count = select(func.count()).select_from(releases)
    event_count = select(func.count()).select_from(events)
    if release_filter is not None:
        release_count = release_count.where(release_filter)
    if event_filter is not None:
        event_count = event_count.where(event_filter)
    row_count = int(
        db.scalar(
            select(
                release_count.scalar_subquery()
                + event_count.scalar_subquery()
                + select(func.count()).select_from(membership).scalar_subquery()
            )
        )
        or 0
    )
    if row_count > maximum:
        raise CatalogError(message, 503)


def write_channels(
    db: Connection,
    writer: BoundedJson,
    *,
    is_custom_channel: Callable[[str | None], bool],
) -> None:
    channel_names = set(BUILT_IN_CHANNELS)
    encoded_size = sum(len(canonical_bytes(channel)) + 1 for channel in channel_names) + 2
    channels = db.scalars(
        select(membership.c.channel)
        .distinct()
        .order_by(membership.c.channel)
        .execution_options(stream_results=True, max_row_buffer=1, yield_per=1)
    ).yield_per(1)
    for channel in channels:
        if channel not in BUILT_IN_CHANNELS and not is_custom_channel(channel):
            raise CatalogError("Stored catalog channel is invalid.")
        if channel not in channel_names:
            encoded_size += len(canonical_bytes(channel)) + 1
            if encoded_size > writer.remaining:
                raise CatalogError(writer.message, 503)
        channel_names.add(channel)

    writer.write(b"{")
    first_channel = True
    for channel in sorted(channel_names):
        if not first_channel:
            writer.write(b",")
        first_channel = False
        writer.value(channel)
        writer.write(b":[")
        first_release = True
        release_ids = db.scalars(
            select(membership.c.release_id)
            .where(membership.c.channel == channel)
            .order_by(membership.c.release_id)
            .execution_options(stream_results=True, max_row_buffer=1, yield_per=1)
        ).yield_per(1)
        for release_id in release_ids:
            if not first_release:
                writer.write(b",")
            first_release = False
            writer.value(release_id)
        writer.write(b"]")
    writer.write(b"}")


def release_channels(
    db: Connection,
    release_id: str,
    maximum: int,
) -> list[str]:
    channels: list[str] = []
    encoded_size = 2
    rows = db.scalars(
        select(membership.c.channel)
        .where(membership.c.release_id == release_id)
        .order_by(membership.c.channel)
        .execution_options(stream_results=True, max_row_buffer=1, yield_per=1)
    ).yield_per(1)
    for channel in rows:
        encoded_size += len(canonical_bytes(channel)) + bool(channels)
        if encoded_size > maximum:
            raise CatalogError(CATALOG_VIEW_LIMIT_MESSAGE, 503)
        channels.append(channel)
    return channels

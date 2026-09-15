"""Durable state_kv reservations for internal channel attachment intake."""

from __future__ import annotations

import json
from collections.abc import Mapping

import psycopg
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    DocumentNotFoundError,
)
from psycopg.rows import dict_row

from fdai_ingestion_api_service.channel_attachment import (
    ChannelAttachmentConflictError,
    ChannelAttachmentReservation,
)

_PREFIX = "channel_attachment_admission:"


class PostgresChannelAttachmentReservationStore:
    """Persist immutable handoff requests and receipts in one owned namespace."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn.strip() or connect_timeout_s < 1:
            raise ValueError("channel attachment reservation database config is invalid")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def reserve(
        self,
        reservation: ChannelAttachmentReservation,
    ) -> ChannelAttachmentReservation:
        key = _key(reservation.request.handoff_id)
        async with await self._connect() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO NOTHING",
                (key, _encode(reservation)),
            )
            stored = await _read(connection, key)
        if stored.request != reservation.request:
            raise ChannelAttachmentConflictError(
                "channel attachment handoff conflicts with its durable request"
            )
        return stored

    async def get(self, handoff_id: str) -> ChannelAttachmentReservation:
        key = _key(handoff_id)
        async with await self._connect() as connection:
            return await _read(connection, key)

    async def record_commit(
        self,
        *,
        handoff_id: str,
        request_digest: str,
        commit: ChannelAttachmentCommitReceipt,
    ) -> ChannelAttachmentReservation:
        key = _key(handoff_id)
        async with await self._connect() as connection, connection.transaction():
            stored = await _read(connection, key, for_update=True)
            if stored.request.request_digest != request_digest:
                raise ChannelAttachmentConflictError(
                    "channel attachment request digest does not match reservation"
                )
            if stored.commit is not None:
                if not _same_commit(stored.commit, commit):
                    raise ChannelAttachmentConflictError(
                        "channel attachment commit conflicts with its durable receipt"
                    )
                return stored
            updated = ChannelAttachmentReservation(
                request=stored.request,
                admission=stored.admission,
                commit=commit,
            )
            cursor = await connection.execute(
                "UPDATE state_kv SET value = %s::jsonb, updated_at = NOW() WHERE key = %s",
                (_encode(updated), key),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("channel attachment reservation update was not persisted")
            return updated

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, object]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        )


async def _read(
    connection: psycopg.AsyncConnection[dict[str, object]],
    key: str,
    *,
    for_update: bool = False,
) -> ChannelAttachmentReservation:
    statement = (
        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE"
        if for_update
        else "SELECT value FROM state_kv WHERE key = %s"
    )
    row = await (await connection.execute(statement, (key,))).fetchone()
    if row is None:
        raise DocumentNotFoundError("channel attachment reservation was not found")
    return _decode(row["value"])


def _encode(reservation: ChannelAttachmentReservation) -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "request": reservation.request.model_dump(mode="json"),
            "admission": reservation.admission.model_dump(mode="json"),
            "commit": (
                None if reservation.commit is None else reservation.commit.model_dump(mode="json")
            ),
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode(value: object) -> ChannelAttachmentReservation:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError("channel attachment reservation is invalid JSON") from exc
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema_version",
            "request",
            "admission",
            "commit",
        }
        or value.get("schema_version") != "1.0.0"
    ):
        raise RuntimeError("channel attachment reservation is malformed")
    commit = value["commit"]
    return ChannelAttachmentReservation(
        request=ChannelAttachmentAdmissionRequest.model_validate(value["request"]),
        admission=ChannelAttachmentAdmissionReceipt.model_validate(value["admission"]),
        commit=(None if commit is None else ChannelAttachmentCommitReceipt.model_validate(commit)),
    )


def _key(handoff_id: str) -> str:
    if not handoff_id.startswith("channel-attachment-") or len(handoff_id) != 83:
        raise ValueError("channel attachment handoff id is invalid")
    return _PREFIX + handoff_id


def _same_commit(
    left: ChannelAttachmentCommitReceipt,
    right: ChannelAttachmentCommitReceipt,
) -> bool:
    return (
        left.schema_version == right.schema_version
        and left.receipt_kind == right.receipt_kind
        and left.handoff_id == right.handoff_id
        and left.request_digest == right.request_digest
        and left.upload_id == right.upload_id
        and left.document_id == right.document_id
        and left.version_id == right.version_id
        and left.observed_size == right.observed_size
        and left.observed_sha256 == right.observed_sha256
        and left.state == right.state
        and left.execution_authority is right.execution_authority
    )


__all__ = ["PostgresChannelAttachmentReservationStore"]

"""Durability tests for channel attachment reservations in state_kv."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from uuid import UUID

import pytest
from fdai_ingestion_api_service.adapters.channel_attachment import (
    PostgresChannelAttachmentReservationStore,
    _decode,
    _encode,
    _same_commit,
)
from fdai_ingestion_api_service.channel_attachment import ChannelAttachmentReservation
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    canonical_digest,
)
from pydantic import TypeAdapter

NOW = datetime(2026, 9, 14, tzinfo=UTC)
HANDOFF_ID = "channel-attachment-" + "a" * 64


def _model(model: type, material: dict[str, object]):  # type: ignore[type-arg]
    normalized = {
        name: TypeAdapter(model.model_fields[name].annotation).validate_python(value)
        for name, value in material.items()
    }
    provisional = model.model_construct(
        **normalized,
        receipt_digest="sha256:" + "0" * 64,
    )
    wire = provisional.model_dump(mode="json", exclude={"receipt_digest"})
    return model.model_validate({**wire, "receipt_digest": canonical_digest(wire)})


def _reservation(*, committed: bool = True) -> ChannelAttachmentReservation:
    request_material: dict[str, object] = {
        "schema_version": "1.0.0",
        "handoff_id": HANDOFF_ID,
        "idempotency_key": "message:attachment:0",
        "origin_digest": "sha256:" + "b" * 64,
        "ordinal": 0,
        "attributed_principal_id": "principal-example",
        "principal_manifest_digest": "sha256:" + "c" * 64,
        "conversation_ref": "conversation-example",
        "requested_purpose": "knowledge_base",
        "source_name": "evidence.txt",
        "media_type_hint": "text/plain",
        "declared_size": 8,
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    request = ChannelAttachmentAdmissionRequest.model_validate(
        {**request_material, "request_digest": canonical_digest(request_material)}
    )
    admission_material = {
        "schema_version": "1.0.0",
        "receipt_kind": "admission",
        "handoff_id": HANDOFF_ID,
        "request_digest": request.request_digest,
        "policy_digest": "sha256:" + "d" * 64,
        "max_content_bytes": 1024,
        "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    commit_material = {
        "schema_version": "1.0.0",
        "receipt_kind": "commit",
        "handoff_id": HANDOFF_ID,
        "request_digest": request.request_digest,
        "upload_id": UUID(int=1),
        "document_id": UUID(int=2),
        "version_id": UUID(int=3),
        "observed_size": 8,
        "observed_sha256": "e" * 64,
        "state": "received",
        "committed_at": NOW.isoformat().replace("+00:00", "Z"),
        "execution_authority": False,
    }
    return ChannelAttachmentReservation(
        request=request,
        admission=_model(ChannelAttachmentAdmissionReceipt, admission_material),
        commit=(_model(ChannelAttachmentCommitReceipt, commit_material) if committed else None),
    )


class _Cursor:
    def __init__(self, row: dict[str, object] | None = None, *, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Context:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback


class _Connection(_Context):
    def __init__(self, stored: ChannelAttachmentReservation, *, update_count: int = 1) -> None:
        self.stored = stored
        self.update_count = update_count
        self.statements: list[str] = []

    def transaction(self) -> _Context:
        return _Context()

    async def execute(self, statement: str, _params: object) -> _Cursor:
        self.statements.append(statement)
        if statement.startswith("SELECT"):
            return _Cursor({"value": _encode(self.stored)})
        return _Cursor(rowcount=self.update_count)


def test_reservation_round_trip_and_same_content_replay_ignore_observation_time() -> None:
    reservation = _reservation()
    assert _decode(_encode(reservation)) == reservation
    assert reservation.commit is not None
    later_material = reservation.commit.model_dump(mode="json", exclude={"receipt_digest"})
    later_material["committed_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    later = _model(ChannelAttachmentCommitReceipt, later_material)

    assert _same_commit(reservation.commit, later)
    assert not _same_commit(
        reservation.commit,
        later.model_copy(update={"observed_sha256": "f" * 64}),
    )


async def test_record_commit_returns_existing_same_content_without_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _reservation()
    assert stored.commit is not None
    connection = _Connection(stored)
    store = PostgresChannelAttachmentReservationStore(dsn="postgresql://example/fdai")

    async def connect() -> _Connection:
        return connection

    monkeypatch.setattr(store, "_connect", connect)
    later_material = stored.commit.model_dump(mode="json", exclude={"receipt_digest"})
    later_material["committed_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    later = _model(ChannelAttachmentCommitReceipt, later_material)

    observed = await store.record_commit(
        handoff_id=HANDOFF_ID,
        request_digest=stored.request.request_digest,
        commit=later,
    )

    assert observed == stored
    assert len(connection.statements) == 1


async def test_record_commit_requires_one_persisted_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _reservation(committed=False)
    commit = _reservation().commit
    assert commit is not None
    connection = _Connection(stored, update_count=0)
    store = PostgresChannelAttachmentReservationStore(dsn="postgresql://example/fdai")

    async def connect() -> _Connection:
        return connection

    monkeypatch.setattr(store, "_connect", connect)

    with pytest.raises(RuntimeError, match="not persisted"):
        await store.record_commit(
            handoff_id=HANDOFF_ID,
            request_digest=stored.request.request_digest,
            commit=commit,
        )


def test_state_kv_schema_carries_updated_at_for_commit_cas() -> None:
    migration = Path("alembic/versions/20260705_0004_state_kv.py").read_text(encoding="utf-8")
    assert "updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()" in migration

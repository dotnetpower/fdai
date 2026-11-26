"""Tests for exact handover draft and governance receipt readback."""

from __future__ import annotations

from types import TracebackType
from uuid import UUID

import pytest
from fdai_ingestion_api_service.adapters.handover import PostgresHandoverDraftReader
from fdai_service_contracts import (
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    StewardResponsibility,
    StewardshipDraft,
    handover_governance_idempotency_key,
)


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Connection:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values
        self.keys: list[str] = []

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    async def execute(self, _statement: str, params: tuple[str]) -> _Cursor:
        key = params[0]
        self.keys.append(key)
        value = self.values.get(key)
        return _Cursor(None if value is None else {"value": value})


def _artifact() -> HandoverDraftArtifact:
    return HandoverDraftArtifact(
        upload_id=UUID(int=1),
        document_id=UUID(int=2),
        version_id=UUID(int=3),
        draft=StewardshipDraft(
            outcome=HandoverDraftOutcome.DRAFTED,
            mappings=(
                HandoverMapping(
                    agent_name="Thor",
                    person=HandoverPerson(display_name="Example owner"),
                    responsibility=StewardResponsibility.ACCOUNTABLE,
                    confidence=1.0,
                    citations=(
                        HandoverSourceSpan(
                            doc_id="handover-fixture",
                            line=1,
                            quote="Thor ownership transfers to the example owner.",
                        ),
                    ),
                ),
            ),
        ),
        yaml="version: 2\nrevision: handover-fixture\n",
    )


def _receipt(artifact: HandoverDraftArtifact, **updates: object) -> dict[str, object]:
    idempotency_key = handover_governance_idempotency_key(artifact)
    value: dict[str, object] = {
        "upload_id": str(artifact.upload_id),
        "document_id": str(artifact.document_id),
        "version_id": str(artifact.version_id),
        "idempotency_key": idempotency_key,
        "published": True,
        "reason": None,
        "pr_ref": "refs/pull/123/head",
    }
    value.update(updates)
    return value


async def _reader(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
) -> tuple[PostgresHandoverDraftReader, _Connection]:
    connection = _Connection(values)

    async def connect(*_args: object, **_kwargs: object) -> _Connection:
        return connection

    monkeypatch.setattr(
        "fdai_ingestion_api_service.adapters.handover.psycopg.AsyncConnection.connect",
        connect,
    )
    return PostgresHandoverDraftReader(dsn="postgresql://example/fdai"), connection


async def test_handover_reader_uses_exact_draft_and_governance_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    idempotency_key = handover_governance_idempotency_key(artifact)
    governance_key = "stewardship_governance:" + idempotency_key.removeprefix(
        "stewardship-handover:"
    )
    reader, connection = await _reader(
        monkeypatch,
        {
            f"handover_draft:{artifact.upload_id}": artifact.to_dict(),
            governance_key: _receipt(artifact),
        },
    )

    observed = await reader.get(artifact.upload_id)

    assert observed == artifact
    assert await reader.governance_delivered(observed) is True
    assert connection.keys == [f"handover_draft:{artifact.upload_id}", governance_key]


async def test_handover_reader_keeps_missing_or_unpublished_delivery_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    idempotency_key = handover_governance_idempotency_key(artifact)
    governance_key = "stewardship_governance:" + idempotency_key.removeprefix(
        "stewardship-handover:"
    )
    reader, _connection = await _reader(
        monkeypatch,
        {governance_key: _receipt(artifact, published=False, reason="no_mapping", pr_ref=None)},
    )

    assert await reader.governance_delivered(artifact) is False


async def test_handover_reader_rejects_substituted_governance_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact()
    idempotency_key = handover_governance_idempotency_key(artifact)
    governance_key = "stewardship_governance:" + idempotency_key.removeprefix(
        "stewardship-handover:"
    )
    reader, _connection = await _reader(
        monkeypatch,
        {governance_key: _receipt(artifact, document_id=str(UUID(int=9)))},
    )

    with pytest.raises(RuntimeError, match="governance receipt is malformed"):
        await reader.governance_delivered(artifact)

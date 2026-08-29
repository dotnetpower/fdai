"""PostgreSQL A3-E transaction-boundary tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fdai.core.standing_authority.lifecycle import (
    AuthenticatedAuthorizationCommand,
    AuthorizationCommandKind,
    AuthorizationLifecycleCommand,
    AuthorizationLifecycleError,
    AuthorizationRevision,
    authorization_revision_id,
)
from fdai.core.standing_authority.record import StandingAuthorization
from fdai.delivery.persistence.postgres_standing_authority import (
    PostgresStandingAuthorizationLifecycleStore,
)

NOW = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _command(
    *,
    family_id: str = "family:one",
    command_id: str = "command:admit",
) -> AuthorizationLifecycleCommand:
    authorization = StandingAuthorization.from_mapping(
        {
            "schema_version": "1.0.0",
            "id": "sa.example",
            "authorization_revision": "pending",
            "status": "active",
            "mode": "shadow",
            "requested_by": "human:requester",
            "approvals": [
                {
                    "principal": "human:service-owner",
                    "role": "service_owner",
                    "approved_at": "2026-08-29T05:00:00Z",
                },
                {
                    "principal": "human:owner",
                    "role": "owner",
                    "approved_at": "2026-08-29T05:01:00Z",
                },
            ],
            "quorum_required": 2,
            "valid_from": "2026-08-29T05:00:00Z",
            "valid_until": "2026-08-30T05:00:00Z",
            "service_ref": "service:example",
            "scope": {"level": "resource", "value": "scope:example"},
            "pins": {
                "policy_digest": "sha256:policy",
                "target_revision": "target:1",
                "action_type_versions": ["ops.scale-out@1.0.0"],
                "evidence_revisions": ["evidence:1"],
            },
            "envelope": {
                "action_types": ["ops.scale-out"],
                "max_blast_radius": 1,
                "max_duration_seconds": 60,
                "reversible": True,
                "rollback_contract": "scripted",
                "stop_conditions": ["provider-error"],
            },
            "incident_classes": ["capacity"],
            "responders": {
                "primary": "human:primary",
                "backup": "human:backup",
                "confirmed_at": "2026-08-29T05:00:00Z",
            },
            "evidence": {
                "history_reviewed": True,
                "precedent_ref": "case:one",
                "scenario_evidence_ref": None,
            },
        }
    )
    revision_id = authorization_revision_id(
        family_id=family_id,
        predecessor_revision_id=None,
        issued_at=NOW,
        authorization=authorization,
    )
    revision = AuthorizationRevision.create(
        family_id=family_id,
        predecessor_revision_id=None,
        issued_at=NOW,
        authorization=authorization,
        approvals_digest=DIGEST,
        evidence_verification_bundle_digest="sha256:" + "e" * 64,
        proof_subject_revision_id=revision_id,
    )
    return AuthorizationLifecycleCommand(
        kind=AuthorizationCommandKind.ADMIT,
        family_id=revision.family_id,
        context=AuthenticatedAuthorizationCommand(
            command_id=command_id,
            actor_ref="human:owner",
            actor_kind="human",
            actor_roles=frozenset({"owner"}),
            authentication_evidence_digest="sha256:" + "f" * 64,
            authenticated_at=NOW,
            correlation_id="correlation:one",
        ),
        occurred_at=NOW,
        expected_revision_id=None,
        expected_fencing_generation=0,
        revision=revision,
    )


class _Cursor:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: tuple[dict[str, object], ...] = (),
        rowcount: int = 1,
    ) -> None:
        self._row = row
        self._rows = rows
        self.rowcount = rowcount

    async def fetchone(self) -> dict[str, object] | None:
        return self._row

    async def fetchall(self) -> tuple[dict[str, object], ...]:
        return self._rows


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> None:
        self._connection.pending = []

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        if exc_type is None:
            self._connection.durable.extend(self._connection.pending)
        self._connection.pending = []


class _Connection:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.durable: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    async def execute(self, query: str, _params: object = None) -> _Cursor:
        compact = " ".join(query.split())
        if "SELECT family_id" in compact and "FOR UPDATE" in compact:
            return _Cursor(row={"family_id": "family:one"})
        if "FROM standing_authorization_transition" in compact and "ORDER BY" in compact:
            return _Cursor(rows=())
        if "FROM standing_authorization_revision" in compact:
            return _Cursor(rows=())
        if "FROM standing_authorization_snapshot" in compact:
            return _Cursor(row=None)
        if "INSERT INTO standing_authorization_audit" in compact:
            raise RuntimeError("simulated audit write failure")
        if compact.startswith(("INSERT", "UPDATE", "DELETE")):
            self.pending.append(compact)
        return _Cursor()


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="DSN"):
        PostgresStandingAuthorizationLifecycleStore(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresStandingAuthorizationLifecycleStore(
            dsn="postgresql://example",
            statement_timeout_ms=0,
        )


async def test_partial_audit_failure_rolls_back_every_lifecycle_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresStandingAuthorizationLifecycleStore(dsn="postgresql://example.invalid/fdai")
    connection = _Connection()

    async def connect() -> _Connection:
        return connection

    async def timeout(_connection: object) -> None:
        return None

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "_timeout", timeout)

    with pytest.raises(RuntimeError, match="audit write failure"):
        await store.apply(_command())

    assert connection.durable == []


@pytest.mark.skipif(not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset")
async def test_postgres_store_round_trips_snapshot_and_primary_fence() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"].replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    suffix = uuid4().hex
    family_id = f"family:test:{suffix}"
    command = _command(
        family_id=family_id,
        command_id=f"command:admit:{suffix}",
    )
    store = PostgresStandingAuthorizationLifecycleStore(dsn=dsn)
    try:
        applied = await store.apply(command)
        duplicate = await store.apply(command)

        assert duplicate.snapshot == applied.snapshot
        assert await store.read_snapshot(family_id) == applied.snapshot
        assert await store.check_fence(applied.snapshot.fence())
        import psycopg

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM standing_authorization_snapshot WHERE family_id = %s",
                (family_id,),
            )
        with pytest.raises(AuthorizationLifecycleError, match="missing or stale"):
            await store.read_snapshot(family_id)
        assert await store.rebuild_snapshot(family_id) == applied.snapshot
    finally:
        import psycopg

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM standing_authorization_audit WHERE family_id = %s",
                (family_id,),
            )
            await connection.execute(
                "DELETE FROM standing_authorization_snapshot WHERE family_id = %s",
                (family_id,),
            )
            await connection.execute(
                "DELETE FROM standing_authorization_transition WHERE family_id = %s",
                (family_id,),
            )
            await connection.execute(
                "DELETE FROM standing_authorization_revision WHERE family_id = %s",
                (family_id,),
            )
            await connection.execute(
                "DELETE FROM standing_authorization_family WHERE family_id = %s",
                (family_id,),
            )

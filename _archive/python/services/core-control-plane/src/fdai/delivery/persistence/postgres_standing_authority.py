"""PostgreSQL single-writer store for the shadow A3-E lifecycle."""

from __future__ import annotations

import json
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.standing_authority.lifecycle import (
    AuthorizationCommandKind,
    AuthorizationLifecycleCommand,
    AuthorizationLifecycleError,
    AuthorizationLifecycleWriteResult,
    AuthorizationProofBindings,
    AuthorizationRevision,
    AuthorizationSnapshot,
    AuthorizationSnapshotStatus,
    AuthorizationTransition,
    LifecycleFence,
    audit_entry_for,
    fence_matches,
    plan_lifecycle_transition,
    replay_lifecycle,
)
from fdai.shared.providers.standing_authority import StandingAuthorizationStoreError


class PostgresStandingAuthorizationLifecycleStore:
    """Serialize each family and commit its full lifecycle boundary atomically."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn.strip():
            raise ValueError("standing authorization PostgreSQL DSN MUST be non-empty")
        if statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("standing authorization PostgreSQL timeouts MUST be positive")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def apply(
        self,
        command: AuthorizationLifecycleCommand,
    ) -> AuthorizationLifecycleWriteResult:
        """Commit an admit, renew, or revoke command in one family transaction."""

        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_family(connection, command.family_id)
            transitions = await self._transitions(connection, command.family_id)
            revisions = await self._revisions(connection, command.family_id)
            snapshot = await self._snapshot(connection, command.family_id)
            result = plan_lifecycle_transition(
                snapshot=snapshot,
                transitions=transitions,
                revisions=revisions,
                command=command,
            )
            if result.status.value == "duplicate":
                return result
            if command.revision is not None:
                await self._insert_revision(connection, command.revision)
            await self._insert_transition(connection, result.transition)
            await self._insert_audit(connection, result.transition)
            await self._write_snapshot(connection, result.snapshot)
            return result

    async def read_revision(self, revision_id: str) -> AuthorizationRevision | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                """
                SELECT *
                  FROM standing_authorization_revision
                 WHERE revision_id = %s
                """,
                (revision_id,),
            )
            row = await cursor.fetchone()
            return _revision(row) if row is not None else None

    async def read_transitions(
        self,
        family_id: str,
    ) -> tuple[AuthorizationTransition, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._transitions(connection, family_id)

    async def read_snapshot(self, family_id: str) -> AuthorizationSnapshot | None:
        """Fail closed when an authoritative history has lost its projection."""

        async with await self._connect() as connection:
            await self._timeout(connection)
            snapshot = await self._anchored_snapshot(connection, family_id)
            if snapshot is not None:
                return snapshot
            cursor = await connection.execute(
                """
                SELECT 1
                  FROM standing_authorization_transition
                 WHERE family_id = %s
                 LIMIT 1
                """,
                (family_id,),
            )
            if await cursor.fetchone() is not None:
                raise AuthorizationLifecycleError(
                    "standing authorization projection is missing or stale for retained history"
                )
            return None

    async def rebuild_snapshot(self, family_id: str) -> AuthorizationSnapshot | None:
        """Rebuild from a complete ordered chain without creating authority."""

        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            await self._lock_family(connection, family_id)
            transitions = await self._transitions(connection, family_id)
            revisions = await self._revisions(connection, family_id)
            rebuilt = replay_lifecycle(transitions=transitions, revisions=revisions)
            if rebuilt is None:
                await connection.execute(
                    "DELETE FROM standing_authorization_snapshot WHERE family_id = %s",
                    (family_id,),
                )
                return None
            await self._write_snapshot(connection, rebuilt)
            return rebuilt

    async def check_fence(self, fence: LifecycleFence) -> bool:
        """Read the primary snapshot and require an exact active fence."""

        try:
            async with await self._connect() as connection:
                await self._timeout(connection)
                return fence_matches(
                    await self._anchored_snapshot(connection, fence.family_id),
                    fence,
                )
        except psycopg.Error as exc:
            raise StandingAuthorizationStoreError(
                "standing authorization primary fence read failed"
            ) from exc

    async def _lock_family(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        family_id: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO standing_authorization_family (family_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (family_id,),
        )
        cursor = await connection.execute(
            """
            SELECT family_id
              FROM standing_authorization_family
             WHERE family_id = %s
             FOR UPDATE
            """,
            (family_id,),
        )
        if await cursor.fetchone() is None:
            raise RuntimeError("standing authorization family lock was not acquired")

    async def _transitions(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        family_id: str,
    ) -> tuple[AuthorizationTransition, ...]:
        cursor = await connection.execute(
            """
            SELECT *
              FROM standing_authorization_transition
             WHERE family_id = %s
             ORDER BY sequence
            """,
            (family_id,),
        )
        return tuple(_transition(row) for row in await cursor.fetchall())

    async def _revisions(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        family_id: str,
    ) -> dict[str, AuthorizationRevision]:
        cursor = await connection.execute(
            """
            SELECT *
              FROM standing_authorization_revision
             WHERE family_id = %s
            """,
            (family_id,),
        )
        revisions = tuple(_revision(row) for row in await cursor.fetchall())
        return {revision.revision_id: revision for revision in revisions}

    async def _snapshot(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        family_id: str,
    ) -> AuthorizationSnapshot | None:
        cursor = await connection.execute(
            """
            SELECT *
              FROM standing_authorization_snapshot
             WHERE family_id = %s
            """,
            (family_id,),
        )
        row = await cursor.fetchone()
        return _snapshot(row) if row is not None else None

    async def _anchored_snapshot(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        family_id: str,
    ) -> AuthorizationSnapshot | None:
        cursor = await connection.execute(
            """
            SELECT snapshot.*
              FROM standing_authorization_snapshot AS snapshot
              JOIN standing_authorization_transition AS head
                ON head.family_id = snapshot.family_id
               AND head.sequence = snapshot.last_sequence
               AND head.transition_digest = snapshot.head_transition_digest
             WHERE snapshot.family_id = %s
               AND NOT EXISTS (
                   SELECT 1
                     FROM standing_authorization_transition AS later
                    WHERE later.family_id = snapshot.family_id
                      AND later.sequence > snapshot.last_sequence
               )
            """,
            (family_id,),
        )
        row = await cursor.fetchone()
        return _snapshot(row) if row is not None else None

    async def _insert_revision(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        revision: AuthorizationRevision,
    ) -> None:
        cursor = await connection.execute(
            """
            INSERT INTO standing_authorization_revision (
                revision_id, family_id, predecessor_revision_id, issued_at,
                terms, document, approval_claim_digest, approvals_digest,
                evidence_claim_digest, evidence_verification_bundle_digest
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                revision.revision_id,
                revision.family_id,
                revision.predecessor_revision_id,
                revision.issued_at,
                Jsonb(json.loads(revision.terms_json)),
                Jsonb(json.loads(revision.document_json)),
                revision.proof_bindings.approval_claim_digest,
                revision.proof_bindings.approvals_digest,
                revision.proof_bindings.evidence_claim_digest,
                revision.proof_bindings.evidence_verification_bundle_digest,
            ),
        )
        if cursor.rowcount != 1:
            raise AuthorizationLifecycleError("authorization revision already exists")

    async def _insert_transition(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        transition: AuthorizationTransition,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO standing_authorization_transition (
                family_id, sequence, kind, command_id, command_digest,
                actor_ref, actor_roles, authentication_evidence_digest,
                authenticated_at, correlation_id, revision_id, predecessor_revision_id,
                fencing_generation, occurred_at, previous_transition_digest,
                transition_digest
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                transition.family_id,
                transition.sequence,
                transition.kind.value,
                transition.command_id,
                transition.command_digest,
                transition.actor_ref,
                Jsonb(list(transition.actor_roles)),
                transition.authentication_evidence_digest,
                transition.authenticated_at,
                transition.correlation_id,
                transition.revision_id,
                transition.predecessor_revision_id,
                transition.fencing_generation,
                transition.occurred_at,
                transition.previous_transition_digest,
                transition.transition_digest,
            ),
        )

    async def _insert_audit(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        transition: AuthorizationTransition,
    ) -> None:
        entry = dict(audit_entry_for(transition))
        await connection.execute(
            """
            INSERT INTO standing_authorization_audit (
                transition_digest, family_id, sequence, audit_digest, entry
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                transition.transition_digest,
                transition.family_id,
                transition.sequence,
                cast(str, entry["audit_digest"]),
                Jsonb(entry),
            ),
        )

    async def _write_snapshot(
        self,
        connection: psycopg.AsyncConnection[dict[str, Any]],
        snapshot: AuthorizationSnapshot,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO standing_authorization_snapshot (
                family_id, current_revision_id, status, fencing_generation,
                last_sequence, head_transition_digest, snapshot_digest
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (family_id) DO UPDATE SET
                current_revision_id = EXCLUDED.current_revision_id,
                status = EXCLUDED.status,
                fencing_generation = EXCLUDED.fencing_generation,
                last_sequence = EXCLUDED.last_sequence,
                head_transition_digest = EXCLUDED.head_transition_digest,
                snapshot_digest = EXCLUDED.snapshot_digest
            """,
            (
                snapshot.family_id,
                snapshot.current_revision_id,
                snapshot.status.value,
                snapshot.fencing_generation,
                snapshot.last_sequence,
                snapshot.head_transition_digest,
                snapshot.snapshot_digest,
            ),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            connect_timeout=self._connect_timeout_s,
            row_factory=dict_row,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )


def _revision(row: dict[str, Any]) -> AuthorizationRevision:
    revision_id = cast(str, row["revision_id"])
    return AuthorizationRevision(
        family_id=cast(str, row["family_id"]),
        revision_id=revision_id,
        predecessor_revision_id=cast(str | None, row["predecessor_revision_id"]),
        issued_at=cast(Any, row["issued_at"]),
        terms_json=_canonical_json(row["terms"]),
        document_json=_canonical_json(row["document"]),
        proof_bindings=AuthorizationProofBindings(
            revision_id=revision_id,
            approval_claim_digest=cast(str, row["approval_claim_digest"]),
            approvals_digest=cast(str, row["approvals_digest"]),
            evidence_claim_digest=cast(str, row["evidence_claim_digest"]),
            evidence_verification_bundle_digest=cast(
                str,
                row["evidence_verification_bundle_digest"],
            ),
        ),
    )


def _transition(row: dict[str, Any]) -> AuthorizationTransition:
    return AuthorizationTransition(
        family_id=cast(str, row["family_id"]),
        sequence=cast(int, row["sequence"]),
        kind=AuthorizationCommandKind(cast(str, row["kind"])),
        command_id=cast(str, row["command_id"]),
        command_digest=cast(str, row["command_digest"]),
        actor_ref=cast(str, row["actor_ref"]),
        actor_roles=tuple(cast(list[str], row["actor_roles"])),
        authentication_evidence_digest=cast(str, row["authentication_evidence_digest"]),
        authenticated_at=cast(Any, row["authenticated_at"]),
        correlation_id=cast(str, row["correlation_id"]),
        revision_id=cast(str, row["revision_id"]),
        predecessor_revision_id=cast(str | None, row["predecessor_revision_id"]),
        fencing_generation=cast(int, row["fencing_generation"]),
        occurred_at=cast(Any, row["occurred_at"]),
        previous_transition_digest=cast(str | None, row["previous_transition_digest"]),
        transition_digest=cast(str, row["transition_digest"]),
    )


def _snapshot(row: dict[str, Any]) -> AuthorizationSnapshot:
    return AuthorizationSnapshot(
        family_id=cast(str, row["family_id"]),
        current_revision_id=cast(str, row["current_revision_id"]),
        status=AuthorizationSnapshotStatus(cast(str, row["status"])),
        fencing_generation=cast(int, row["fencing_generation"]),
        last_sequence=cast(int, row["last_sequence"]),
        head_transition_digest=cast(str, row["head_transition_digest"]),
        snapshot_digest=cast(str, row["snapshot_digest"]),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = ["PostgresStandingAuthorizationLifecycleStore"]

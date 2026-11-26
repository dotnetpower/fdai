"""PostgresAdvisoryResourceLock - distributed per-resource lock.

Realizes the :class:`~fdai.shared.providers.resource_lock.ResourceLock`
Protocol on PostgreSQL session advisory locks, so per-resource mutual
exclusion holds across every replica (not just within one process like
the in-memory :class:`~fdai.core.executor.lock.ResourceLockManager`).

Design
------
- ``hashtextextended(resource_id, 0)`` maps a resource id to a stable
  bigint key - the same id yields the same key in every replica, so
  ``pg_advisory_lock`` gives cross-replica mutual exclusion.
- The lock is *session-scoped* and held on a dedicated ``autocommit``
  connection for the whole critical section. Session locks (unlike
  ``pg_advisory_xact_lock``) do not pin an open transaction, so the
  action can run for its full duration without an idle-in-transaction
  connection.
- Crash-safety: closing the connection (normal exit OR a crashed holder)
  releases the session lock automatically, so a dead holder never wedges
  the resource.
- ``lock_timeout_ms`` bounds the acquire wait; on timeout ``acquire``
  raises (fail toward safety - the caller does not mutate) rather than
  blocking a replica forever behind a stuck holder.

psycopg 3 is already a repo dependency (see the sibling adapters).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.shared.providers.resource_lock import (
    MAX_LOCK_ASSESSMENT_TTL,
    HeldResourceLock,
    HeldResourceLockLifecycle,
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)

_LOG = logging.getLogger(__name__)

_LOCK_SQL = "SELECT pg_advisory_lock(hashtextextended(%s, 0))"
_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"
_EVIDENCED_ACQUIRE_SQL = """
SELECT pg_advisory_lock(hashtextextended(%s, 0)) AS acquired,
       current_database() AS database_name,
       pg_backend_pid() AS backend_pid,
       backend_start,
       clock_timestamp() AS observed_at
FROM pg_stat_activity
WHERE pid = pg_backend_pid()
"""
_OWNERSHIP_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM pg_locks
    WHERE locktype = 'advisory'
      AND pid = pg_backend_pid()
      AND granted
      AND classid = ((hashtextextended(%s, 0) >> 32) & 4294967295)::oid
      AND objid = (hashtextextended(%s, 0) & 4294967295)::oid
      AND objsubid = 1
) AS owns_lock,
current_database() AS database_name,
pg_backend_pid() AS backend_pid,
backend_start,
clock_timestamp() AS evaluated_at
FROM pg_stat_activity
WHERE pid = pg_backend_pid()
"""
_EVIDENCED_UNLOCK_SQL = """
SELECT pg_advisory_unlock(hashtextextended(%s, 0)) AS released,
       clock_timestamp() AS released_at
"""
_PROVIDER_ID = "postgres-advisory-lock"
_PROVIDER_VERSION = "1.0.0"
_VERIFIER_ID = "postgres-pg-locks-readback"


class ResourceLockOwnershipUnknownError(RuntimeError):
    """The exact PostgreSQL session can no longer prove lock ownership."""


class ResourceLockReleaseUnknownError(RuntimeError):
    """PostgreSQL did not prove release of the exact advisory lock."""


@dataclass(frozen=True, slots=True)
class PostgresAdvisoryResourceLockConfig:
    """DSN + acquire-wait bound for the distributed lock."""

    dsn: str
    """psycopg 3 connection string, e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    lock_timeout_ms: int = 30_000
    """Max wait to acquire before failing closed. ``0`` waits forever
    (matching the in-process ``asyncio.Lock`` semantics)."""

    connect_timeout_s: int = 10
    """Bound the TCP/auth handshake so a dead DB fails fast instead of
    hanging the event loop before the lock wait even begins."""

    trust_anchor_id: str = "postgres:primary"
    continuity_policy: EffectSinkContinuityPolicy | None = None


class _HeldPostgresResourceLock:
    """One exact dedicated PostgreSQL session acquisition."""

    def __init__(
        self,
        *,
        connection: psycopg.AsyncConnection[Any],
        lifecycle: HeldResourceLockLifecycle,
        backend_pid: int,
        backend_start: datetime,
        provider_instance_digest: str,
    ) -> None:
        self._connection = connection
        self._lifecycle = lifecycle
        self._backend_pid = backend_pid
        self._backend_start = backend_start
        self._provider_instance_digest = provider_instance_digest
        self._release_receipt: ResourceLockReleaseReceipt | None = None
        self._session_unusable = False

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        return self._lifecycle.acquisition_request

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        return self._lifecycle.acquisition_receipt

    def require_active(self) -> None:
        self._lifecycle.require_active()

    @property
    def release_receipt(self) -> ResourceLockReleaseReceipt | None:
        return self._release_receipt

    def deactivate(self) -> None:
        self._lifecycle.deactivate()

    @property
    def session_unusable(self) -> bool:
        return self._session_unusable

    def mark_session_unusable(self) -> None:
        self._session_unusable = True
        self.deactivate()

    def record_release(
        self,
        *,
        state: ResourceLockReleaseState,
        observed_at: datetime | None,
        recorded_at: datetime,
    ) -> None:
        if self._lifecycle.active:
            raise RuntimeError("PostgreSQL resource lock release recorded while active")
        self._release_receipt = ResourceLockReleaseReceipt.create(
            acquisition_receipt=self.acquisition_receipt,
            state=state,
            provider_attestation_digest=content_digest(
                {
                    "domain": "postgres-resource-lock-release",
                    "request_digest": self.acquisition_request.request_digest,
                    "provider_instance_digest": self._provider_instance_digest,
                    "backend_pid": self._backend_pid,
                    "backend_start": self._backend_start.isoformat(),
                    "state": state.value,
                    "observed_at": (observed_at.isoformat() if observed_at is not None else None),
                    "recorded_at": recorded_at.isoformat(),
                }
            ),
            observed_at=observed_at,
            recorded_at=recorded_at,
        )

    async def assess_ownership(self) -> LiveLockOwnershipAssessment:
        self.require_active()
        try:
            cursor = await self._connection.execute(
                _OWNERSHIP_SQL,
                (
                    self.acquisition_request.lock_key,
                    self.acquisition_request.lock_key,
                ),
            )
            row = await cursor.fetchone()
        except psycopg.Error as exc:
            self.mark_session_unusable()
            raise ResourceLockOwnershipUnknownError(
                "PostgreSQL lock ownership readback failed"
            ) from exc
        except asyncio.CancelledError:
            self.mark_session_unusable()
            raise
        if row is None:
            self.mark_session_unusable()
            raise ResourceLockOwnershipUnknownError(
                "PostgreSQL lock ownership readback is unavailable"
            )
        owns_lock = row.get("owns_lock")
        try:
            evaluated_at = _row_datetime(row.get("evaluated_at"), "evaluated_at")
        except ResourceLockOwnershipUnknownError:
            self.mark_session_unusable()
            raise
        if type(owns_lock) is not bool:
            self.mark_session_unusable()
            raise ResourceLockOwnershipUnknownError("PostgreSQL lock ownership readback is invalid")
        database_name = row.get("database_name")
        backend_pid = row.get("backend_pid")
        try:
            backend_start = _row_datetime(
                row.get("backend_start"),
                "backend_start",
            )
        except ResourceLockOwnershipUnknownError:
            self.mark_session_unusable()
            raise
        if type(database_name) is not str or type(backend_pid) is not int:
            self.mark_session_unusable()
            raise ResourceLockOwnershipUnknownError(
                "PostgreSQL lock ownership session identity is invalid"
            )
        observed_provider_instance = content_digest(
            {
                "domain": "postgres-resource-lock-instance",
                "database_name": database_name,
                "trust_anchor_id": self.acquisition_receipt.trust_anchor_id,
            }
        )
        same_session = bool(
            backend_pid == self._backend_pid
            and backend_start == self._backend_start
            and observed_provider_instance == self._provider_instance_digest
        )
        owns_exact_acquisition = owns_lock and same_session
        if owns_exact_acquisition is False:
            self.mark_session_unusable()
        current_session_identity = (
            self.acquisition_receipt.session_identity if owns_exact_acquisition else None
        )
        rejection_reasons = (
            () if owns_exact_acquisition else (LockOwnershipRejectionReason.LOCK_LOST,)
        )
        try:
            return LiveLockOwnershipAssessment.create(
                self.acquisition_receipt,
                current_fencing_generation=None,
                current_session_identity=current_session_identity,
                verifier_id=_VERIFIER_ID,
                verifier_version=_PROVIDER_VERSION,
                trust_anchor_id=self.acquisition_receipt.trust_anchor_id,
                provider_attestation_digest=content_digest(
                    {
                        "domain": "postgres-resource-lock-readback",
                        "request_digest": self.acquisition_request.request_digest,
                        "provider_instance_digest": self._provider_instance_digest,
                        "backend_pid": backend_pid,
                        "backend_start": backend_start.isoformat(),
                        "owns_lock": owns_exact_acquisition,
                        "evaluated_at": evaluated_at.isoformat(),
                    }
                ),
                evaluated_at=evaluated_at,
                valid_until=evaluated_at + MAX_LOCK_ASSESSMENT_TTL,
                rejection_reasons=rejection_reasons,
            )
        except ValueError as exc:
            self.mark_session_unusable()
            raise ResourceLockOwnershipUnknownError(
                "PostgreSQL lock ownership assessment is invalid"
            ) from exc


class PostgresAdvisoryResourceLock:
    """Distributed :class:`ResourceLock` via Postgres session advisory locks."""

    distributed = True

    def __init__(self, *, config: PostgresAdvisoryResourceLockConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresAdvisoryResourceLockConfig.dsn MUST NOT be empty")
        if config.lock_timeout_ms < 0:
            raise ValueError("lock_timeout_ms MUST be >= 0")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if (
            type(config.trust_anchor_id) is not str
            or not config.trust_anchor_id.strip()
            or config.trust_anchor_id != config.trust_anchor_id.strip()
        ):
            raise ValueError("trust_anchor_id MUST be canonical")
        if (
            config.continuity_policy is not None
            and type(config.continuity_policy) is not EffectSinkContinuityPolicy
        ):
            raise ValueError("continuity_policy MUST be an exact reviewed policy")
        self._config = config

    @property
    def production_eligible(self) -> bool:
        """Require one reviewed sink continuity policy for production use."""

        return bool(
            self._config.continuity_policy is not None
            and self._config.continuity_policy.strategy
            is OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION
        )

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            if self._config.lock_timeout_ms > 0:
                # set_config takes bind params (plain SET does not); bound
                # to the session so the advisory-lock wait is capped.
                await conn.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(self._config.lock_timeout_ms),),
                )
            await conn.execute(_LOCK_SQL, (resource_id,))
            try:
                yield
            finally:
                # Explicit unlock keeps the key count tidy; the connection
                # close below also releases every session lock, so a
                # failure here is not fatal.
                try:
                    await conn.execute(_UNLOCK_SQL, (resource_id,))
                except Exception:  # noqa: BLE001 - close() still releases it
                    _LOG.warning(
                        "advisory_unlock_failed",
                        extra={"resource_id": resource_id},
                        exc_info=True,
                    )

    @asynccontextmanager
    async def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AsyncIterator[HeldResourceLock]:
        """Acquire and attest one exact target on a dedicated session."""

        if type(request) is not ResourceLockAcquisitionRequest:
            raise ValueError("PostgreSQL evidenced lock requires a canonical request")
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            if self._config.lock_timeout_ms > 0:
                await connection.execute(
                    "SELECT set_config('lock_timeout', %s, false)",
                    (str(self._config.lock_timeout_ms),),
                )
            try:
                session_cursor = await connection.execute(
                    _EVIDENCED_ACQUIRE_SQL,
                    (request.lock_key,),
                )
                session_row = await session_cursor.fetchone()
            except psycopg.Error as exc:
                raise ResourceLockOwnershipUnknownError(
                    "PostgreSQL backend session readback failed"
                ) from exc
            if session_row is None:
                raise ResourceLockOwnershipUnknownError(
                    "PostgreSQL backend session identity is unavailable"
                )
            database_name = session_row.get("database_name")
            backend_pid = session_row.get("backend_pid")
            backend_start = _row_datetime(
                session_row.get("backend_start"),
                "backend_start",
            )
            acquired_at = _row_datetime(
                session_row.get("observed_at"),
                "observed_at",
            )
            if type(database_name) is not str or type(backend_pid) is not int:
                raise ResourceLockOwnershipUnknownError(
                    "PostgreSQL backend session identity is invalid"
                )
            provider_instance_digest = content_digest(
                {
                    "domain": "postgres-resource-lock-instance",
                    "database_name": database_name,
                    "trust_anchor_id": self._config.trust_anchor_id,
                }
            )
            session_identity = content_digest(
                {
                    "domain": "postgres-resource-lock-session",
                    "provider_instance_digest": provider_instance_digest,
                    "backend_pid": backend_pid,
                    "backend_start": backend_start.isoformat(),
                }
            )
            owner_reference_digest = content_digest(
                {
                    "domain": "postgres-resource-lock-owner",
                    "request_digest": request.request_digest,
                    "session_identity": session_identity,
                }
            )
            receipt = ResourceLockAcquisitionReceipt.create(
                lock_key=request.lock_key,
                target_digest=request.target_digest,
                action_digest=request.action_digest,
                attempt=request.attempt,
                provider_id=_PROVIDER_ID,
                provider_version=_PROVIDER_VERSION,
                producer_id=request.producer_id,
                producer_version=request.producer_version,
                owner_token_digest=owner_reference_digest,
                fencing_generation=None,
                session_identity=session_identity,
                provider_attestation_digest=content_digest(
                    {
                        "domain": "postgres-resource-lock-acquisition",
                        "request_digest": request.request_digest,
                        "provider_instance_digest": provider_instance_digest,
                        "session_identity": session_identity,
                        "acquired_at": acquired_at.isoformat(),
                    }
                ),
                trust_anchor_id=self._config.trust_anchor_id,
                acquired_at=acquired_at,
                valid_until=None,
                source_revision=request.source_revision,
                request_digest=request.request_digest,
            )
            lifecycle = HeldResourceLockLifecycle(request, receipt)
            handle = _HeldPostgresResourceLock(
                connection=connection,
                lifecycle=lifecycle,
                backend_pid=backend_pid,
                backend_start=backend_start,
                provider_instance_digest=provider_instance_digest,
            )
            try:
                yield handle
            finally:
                active_exception = sys.exc_info()[1]
                handle.deactivate()
                if handle.session_unusable:
                    handle.record_release(
                        state=ResourceLockReleaseState.UNKNOWN,
                        observed_at=None,
                        recorded_at=datetime.now(UTC),
                    )
                    if not isinstance(active_exception, asyncio.CancelledError):
                        raise ResourceLockReleaseUnknownError(
                            "PostgreSQL resource lock session became unusable"
                        )
                else:
                    try:
                        await self._release_evidenced(
                            connection=connection,
                            request=request,
                            handle=handle,
                        )
                    except ResourceLockReleaseUnknownError:
                        if not isinstance(active_exception, asyncio.CancelledError):
                            raise

    async def _release_evidenced(
        self,
        *,
        connection: psycopg.AsyncConnection[Any],
        request: ResourceLockAcquisitionRequest,
        handle: _HeldPostgresResourceLock,
    ) -> None:
        try:
            unlock_cursor = await connection.execute(
                _EVIDENCED_UNLOCK_SQL,
                (request.lock_key,),
            )
            unlock_row = await unlock_cursor.fetchone()
        except psycopg.Error as exc:
            handle.record_release(
                state=ResourceLockReleaseState.UNKNOWN,
                observed_at=None,
                recorded_at=datetime.now(UTC),
            )
            raise ResourceLockReleaseUnknownError(
                "PostgreSQL resource lock release failed"
            ) from exc
        except asyncio.CancelledError:
            handle.record_release(
                state=ResourceLockReleaseState.UNKNOWN,
                observed_at=None,
                recorded_at=datetime.now(UTC),
            )
            raise
        if unlock_row is None:
            handle.record_release(
                state=ResourceLockReleaseState.UNKNOWN,
                observed_at=None,
                recorded_at=datetime.now(UTC),
            )
            raise ResourceLockReleaseUnknownError(
                "PostgreSQL did not confirm resource lock release"
            )
        try:
            released_at = _row_datetime(
                unlock_row.get("released_at"),
                "released_at",
            )
        except ResourceLockOwnershipUnknownError as exc:
            handle.record_release(
                state=ResourceLockReleaseState.UNKNOWN,
                observed_at=None,
                recorded_at=datetime.now(UTC),
            )
            raise ResourceLockReleaseUnknownError(
                "PostgreSQL resource lock release time is invalid"
            ) from exc
        released = unlock_row.get("released")
        if type(released) is not bool:
            handle.record_release(
                state=ResourceLockReleaseState.UNKNOWN,
                observed_at=None,
                recorded_at=released_at,
            )
            raise ResourceLockReleaseUnknownError(
                "PostgreSQL resource lock release result is invalid"
            )
        handle.record_release(
            state=(
                ResourceLockReleaseState.RELEASED if released else ResourceLockReleaseState.LOST
            ),
            observed_at=released_at,
            recorded_at=released_at,
        )
        if released is False:
            raise ResourceLockReleaseUnknownError(
                "PostgreSQL did not confirm resource lock release"
            )


def _row_datetime(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ResourceLockOwnershipUnknownError(
            f"PostgreSQL resource lock {name} MUST include a timezone"
        )
    return value.astimezone(UTC)


__all__ = [
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
    "ResourceLockOwnershipUnknownError",
    "ResourceLockReleaseUnknownError",
]

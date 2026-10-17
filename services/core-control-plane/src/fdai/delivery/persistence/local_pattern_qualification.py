"""Real row-level coherent leases for the isolated LOCAL PostgreSQL owner backend."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import RetainedPatternQualification
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import RetainedPatternLeaseEvidence
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

from .local_pattern_owner import local_dsn
from .local_pattern_validation import artifact_key, base_keys, validate_locked


class LocalPostgresPatternQualifier:
    """Lock the closed dependency set, including negative members and authorization.

    Only the LOCAL owner sources in this module's sibling adapter are supported.
    A real database row lock, not an epoch convention, blocks every UPDATE/DELETE
    and conflicting upsert through the normal StateStore or another connection.
    No new permission is minted: the lease carries the two independently retained
    readiness admissions. It is valid only inside ``lease`` and is never persisted.
    """

    def __init__(
        self,
        *,
        dsn: str,
        venue: str,
        clock: Callable[[], datetime] | None = None,
        statement_timeout_ms: int = 1500,
    ) -> None:
        pinned = local_dsn(dsn, venue=venue)
        if not 1 <= statement_timeout_ms <= 3000:
            raise ValueError("local Pattern lease timeout is out of bounds")
        self._dsn, self._timeout = pinned, statement_timeout_ms
        self._clock = clock or (lambda: datetime.now(UTC))

    async def qualify(
        self, request: RetainedPatternQualification
    ) -> DecisionEvidenceAdmission | None:
        """An unleased call cannot safely qualify; never replace it with a new permission."""
        return None

    @asynccontextmanager
    async def lease(
        self, request: RetainedPatternQualification
    ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
        value = request.descriptor
        if not 1 <= len(value["cohort"]["cases"]) <= 100:
            raise ValueError("local Pattern lease cohort is out of bounds")
        keys = set(base_keys(value))
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row, connect_timeout=2
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(self._timeout),)
                )
                # Discover storage coordinates only; no eligibility is inferred here.
                metadata_keys = [key for key in keys if key.startswith("case-history:latest:")]
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = ANY(%s)", (metadata_keys,)
                )
                for row in await cursor.fetchall():
                    storage = row["value"].get("storage_ref")
                    if isinstance(storage, str):
                        keys.add(artifact_key(storage))
                if len(keys) > 256:
                    raise ValueError("local Pattern lease dependency set is out of bounds")
                cursor = await connection.execute(
                    "SELECT key, value FROM state_kv WHERE key = ANY(%s) ORDER BY key FOR SHARE",
                    (sorted(keys),),
                )
                rows: dict[str, dict[str, Any]] = {
                    row["key"]: row["value"] for row in await cursor.fetchall()
                }
                if rows.keys() != keys:
                    yield None
                    return
                # A changed metadata coordinate references an unlocked/missing artifact
                # and fails closed. There is no expanding read/lock retry loop.
                try:
                    qualified = validate_locked(request, rows, now=self._clock())
                except (KeyError, TypeError, ValueError):
                    qualified = None
                if qualified is None:
                    yield None
                    return
                qualified.guard.active = True
                try:
                    yield qualified
                finally:
                    qualified.guard.active = False

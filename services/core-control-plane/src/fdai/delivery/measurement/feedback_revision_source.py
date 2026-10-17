"""Read current immutable scalar outcome chains from the owning audit database."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai.core.assurance_twin.feedback_rebuild import latest_feedback_revisions
from fdai.delivery.measurement.postgres_growth import _mapping, _response_outcome
from fdai.shared.contracts.models import ResponseOutcome
from psycopg.rows import dict_row

_LOGGER = logging.getLogger("fdai.measurement.feedback_revision_source")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORDS = 1024


class PostgresFeedbackRevisionSource:
    """Qualify heads, not labels or permissions, from one bounded audit snapshot.

    Missing records or incomplete predecessor chains withhold the model. The
    adapter never copies audit bodies, approves a rebuild, or promotes a model.
    """

    def __init__(
        self,
        *,
        dsn: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("feedback revision source requires its owning audit DSN")
        self._dsn = dsn
        self._clock = clock or (lambda: datetime.now(UTC))

    async def current(self, revision_digests: tuple[str, ...]) -> bool:
        if (
            not revision_digests
            or len(revision_digests) > _MAX_RECORDS
            or len(set(revision_digests)) != len(revision_digests)
            or any(_DIGEST.fullmatch(value) is None for value in revision_digests)
        ):
            raise ValueError("feedback revision manifest requires bounded unique SHA-256 values")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("feedback revision source clock requires a timezone")
        async with asyncio.timeout(5):
            rows = await self._rows(revision_digests)
        if len(rows) > _MAX_RECORDS:
            return self._unavailable("feedback_source_window_truncated")
        outcomes: list[ResponseOutcome] = []
        for row in rows:
            outcome = _response_outcome(_mapping(row["entry"]))
            if outcome is None:
                return self._unavailable("feedback_source_invalid_outcome")
            outcomes.append(outcome)
        requested = frozenset(revision_digests)
        indexed = {outcome.revision_digest: outcome for outcome in outcomes}
        if not requested.issubset(indexed):
            return self._unavailable("feedback_source_revision_missing")
        identities = {indexed[digest].outcome_id for digest in requested}
        relevant = tuple(outcome for outcome in outcomes if outcome.outcome_id in identities)
        if any(item.schema_version != "1.1.0" for item in relevant):
            return self._unavailable("feedback_source_legacy_lineage_unavailable")
        if any(item.recorded_at > now for item in relevant):
            return self._unavailable("feedback_source_future_revision")
        try:
            latest = latest_feedback_revisions(relevant, as_of=now)
        except ValueError:
            return self._unavailable("feedback_source_revision_chain_invalid")
        if any(item.revision_digest not in requested for item in latest):
            return self._unavailable("feedback_source_revision_superseded")
        return True

    @staticmethod
    def _unavailable(reason: str) -> bool:
        _LOGGER.warning("feedback_revision_source_unavailable", extra={"reason": reason})
        return False

    async def outcomes_for_scope(
        self,
        *,
        action_type_id: str,
        metric: str,
    ) -> tuple[ResponseOutcome, ...]:
        """Load complete bounded scope input for an independently admitted rebuild."""
        if not action_type_id or not metric:
            raise ValueError("feedback rebuild scope requires action type and metric")
        async with (
            asyncio.timeout(5),
            await psycopg.AsyncConnection.connect(
                self._dsn,
                row_factory=dict_row,
                connect_timeout=3,
            ) as connection,
        ):
            await connection.execute("SELECT set_config('statement_timeout', %s, true)", ("4000",))
            cursor = await connection.execute(
                "SELECT entry FROM audit_log WHERE action_kind = %s "
                "AND entry->>'action_type_id' = %s AND entry->>'metric' = %s "
                "AND entry->>'schema_version' = %s "
                "ORDER BY seq ASC LIMIT %s",
                (
                    "measurement.action_outcome.v1",
                    action_type_id,
                    metric,
                    "1.1.0",
                    _MAX_RECORDS + 1,
                ),
            )
            rows = await cursor.fetchall()
        if len(rows) > _MAX_RECORDS:
            raise ValueError("feedback rebuild scope exceeds its complete-history bound")
        outcomes = tuple(_response_outcome(_mapping(row["entry"])) for row in rows)
        if any(item is None for item in outcomes):
            raise ValueError("feedback rebuild source includes invalid outcomes")
        return tuple(item for item in outcomes if item is not None)

    async def _rows(self, revision_digests: tuple[str, ...]) -> Sequence[Mapping[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=3,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", ("4000",)
                )
                cursor = await connection.execute(
                    "SELECT entry FROM audit_log WHERE action_kind = %s "
                    "AND entry->>'outcome_revision_digest' = ANY(%s) "
                    "ORDER BY seq DESC LIMIT %s",
                    ("measurement.action_outcome.v1", list(revision_digests), _MAX_RECORDS + 1),
                )
                witnesses = await cursor.fetchall()
                parsed = tuple(_response_outcome(_mapping(row["entry"])) for row in witnesses)
                if any(item is None for item in parsed):
                    return witnesses
                identities = {item.outcome_id.hex for item in parsed if item is not None}
                if not identities:
                    return witnesses
                cursor = await connection.execute(
                    "SELECT entry FROM audit_log WHERE action_kind = %s "
                    "AND translate(regexp_replace(lower(entry->>'outcome_id'), "
                    "'^urn:uuid:', ''), '{}-', '') "
                    "= ANY(%s) ORDER BY seq DESC LIMIT %s",
                    ("measurement.action_outcome.v1", sorted(identities), _MAX_RECORDS + 1),
                )
                return await cursor.fetchall()

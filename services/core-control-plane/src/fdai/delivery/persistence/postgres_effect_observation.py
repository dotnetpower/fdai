"""PostgreSQL append-only store for independent effect observations.

Append-only is enforced twice.  The migration grants only ``SELECT`` and
``INSERT``, so no statement this module could issue can mutate a retained
receipt.  The insert itself is idempotent on the exact receipt: a replayed
observation returns the retained row, while a *different* receipt at an
occupied sequence position raises rather than overwriting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationReceipt,
)
from fdai.core.executor.effect_observation_codec import (
    observation_receipt_from_mapping,
    observation_receipt_to_mapping,
)
from fdai.core.executor.effect_observation_ledger import (
    IndependentEffectLedgerError,
)
from fdai.core.executor.safeguard_dispatch_support import validate_digest

_INSERT_SQL = (
    "INSERT INTO independent_effect_observation "
    "(evidence_identity_digest, sequence, observation_id, receipt_digest, "
    "prior_receipt_digest, safeguard_bundle_digest, outcome, disposition, "
    "effect_verified, observer_instance_id, executor_instance_id, "
    "source_instance_id, receipt) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (evidence_identity_digest, sequence) DO NOTHING"
)
_SELECT_ONE_SQL = (
    "SELECT receipt FROM independent_effect_observation "
    "WHERE evidence_identity_digest = %s AND sequence = %s"
)
_SELECT_LINEAGE_SQL = (
    "SELECT receipt FROM independent_effect_observation "
    "WHERE evidence_identity_digest = %s ORDER BY sequence ASC"
)


@dataclass(frozen=True, slots=True)
class PostgresIndependentEffectObservationStoreConfig:
    """Connection and statement bounds for observation retention."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresIndependentEffectObservationStore:
    """Sequence-unique insert with exact-receipt idempotency and strict readback."""

    production_eligible = True

    def __init__(
        self,
        *,
        config: PostgresIndependentEffectObservationStoreConfig,
    ) -> None:
        if not config.dsn:
            raise ValueError(
                "PostgresIndependentEffectObservationStoreConfig.dsn MUST NOT be empty"
            )
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        self._config = config

    async def append(
        self,
        receipt: IndependentEffectObservationReceipt,
    ) -> IndependentEffectObservationReceipt:
        """Persist one receipt, or return the identical retained receipt."""

        if type(receipt) is not IndependentEffectObservationReceipt:
            raise IndependentEffectLedgerError("observation store requires an exact receipt")
        payload = observation_receipt_to_mapping(receipt)
        async with await self._connect() as connection:
            async with connection.transaction():
                await self._set_statement_timeout(connection)
                await connection.execute(_INSERT_SQL, _params(receipt, payload))
                cursor = await connection.execute(
                    _SELECT_ONE_SQL,
                    (receipt.binding.evidence_identity_digest, receipt.sequence),
                )
                row = await cursor.fetchone()
        if row is None:
            raise IndependentEffectLedgerError("observation insert produced no retained receipt")
        retained = observation_receipt_from_mapping(row["receipt"])
        if retained.receipt_digest != receipt.receipt_digest:
            raise IndependentEffectLedgerError(
                "a different observation already occupies this sequence"
            )
        return retained

    async def read_lineage(
        self,
        evidence_identity_digest: str,
    ) -> tuple[IndependentEffectObservationReceipt, ...]:
        """Return every retained receipt for one dispatch, in sequence order."""

        validate_digest("evidence_identity_digest", evidence_identity_digest)
        async with await self._connect() as connection:
            await self._set_statement_timeout(connection)
            cursor = await connection.execute(
                _SELECT_LINEAGE_SQL,
                (evidence_identity_digest,),
            )
            rows = await cursor.fetchall()
        return tuple(observation_receipt_from_mapping(row["receipt"]) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_s,
            row_factory=dict_row,
        )

    async def _set_statement_timeout(
        self,
        connection: psycopg.AsyncConnection[Any],
    ) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


def _params(
    receipt: IndependentEffectObservationReceipt,
    payload: dict[str, object],
) -> tuple[object, ...]:
    return (
        receipt.binding.evidence_identity_digest,
        receipt.sequence,
        receipt.observation_id,
        receipt.receipt_digest,
        receipt.prior_receipt_digest,
        receipt.binding.safeguard_bundle_digest,
        receipt.outcome.value,
        receipt.disposition.value,
        receipt.effect_verified,
        receipt.observer_instance_id,
        receipt.executor_instance_id,
        receipt.source_instance_id,
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


__all__ = [
    "PostgresIndependentEffectObservationStore",
    "PostgresIndependentEffectObservationStoreConfig",
]

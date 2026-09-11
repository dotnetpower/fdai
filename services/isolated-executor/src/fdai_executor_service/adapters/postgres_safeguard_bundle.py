"""Read-only PostgreSQL resolver for Core safeguard proof bundles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from fdai_service_contracts.execution_safeguards import SafeguardProofBundle
from psycopg.rows import dict_row

_SELECT_SQL = """
SELECT record
FROM safeguard_dispatch_evidence
WHERE record #>> '{bundle,bundle_digest}' = %s
ORDER BY generation DESC
LIMIT 2
"""


@dataclass(frozen=True, slots=True)
class PostgresSafeguardBundleStoreConfig:
    """Connection and query bounds for isolated bundle readback."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


class PostgresSafeguardBundleStore:
    """Resolve exactly one Core-persisted bundle by content digest."""

    def __init__(self, *, config: PostgresSafeguardBundleStoreConfig) -> None:
        if not config.dsn:
            raise ValueError("PostgresSafeguardBundleStoreConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1 or config.connect_timeout_s < 1:
            raise ValueError("PostgreSQL safeguard bundle timeouts MUST be positive")
        self._config = config

    async def resolve_bundle(self, bundle_digest: str) -> SafeguardProofBundle | None:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(_SELECT_SQL, (bundle_digest,))
            rows = await cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RuntimeError("safeguard bundle digest resolved to multiple generations")
        record = rows[0].get("record")
        if not isinstance(record, Mapping):
            raise ValueError("persisted safeguard evidence is malformed")
        raw_bundle: Any = record.get("bundle")
        if not isinstance(raw_bundle, Mapping):
            raise ValueError("persisted safeguard proof bundle is missing")
        bundle = SafeguardProofBundle.model_validate(dict(raw_bundle))
        if bundle.bundle_digest != bundle_digest:
            raise ValueError("persisted safeguard proof bundle digest mismatched")
        return bundle


__all__ = [
    "PostgresSafeguardBundleStore",
    "PostgresSafeguardBundleStoreConfig",
]

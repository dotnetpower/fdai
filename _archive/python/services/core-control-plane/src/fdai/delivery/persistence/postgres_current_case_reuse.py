"""Verifier-role current-case reuse source reads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from fdai_service_contracts.operational_evidence import OperationalEvidenceSourceHealth

from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
    role_bound_connection,
)
from fdai.delivery.persistence.state_store_current_case_reuse import (
    current_case_reuse_source_key,
)

_PROBE_KEY = "current-case-reuse:v1:" + ("0" * 64)
_HEALTH_FAILURES = (OSError, PermissionError, RuntimeError, ValueError, psycopg.Error)


class PostgresCurrentCaseReuseSource:
    """Read retained current-case reuse rows through a fixed-parameter function."""

    source_ids = (
        "inventory.current-snapshot",
        "core-control-plane.case-history",
        "core-control-plane.safety-receipts",
    )

    def __init__(self, config: PostgresOperationalEvidenceConfig) -> None:
        if config.expected_role != VERIFIER_ROLE:
            raise ValueError("current-case reuse source requires the verifier role")
        self._config = config

    async def current_reuse(
        self, *, case_ref: str, resource_ref: str, event_id: str
    ) -> Mapping[str, object] | None:
        key = current_case_reuse_source_key(case_ref, resource_ref, event_id)
        async with role_bound_connection(self._config) as connection:
            row = await (
                await connection.execute(
                    "SELECT public.fdai_current_case_reuse_source(%s) AS value",
                    (key,),
                )
            ).fetchone()
        value: Any = row["value"] if row is not None else None
        return value if isinstance(value, Mapping) else None

    async def source_health(self) -> dict[str, OperationalEvidenceSourceHealth]:
        try:
            async with role_bound_connection(self._config) as connection:
                await (
                    await connection.execute(
                        "SELECT public.fdai_current_case_reuse_source(%s) IS NULL AS absent",
                        (_PROBE_KEY,),
                    )
                ).fetchone()
        except _HEALTH_FAILURES:
            health = OperationalEvidenceSourceHealth.UNAVAILABLE
        else:
            health = OperationalEvidenceSourceHealth.HEALTHY
        return {source_id: health for source_id in self.source_ids}


__all__ = ["PostgresCurrentCaseReuseSource"]

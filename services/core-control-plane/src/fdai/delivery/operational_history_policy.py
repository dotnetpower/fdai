"""Load deployment-owned operational history retention policies."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from fdai.core.ontology_platform.operational_history_retention import (
    ObservationRetentionPolicy,
    load_retention_policy_registry,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventorySnapshotObservationAppendResult,
    PostgresInventoryObservationJournal,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)

RETENTION_POLICY_PATH_ENV = "FDAI_OPERATIONAL_HISTORY_RETENTION_PATH"
_MAX_POLICY_FILE_BYTES = 256 * 1024


def load_operational_history_retention_policies(
    environ: Mapping[str, str],
) -> tuple[ObservationRetentionPolicy, ...]:
    """Load optional deployment policy; absence preserves the safe retain default."""

    raw_path = environ.get(RETENTION_POLICY_PATH_ENV, "").strip()
    if not raw_path:
        return ()
    path = Path(raw_path)
    if not path.is_file():
        raise ValueError(f"{RETENTION_POLICY_PATH_ENV} MUST identify a readable file")
    if path.stat().st_size > _MAX_POLICY_FILE_BYTES:
        raise ValueError("operational history retention policy file exceeds its byte bound")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("operational history retention policy file is invalid") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0.0":
        raise ValueError("operational history retention policy schema is unsupported")
    policies = raw.get("policies")
    if not isinstance(policies, Sequence) or isinstance(policies, str | bytes):
        raise ValueError("operational history retention policies MUST be an array")
    if not all(isinstance(value, Mapping) for value in policies):
        raise ValueError("operational history retention policy entries MUST be objects")
    registry = load_retention_policy_registry(policies)
    return tuple(registry[key] for key in sorted(registry))


class ConfiguredInventoryObservationJournal:
    """Persist deployment policy before delegating normalized observation writes."""

    def __init__(
        self,
        *,
        journal: PostgresInventoryObservationJournal,
        policies: tuple[ObservationRetentionPolicy, ...],
        history: PostgresOperationalHistoryStore,
    ) -> None:
        self._journal = journal
        self._policies = policies
        self._history = history

    async def append_promoted_snapshot(
        self,
        observation: PromotedInventoryObservation,
    ) -> InventorySnapshotObservationAppendResult:
        if observation.recorded_at is None:
            raise ValueError("promoted inventory observation recorded_at MUST be supplied")
        await self._persist_policies(observation.recorded_at)
        return await self._journal.append_promoted_snapshot(observation)

    async def mark_ontology_projected(self, *, generation: str, watermark: int) -> None:
        await self._journal.mark_ontology_projected(
            generation=generation,
            watermark=watermark,
        )

    async def _persist_policies(self, recorded_at: datetime) -> None:
        for policy in self._policies:
            await self._history.put_retention_policy(policy, recorded_at=recorded_at)


def build_observation_journal(
    dsn: str,
    environ: Mapping[str, str],
) -> ConfiguredInventoryObservationJournal:
    """Compose policy persistence with the normalized journal."""

    return ConfiguredInventoryObservationJournal(
        journal=PostgresInventoryObservationJournal(
            config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
        ),
        policies=load_operational_history_retention_policies(environ),
        history=PostgresOperationalHistoryStore(config=PostgresOperationalHistoryConfig(dsn=dsn)),
    )


__all__ = [
    "RETENTION_POLICY_PATH_ENV",
    "ConfiguredInventoryObservationJournal",
    "build_observation_journal",
    "load_operational_history_retention_policies",
]

"""Runtime composition for durable forecast case history and analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from fdai.core.case_history import (
    CaseHistoryAnalyzer,
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
)
from fdai.core.case_history.dual_write import DualWriteCaseHistoryMetadataStore
from fdai.core.learning import ConsensusPostTurnReviewer, PostTurnProposalModel
from fdai.delivery.azure.case_history_artifacts import (
    AzureBlobCaseHistoryArtifactStore,
    AzureBlobCaseHistoryConfig,
)
from fdai.delivery.persistence.postgres_case_history import (
    PostgresCaseHistoryMetadataStore,
    PostgresCaseHistoryMetadataStoreConfig,
)
from fdai.delivery.persistence.state_store_case_history import (
    StateStoreCaseHistoryMetadataStore,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.case_history import CaseHistoryMetadataStore
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class CaseHistoryRuntime:
    metadata: CaseHistoryMetadataStore
    materializer: CaseHistoryMaterializer
    analyzer: CaseHistoryAnalyzer | None
    retention: CaseHistoryRetentionService


class CaseHistoryRetentionTickPublisher:
    """Publish bounded retention ticks through Huginn's raw ingress topic."""

    def __init__(
        self,
        *,
        bus: EventBus,
        topic: str,
        interval_seconds: int = 86_400,
        runtime_settings: RuntimeSettingsService | None = None,
    ) -> None:
        if not topic.strip():
            raise ValueError("case history retention topic MUST be non-empty")
        if interval_seconds < 1:
            raise ValueError("case history retention interval MUST be positive")
        self._bus = bus
        self._topic = topic
        self._interval_seconds = interval_seconds
        self._runtime_settings = runtime_settings

    async def publish_once(
        self,
        *,
        now: datetime,
        interval_seconds: int | None = None,
    ) -> None:
        if now.tzinfo is None:
            raise ValueError("case history retention tick MUST be timezone-aware")
        interval = interval_seconds or await self._effective_interval_seconds()
        bucket = int(now.timestamp()) // interval
        tick_id = f"case-history-retention:{bucket}"
        await self._bus.publish(
            self._topic,
            tick_id,
            {
                "event_id": tick_id,
                "idempotency_key": tick_id,
                "correlation_id": tick_id,
                "source": "case-history-retention-scheduler",
                "event_type": "case_history.retention_due",
                "attributes": {"as_of": now.isoformat()},
            },
        )

    async def run(self, *, stop: asyncio.Event) -> None:
        while not stop.is_set():
            interval = await self._effective_interval_seconds()
            await self.publish_once(now=datetime.now(UTC), interval_seconds=interval)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def _effective_interval_seconds(self) -> int:
        if self._runtime_settings is None:
            return self._interval_seconds
        effective = await self._runtime_settings.effective_values()
        interval = effective["case_history.retention_tick_seconds"]
        if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
            raise RuntimeError("effective case history retention interval is invalid")
        return interval


def build_case_history_runtime(
    *,
    container_url: str | None,
    state_store: StateStore,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    dsn: str | None = None,
    relational_read_authority: bool = False,
    models: tuple[PostTurnProposalModel, ...] = (),
) -> CaseHistoryRuntime | None:
    if container_url is None or not container_url.strip():
        return None
    if identity is None or http_client is None:
        raise RuntimeError("case history storage requires workload identity and HTTP bindings")
    metadata: CaseHistoryMetadataStore
    state_metadata = StateStoreCaseHistoryMetadataStore(store=state_store)
    if dsn is not None and dsn.strip():
        relational_metadata = PostgresCaseHistoryMetadataStore(
            config=PostgresCaseHistoryMetadataStoreConfig(dsn=dsn.strip())
        )
        metadata = DualWriteCaseHistoryMetadataStore(
            authority=state_metadata,
            shadow=relational_metadata,
            read_from_shadow=relational_read_authority,
        )
    else:
        metadata = state_metadata
    artifacts = AzureBlobCaseHistoryArtifactStore(
        config=AzureBlobCaseHistoryConfig(container_url=container_url),
        identity=identity,
        http_client=http_client,
    )
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    retention = CaseHistoryRetentionService(metadata=metadata, artifacts=artifacts)
    analyzer = None
    if len(models) >= 2:
        analyzer = CaseHistoryAnalyzer(
            metadata=metadata,
            artifacts=artifacts,
            reviewer=ConsensusPostTurnReviewer(models),
        )
    return CaseHistoryRuntime(
        metadata=metadata,
        materializer=materializer,
        analyzer=analyzer,
        retention=retention,
    )


def case_history_retention_days(
    retention_raw: str | None,
    deletion_raw: str | None,
) -> tuple[int, int]:
    retention = _positive_int("FDAI_CASE_HISTORY_RETENTION_DAYS", retention_raw, 30)
    deletion = _positive_int("FDAI_CASE_HISTORY_DELETION_DAYS", deletion_raw, 60)
    if deletion < retention:
        raise ValueError("case history deletion days MUST be >= retention days")
    return retention, deletion


def case_history_retention_tick_seconds(raw: str | None) -> int:
    return _positive_int("FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS", raw, 86_400)


def _positive_int(name: str, raw: str | None, default: int) -> int:
    try:
        value = int(raw.strip()) if raw and raw.strip() else default
    except ValueError as exc:
        raise ValueError(f"{name} MUST be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} MUST be a positive integer")
    return value


__all__ = [
    "CaseHistoryRetentionTickPublisher",
    "CaseHistoryRuntime",
    "build_case_history_runtime",
    "case_history_retention_days",
    "case_history_retention_tick_seconds",
]

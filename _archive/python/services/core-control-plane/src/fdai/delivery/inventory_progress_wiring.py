"""Compose count-only inventory progress publishers for one reconciliation run."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from fdai_service_contracts import InventoryProgressStage

from fdai.delivery.azure.inventory_progress_blob import (
    AzureBlobInventoryProgressConfig,
    AzureBlobInventoryProgressPublisher,
)
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_progress import (
    CompositeInventoryProgressPublisher,
    InventoryProgressPublisher,
    InventoryProgressRecorder,
)
from fdai.delivery.persistence.postgres_inventory_progress import (
    PostgresInventoryProgressStore,
    PostgresInventoryProgressStoreConfig,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity


async def build_inventory_progress_recorder(
    *,
    config: InventoryJobConfig,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    environment: Mapping[str, str] = os.environ,
) -> InventoryProgressRecorder:
    """Build and initialize one durable progress chain for a reconciliation attempt."""

    started_at = datetime.now(tz=UTC)
    publishers: list[InventoryProgressPublisher] = [
        PostgresInventoryProgressStore(config=PostgresInventoryProgressStoreConfig(dsn=config.dsn))
    ]
    if container_url := environment.get("FDAI_INVENTORY_PROGRESS_CONTAINER_URL"):
        publishers.append(
            AzureBlobInventoryProgressPublisher(
                config=AzureBlobInventoryProgressConfig(container_url=container_url),
                identity=identity,
                http_client=http_client,
            )
        )
    recorder = InventoryProgressRecorder(
        run_id=environment.get("FDAI_INVENTORY_PROGRESS_RUN_ID") or f"inventory.{uuid4().hex}",
        attempt_id=environment.get("FDAI_INVENTORY_PROGRESS_ATTEMPT_ID")
        or f"attempt.{uuid4().hex}",
        scopes_total=len(config.scopes),
        provider_types_total=0,
        pages_expected=0,
        started_at=started_at,
        deadline_at=started_at + timedelta(seconds=config.attempt_deadline_seconds + 300),
        publisher=CompositeInventoryProgressPublisher(*publishers),
        clock=lambda: datetime.now(tz=UTC),
    )
    await recorder.advance(InventoryProgressStage.COUNT)
    return recorder


__all__ = ["build_inventory_progress_recorder"]

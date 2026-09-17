"""Emit one sanitized independent inventory closure receipt."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import httpx

from fdai.delivery.azure.inventory_progress_blob import (
    AzureBlobInventoryProgressConfig,
    AzureBlobInventoryProgressPublisher,
)
from fdai.delivery.inventory_change_acceleration import workload_identity
from fdai.delivery.inventory_closure import (
    PostgresInventoryClosureVerifier,
    PostgresInventoryClosureVerifierConfig,
)
from fdai.delivery.inventory_progress import (
    CompositeInventoryProgressPublisher,
    InventoryProgressRecorder,
)
from fdai.delivery.persistence.postgres_inventory_progress import (
    PostgresInventoryProgressStore,
    PostgresInventoryProgressStoreConfig,
)


async def _main() -> None:
    dsn = os.environ.get("FDAI_INVENTORY_DSN", "").strip()
    run_id = os.environ.get("FDAI_INVENTORY_PROGRESS_RUN_ID", "").strip()
    attempt_id = os.environ.get("FDAI_INVENTORY_PROGRESS_ATTEMPT_ID", "").strip()
    if not run_id or not attempt_id:
        raise ValueError("inventory closure run and attempt identifiers MUST be supplied")
    progress_container_url = os.environ.get("FDAI_INVENTORY_PROGRESS_CONTAINER_URL", "").strip()
    if not progress_container_url:
        raise ValueError("inventory closure progress container URL MUST be supplied")
    verifier = PostgresInventoryClosureVerifier(
        config=PostgresInventoryClosureVerifierConfig(dsn=dsn)
    )
    receipt = await verifier.verify(run_id=run_id, attempt_id=attempt_id)
    latest = await verifier.latest_progress(run_id=run_id, attempt_id=attempt_id)
    if latest.state.value != "complete":
        async with httpx.AsyncClient() as client:
            identity = workload_identity(http_client=client)
            publisher = CompositeInventoryProgressPublisher(
                AzureBlobInventoryProgressPublisher(
                    config=AzureBlobInventoryProgressConfig(container_url=progress_container_url),
                    identity=identity,
                    http_client=client,
                ),
                PostgresInventoryProgressStore(
                    config=PostgresInventoryProgressStoreConfig(dsn=dsn)
                ),
            )
            await InventoryProgressRecorder.resume(
                latest,
                publisher=publisher,
                clock=lambda: datetime.now(tz=UTC),
            ).complete()
    print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))


def main() -> None:
    """Run the read-only closure observer in a process distinct from collection."""

    asyncio.run(_main())


if __name__ == "__main__":
    main()

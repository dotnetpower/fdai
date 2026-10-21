"""Configured-selector continuity at actual PostgreSQL recovery consumers, not identity proof."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.delivery.azure.dev_workload_identity import (
    AsyncAzureCliWorkloadIdentity,
    AzureCliWorkloadIdentity,
)
from fdai.delivery.azure.workload_identity import (
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)
from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
from fdai.delivery.inventory_collection import collection_context_digest
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_sync import InventorySyncCoordinator
from fdai.delivery.inventory_sync_cli_support import build_sources
from fdai.delivery.inventory_sync_models import (
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.delivery.persistence.postgres_inventory_prepared import (
    load_prepared_candidate,
    seal_candidate,
)
from fdai.delivery.persistence.postgres_inventory_resume import load_unfinished_collection
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventorySource

from tests.persistence.test_postgres_inventory_chunks import _database


class RecollectionRequiredError(RuntimeError):
    """The test holds at the fresh-collection boundary instead of making a provider call."""


@pytest.mark.parametrize("retained", ["prepared", "cursor"])
@pytest.mark.parametrize("change", ["same", "client", "backend"])
async def test_coordinator_recovery_fences_configured_authentication(
    monkeypatch: pytest.MonkeyPatch, retained: str, change: str
) -> None:
    async with _database() as (store, _unused_attempt, _unused_context):
        config = InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example.invalid/unused",
                "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
                "FDAI_INVENTORY_SOURCES": "arg",
            }
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("no HTTP"))
        ) as client:

            def build(client_id: str, *, cli: bool = False) -> InventorySource:
                identity = (
                    AsyncAzureCliWorkloadIdentity(
                        credential=AzureCliWorkloadIdentity(subscription_id=config.scopes[0])
                    )
                    if cli
                    else ManagedIdentityWorkloadIdentity(
                        http_client=client,
                        config=ManagedIdentityWorkloadIdentityConfig(
                            endpoint="https://identity.example.invalid/token",
                            header="synthetic-header",
                            client_id=client_id,
                        ),
                    )
                )
                return build_sources(
                    config=config,
                    vocabulary=load_resource_type_registry(),
                    resource_types=("resource-group",),
                    identity=identity,
                    http_client=client,
                    started_at=datetime.now(UTC),
                )[0]

            original = build("00000000-0000-0000-0000-000000000001")
            current = build(
                "00000000-0000-0000-0000-000000000002"
                if change == "client"
                else "00000000-0000-0000-0000-000000000001",
                cli=change == "backend",
            )
        context = collection_context_digest(original.manifest)
        assert (context == collection_context_digest(current.manifest)) == (change == "same")
        attempt = await store.begin(original.manifest)
        resource = ResourceRecord("retained", "resource-group")
        await store.stage_chunk(
            attempt,
            InventoryBatch(resources=(resource,), cursor="retained-cursor"),
            context_digest=context,
            sequence=0,
            previous_digest=None,
        )
        if retained == "prepared":
            recorded_at = datetime.now(UTC)
            observation = PromotedInventoryObservation(
                generation=attempt,
                resources=(resource,),
                links=(),
                complete=True,
                recorded_at=recorded_at,
            )
            manifest = replace(
                original.manifest,
                completed_at=recorded_at,
                metadata={
                    **original.manifest.metadata,
                    "projection_complete": True,
                    "prepared_candidate_required": True,
                    "derived_source_states": [],
                    "relationship_coverage": compute_relationship_coverage(
                        observation
                    ).to_metadata(),
                },
            )
            await seal_candidate(
                store._config,
                source_manifest=original.manifest,
                manifest=manifest,
                observation=observation,
            )

        reads: list[str] = []

        class ReplayInventory:
            async def full_snapshot(
                self, since: str | None = None
            ) -> AsyncIterator[InventoryBatch]:
                reads.append("complete-source-replay")
                yield InventoryBatch(resources=(resource,))
                yield InventoryBatch(final=True)

        class Lock:
            distributed = False

            @asynccontextmanager
            async def acquire(self, resource_id: str) -> AsyncIterator[None]:
                yield

        begin = AsyncMock(
            side_effect=RecollectionRequiredError("configured source requires fresh collection")
        )
        promote = AsyncMock()
        monkeypatch.setattr(store, "begin", begin)
        monkeypatch.setattr(store, "promote", promote)
        coordinator = InventorySyncCoordinator(
            store=store,
            candidate_loader=partial(load_prepared_candidate, store._config),
            collection_loader=partial(load_unfinished_collection, store._config),
            run_lock=Lock(),
        )
        source = InventorySource(current.name, ReplayInventory(), current.manifest)
        if change != "same":
            with pytest.raises(RecollectionRequiredError):
                await coordinator.run((source,))
            begin.assert_awaited_once_with(current.manifest)
            promote.assert_not_awaited()
            assert reads == []
        else:
            result = await coordinator.run((source,))
            assert result.attempt_id == attempt
            begin.assert_not_awaited()
            assert promote.await_args is not None
            assert promote.await_args.args[0] == attempt
            assert reads == ([] if retained == "prepared" else ["complete-source-replay"])

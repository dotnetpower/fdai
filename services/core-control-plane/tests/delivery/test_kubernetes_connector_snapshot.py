"""The actual spool, atomic inbox and inventory adapter retain one evidence identity."""

import json
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.kubernetes_api_status import KubernetesApiInventoryError
from fdai.delivery.kubernetes_connector_snapshot import (
    ConnectorInventorySource,
    ConnectorSnapshotInbox,
)
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.kubernetes_inventory import KubernetesInventoryEnricher
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing import InMemoryStateStore

from .test_kubernetes_connector_spool import NOW, REVISION, registration, snapshot


class Registrations:
    def __init__(self):
        self.registration = registration()

    async def read(self, principal_ref):
        return self.registration if principal_ref == "example" else None


async def test_spool_to_atomic_inbox_to_inventory_source(tmp_path) -> None:
    store = InMemoryStateStore()
    registrations = Registrations()
    outbox = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
    )
    pending = await outbox.enqueue(
        snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
    )
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
    )
    receipt = await inbox.accept(pending.evidence, pending.content, principal_ref="example")
    assert await ConnectorInventorySource(inbox, principal_ref="example").collect() == snapshot()
    assert (
        await inbox.accept(pending.evidence, pending.content, principal_ref="example")
    ).status == "duplicate"
    assert len(list(store.audit_entries)) == 1
    await outbox.acknowledge(receipt)
    assert await outbox.oldest() is None
    promoted = await KubernetesInventoryEnricher(
        source=ConnectorInventorySource(inbox, principal_ref="example"),
        relationship_mapping_catalog=load_provider_relationship_mapping_catalog(
            Path("rule-catalog/vocabulary/provider-relationship-mappings")
        ),
    ).enrich(
        PromotedInventoryObservation(
            generation="example",
            resources=(
                ResourceRecord("cluster-example", "kubernetes-cluster", {"name": "example"}),
            ),
            links=(),
            complete=True,
            relationship_drops=(),
            recorded_at=NOW,
        )
    )
    assert len(promoted.resources) == 2
    assert promoted.source_states[-1].status.value == "available"
    assert len(promoted.links) == 1
    assert promoted.links[0].observation_metadata.verified is True
    registrations.registration = registration().model_copy(update={"revoked": True})
    with pytest.raises(KubernetesApiInventoryError):
        await ConnectorInventorySource(inbox, principal_ref="example").collect()


async def test_inventory_job_composes_connector_source_from_environment(
    tmp_path, monkeypatch
) -> None:
    from fdai.delivery import inventory_sync_cli as cli
    from fdai.delivery.inventory_job_config import InventoryJobConfig

    registration_path = tmp_path / "registrations.json"
    registration_path.write_text(json.dumps([registration().model_dump(mode="json")]))
    registration_path.chmod(0o600)
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
            "FDAI_KUBERNETES_CONNECTOR_REGISTRATION_PATH": str(registration_path),
            "FDAI_KUBERNETES_CONNECTOR_PRINCIPAL_REF": "example",
        }
    )
    store = InMemoryStateStore()
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **kwargs: store)
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(now=lambda timezone: NOW))
    outbox = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
    )
    pending = await outbox.enqueue(
        snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
    )
    inbox = ConnectorSnapshotInbox(
        store, registrations=Registrations(), allow_cluster_resources=False, now=lambda: NOW
    )
    await inbox.accept(pending.evidence, pending.content, principal_ref="example")
    async with AsyncExitStack() as stack:
        enricher = await cli._build_kubernetes_enricher(
            config=config,
            relationship_catalog=load_provider_relationship_mapping_catalog(
                Path("rule-catalog/vocabulary/provider-relationship-mappings")
            ),
            stack=stack,
        )
        result = await enricher.enrich(
            PromotedInventoryObservation(
                generation="example",
                resources=(
                    ResourceRecord("cluster-example", "kubernetes-cluster", {"name": "example"}),
                ),
                links=(),
                complete=True,
                relationship_drops=(),
                recorded_at=NOW,
            )
        )
    assert result.source_states[-1].status.value == "available"
    assert len(result.resources) == 2
    assert result.links[0].observation_metadata.verified is True


async def test_stale_original_clock_and_forged_principal_do_not_promote(tmp_path) -> None:
    store = InMemoryStateStore()
    registrations = Registrations()
    clock = [NOW]
    outbox = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
    )
    pending = await outbox.enqueue(
        snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
    )
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: clock[0]
    )
    with pytest.raises(ValueError):
        await inbox.accept(pending.evidence, pending.content, principal_ref="foreign")
    assert list(store.audit_entries) == []
    await inbox.accept(pending.evidence, pending.content, principal_ref="example")
    clock[0] += timedelta(minutes=5)
    with pytest.raises(KubernetesApiInventoryError):
        await ConnectorInventorySource(inbox, principal_ref="example").collect()

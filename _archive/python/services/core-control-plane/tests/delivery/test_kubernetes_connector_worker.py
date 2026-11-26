"""A lost acknowledgment reuses the durable packet before any new provider collection."""

import asyncio
from datetime import timedelta

import pytest
from fdai.delivery.kubernetes_connector_snapshot import ConnectorSnapshotInbox
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool
from fdai.delivery.kubernetes_connector_worker import ConnectorObserverWorker
from fdai.shared.providers.testing import InMemoryStateStore

from .test_kubernetes_connector_snapshot import Registrations
from .test_kubernetes_connector_spool import NOW, REVISION, registration, snapshot


class Source:
    def __init__(self):
        self.calls = 0

    async def collect(self):
        self.calls += 1
        return snapshot()


class Sender:
    def __init__(self, inbox):
        self.inbox = inbox
        self.lose_ack = True

    async def send_snapshot(self, packet, content, *, allow_cluster_resources):
        receipt = await self.inbox.accept(packet, content, principal_ref="example")
        if self.lose_ack:
            self.lose_ack = False
            raise ConnectionError("synthetic lost acknowledgment")
        return receipt


async def test_lost_ack_restart_does_not_recollect_or_duplicate_audit(tmp_path) -> None:
    source, store, registrations = Source(), InMemoryStateStore(), Registrations()
    inbox = ConnectorSnapshotInbox(
        store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
    )
    sender = Sender(inbox)

    def worker():
        return ConnectorObserverWorker(
            source=source,
            spool=ConnectorSnapshotSpool(
                tmp_path / "spool",
                registration=registration(),
                stream_id="example",
                allow_cluster_resources=False,
            ),
            sender=sender,
            registrations=registrations,
            principal_ref="example",
            producer_revision=REVISION,
            allow_cluster_resources=False,
            now=lambda: NOW,
        )

    with pytest.raises(ConnectionError):
        await worker().run_once()
    assert source.calls == 1
    assert (await worker().run_once()).status == "duplicate"
    assert source.calls == 1
    assert len(list(store.audit_entries)) == 1
    assert (await worker().run_once()).sequence == 2
    assert source.calls == 2


async def test_stale_pending_blocks_without_eviction_or_recollection(tmp_path) -> None:
    source, store, registrations = Source(), InMemoryStateStore(), Registrations()
    spool = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
    )
    pending = await spool.enqueue(
        snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
    )
    worker = ConnectorObserverWorker(
        source=source,
        spool=spool,
        sender=Sender(
            ConnectorSnapshotInbox(
                store, registrations=registrations, allow_cluster_resources=False, now=lambda: NOW
            )
        ),
        registrations=registrations,
        principal_ref="example",
        producer_revision=REVISION,
        allow_cluster_resources=False,
        now=lambda: NOW + timedelta(minutes=5),
    )
    with pytest.raises(ValueError, match="stale"):
        await worker.run_once()
    assert source.calls == 0
    assert await spool.oldest() == pending
    assert list(store.audit_entries) == []


async def test_cancelled_transfer_keeps_pending_packet(tmp_path) -> None:
    class CancelledSender:
        async def send_snapshot(self, packet, content, *, allow_cluster_resources):
            raise asyncio.CancelledError

    source, registrations = Source(), Registrations()
    spool = ConnectorSnapshotSpool(
        tmp_path / "spool",
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
    )
    worker = ConnectorObserverWorker(
        source=source,
        spool=spool,
        sender=CancelledSender(),
        registrations=registrations,
        principal_ref="example",
        producer_revision=REVISION,
        allow_cluster_resources=False,
        now=lambda: NOW,
    )
    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    assert (await spool.oldest()).evidence.sequence == 1
    assert source.calls == 1

"""Real SQLite persistence, restart and capacity tests for the snapshot outbox."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventorySnapshot,
    kubernetes_resource_id,
)
from fdai.delivery.kubernetes_connector import ConnectorAdmissionReceipt, ConnectorAdmissionStatus
from fdai.delivery.kubernetes_connector_spool import ConnectorSnapshotSpool, ConnectorSpoolError
from fdai.shared.providers.inventory import ResourceRecord
from fdai_service_contracts.cluster_connector import ConnectorRegistration

NOW = datetime(2026, 9, 19, tzinfo=UTC)
REVISION = "sha256:" + "a" * 64


def registration() -> ConnectorRegistration:
    return ConnectorRegistration.model_validate(
        {
            "scope": {
                "deployment_ref": "example",
                "cluster_ref": "cluster-example",
                "connector_id": "example",
                "enrollment_revision": 1,
            },
            "principal_ref": "example",
            "role": "observer",
            "namespaces": ["example"],
            "capabilities": ["inventory.snapshot"],
            "valid_from": NOW - timedelta(minutes=1),
            "expires_at": NOW + timedelta(hours=1),
        }
    )


def snapshot() -> KubernetesApiInventorySnapshot:
    identity = kubernetes_resource_id(
        cluster_ref="cluster-example",
        resource_type="kubernetes.namespace",
        uid="namespace-example",
        namespace=None,
    )
    return KubernetesApiInventorySnapshot(
        (
            ResourceRecord(
                identity,
                "kubernetes.namespace",
                {
                    "api_version": "v1",
                    "kind": "Namespace",
                    "cluster_ref": "cluster-example",
                    "name": "example",
                    "namespace": "example",
                    "uid": "namespace-example",
                    "resource_version": "1",
                },
                "kubernetes-uid:namespace-example",
                NOW.isoformat(),
            ),
        ),
        NOW,
    )


def spool(directory: Path, **kwargs) -> ConnectorSnapshotSpool:
    return ConnectorSnapshotSpool(
        directory,
        registration=registration(),
        stream_id="example",
        allow_cluster_resources=False,
        **kwargs,
    )


async def queue(store: ConnectorSnapshotSpool):
    return await store.enqueue(
        snapshot(), registration=registration(), producer_revision=REVISION, now=NOW
    )


async def test_restart_replays_and_ack_preserves_sequence(tmp_path: Path) -> None:
    directory = tmp_path / "spool"
    first = await queue(spool(directory))
    restarted = spool(directory)
    assert await restarted.oldest() == first
    await restarted.acknowledge(
        ConnectorAdmissionReceipt(ConnectorAdmissionStatus.ACCEPTED, first.evidence.digest, 1)
    )
    assert await restarted.oldest() is None
    assert (await queue(spool(directory))).evidence.sequence == 2
    assert (directory.stat().st_mode & 0o777) == 0o700
    assert ((directory / "snapshots.sqlite3").stat().st_mode & 0o777) == 0o600


async def test_capacity_never_evicts_or_advances_sequence(tmp_path: Path) -> None:
    store = spool(tmp_path / "spool", max_items=1)
    first = await queue(store)
    with pytest.raises(ConnectorSpoolError, match="capacity"):
        await queue(store)
    assert await store.oldest() == first
    await store.acknowledge(
        ConnectorAdmissionReceipt(ConnectorAdmissionStatus.DUPLICATE, first.evidence.digest, 1)
    )
    assert (await queue(store)).evidence.sequence == 2


async def test_wrong_ack_and_wrong_stream_are_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "spool"
    first = await queue(spool(directory))
    with pytest.raises(ConnectorSpoolError):
        await spool(directory).acknowledge(
            ConnectorAdmissionReceipt(ConnectorAdmissionStatus.ACCEPTED, REVISION, 1)
        )
    other = ConnectorSnapshotSpool(
        directory, registration=registration(), stream_id="other", allow_cluster_resources=False
    )
    with pytest.raises(ConnectorSpoolError, match="different"):
        await other.oldest()
    assert await spool(directory).oldest() == first


async def test_concurrent_enqueues_allocate_unique_sequences(tmp_path: Path) -> None:
    directory = tmp_path / "spool"
    results = await asyncio.gather(*(queue(spool(directory)) for _ in range(8)))
    assert sorted(item.evidence.sequence for item in results) == list(range(1, 9))


async def test_unsafe_directory_and_byte_capacity_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    with pytest.raises(ConnectorSpoolError, match="owner-only"):
        await queue(spool(directory))
    with pytest.raises(ConnectorSpoolError, match="capacity"):
        await queue(spool(tmp_path / "small", max_bytes=1))


async def test_boolean_acknowledgment_cannot_delete_sequence_one(tmp_path: Path) -> None:
    store = spool(tmp_path / "spool")
    first = await queue(store)
    with pytest.raises(ConnectorSpoolError):
        await store.acknowledge(
            ConnectorAdmissionReceipt(
                ConnectorAdmissionStatus.ACCEPTED, first.evidence.digest, True
            )
        )
    assert await store.oldest() == first

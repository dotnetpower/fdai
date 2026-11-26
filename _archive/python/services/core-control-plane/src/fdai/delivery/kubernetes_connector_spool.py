"""Owner-only bounded SQLite outbox for one registered snapshot stream."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai_service_contracts.cluster_connector import ConnectorEvidence, ConnectorRegistration
from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot
from fdai.delivery.kubernetes_connector import ConnectorAdmissionReceipt
from fdai.delivery.kubernetes_connector_artifact import (
    artifact_digest,
    decode_snapshot,
    snapshot_bytes,
)


class ConnectorSpoolError(RuntimeError):
    """Fail closed on capacity, identity, integrity or local persistence failure."""


@dataclass(frozen=True, slots=True)
class PendingSnapshot:
    evidence: ConnectorEvidence
    content: bytes


class ConnectorSnapshotSpool:
    """Durably queue validated snapshots before transmitting any bytes.

    A directory is bound to one enrollment and stream. Full buffers reject new evidence;
    they never silently evict unsent data or reset a stream. The worker supplies a current
    registration on every enqueue; this local store does not authenticate a principal.
    """

    def __init__(
        self,
        directory: Path,
        *,
        registration: ConnectorRegistration,
        stream_id: str,
        allow_cluster_resources: bool,
        max_bytes: int = 67_108_864,
        max_items: int = 32,
    ) -> None:
        if type(max_bytes) is not int or not 1 <= max_bytes <= 268_435_456:
            raise ValueError("connector spool byte bound is invalid")
        if type(max_items) is not int or not 1 <= max_items <= 256:
            raise ValueError("connector spool item bound is invalid")
        self._directory = directory
        self._registration = ConnectorRegistration.model_validate_json(
            registration.model_dump_json()
        )
        self._stream_id = stream_id
        self._allow_cluster_resources = allow_cluster_resources
        self._max_bytes = max_bytes
        self._max_items = max_items
        self._binding = canonical_digest(
            {
                "scope": registration.scope.model_dump(mode="json"),
                "stream_id": stream_id,
                "namespaces": list(registration.namespaces),
                "cluster_resources": allow_cluster_resources,
            }
        )

    async def enqueue(
        self,
        snapshot: KubernetesApiInventorySnapshot,
        *,
        registration: ConnectorRegistration,
        producer_revision: str,
        now: datetime,
    ) -> PendingSnapshot:
        """Allocate the sequence and append the validated packet in one transaction."""
        content = snapshot_bytes(snapshot)
        if (
            registration.scope != self._registration.scope
            or registration.namespaces != self._registration.namespaces
        ):
            raise ConnectorSpoolError(
                "connector spool registration changed; use an approved new stream"
            )
        template = ConnectorEvidence(
            scope=registration.scope,
            capability="inventory.snapshot",
            stream_id=self._stream_id,
            sequence=1,
            observed_at=snapshot.observed_at,
            producer_revision=producer_revision,
            artifact_digest=artifact_digest(content),
            artifact_bytes=len(content),
            namespaces=registration.namespaces,
            complete=True,
        )
        template.admit(
            registration, principal_ref=registration.principal_ref, now=now, max_age_seconds=3600
        )
        decode_snapshot(content, template, allow_cluster_resources=self._allow_cluster_resources)
        return await asyncio.to_thread(self._enqueue, template, content)

    async def oldest(self) -> PendingSnapshot | None:
        """Read the oldest packet without consuming it; replay preserves its original clock."""
        return await asyncio.to_thread(self._oldest)

    async def acknowledge(self, receipt: ConnectorAdmissionReceipt) -> None:
        """Remove only an exact accepted packet, preserving later packets and sequence state."""
        if type(receipt.sequence) is not int or receipt.sequence < 1:
            raise ConnectorSpoolError(
                "connector acknowledgment sequence must be a positive integer"
            )
        await asyncio.to_thread(self._acknowledge, receipt)

    def _connect(self) -> sqlite3.Connection:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self._directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ConnectorSpoolError("connector spool requires an owner-only directory")
        path = self._directory / "snapshots.sqlite3"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            file_info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_info.st_mode)
                or file_info.st_uid != os.getuid()
                or stat.S_IMODE(file_info.st_mode) != 0o600
                or file_info.st_nlink != 1
            ):
                raise ConnectorSpoolError("connector spool requires an owner-only regular database")
        finally:
            os.close(descriptor)
        connection = sqlite3.connect(path, timeout=3)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA max_page_count=131072")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS binding "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "digest TEXT NOT NULL, sequence INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pending (sequence INTEGER PRIMARY KEY, "
                "digest TEXT NOT NULL UNIQUE, envelope TEXT NOT NULL, content BLOB NOT NULL)"
            )
            connection.execute("INSERT OR IGNORE INTO binding VALUES (1, ?, 0)", (self._binding,))
            row = connection.execute("SELECT digest FROM binding WHERE singleton=1").fetchone()
            if row is None or row[0] != self._binding:
                raise ConnectorSpoolError(
                    "connector spool belongs to a different registered stream"
                )
            return connection
        except BaseException:
            connection.close()
            raise

    def _enqueue(self, template: ConnectorEvidence, content: bytes) -> PendingSnapshot:
        connection = self._connect()
        try:
            count, size = connection.execute(
                "SELECT count(*), coalesce(sum(length(content) + length(envelope)), 0) FROM pending"
            ).fetchone()
            sequence = (
                connection.execute("SELECT sequence FROM binding WHERE singleton=1").fetchone()[0]
                + 1
            )
            packet = ConnectorEvidence.model_validate(
                {**template.model_dump(), "sequence": sequence}
            )
            envelope = packet.model_dump_json()
            if (
                count >= self._max_items
                or size + len(content) + len(envelope.encode()) > self._max_bytes
            ):
                raise ConnectorSpoolError(
                    "connector spool capacity exceeded; evidence was not queued"
                )
            connection.execute(
                "INSERT INTO pending VALUES (?, ?, ?, ?)",
                (sequence, packet.digest, envelope, content),
            )
            connection.execute("UPDATE binding SET sequence=? WHERE singleton=1", (sequence,))
            connection.commit()
            return PendingSnapshot(packet, content)
        finally:
            connection.close()

    def _oldest(self) -> PendingSnapshot | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT sequence, digest, envelope, content FROM pending ORDER BY sequence LIMIT 1"
            ).fetchone()
            connection.commit()
            if row is None:
                return None
            packet = ConnectorEvidence.model_validate_json(row[2])
            if (
                packet.digest != row[1]
                or packet.sequence != row[0]
                or packet.scope != self._registration.scope
                or packet.stream_id != self._stream_id
                or packet.namespaces != self._registration.namespaces
            ):
                raise ConnectorSpoolError("connector spool packet failed integrity validation")
            content = bytes(row[3])
            decode_snapshot(content, packet, allow_cluster_resources=self._allow_cluster_resources)
            return PendingSnapshot(packet, content)
        finally:
            connection.close()

    def _acknowledge(self, receipt: ConnectorAdmissionReceipt) -> None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT sequence, digest FROM pending ORDER BY sequence LIMIT 1"
            ).fetchone()
            if (
                row is None
                or row != (receipt.sequence, receipt.evidence_digest)
                or receipt.status not in ("accepted", "duplicate")
            ):
                raise ConnectorSpoolError(
                    "connector acknowledgment does not match the oldest packet"
                )
            connection.execute("DELETE FROM pending WHERE sequence=? AND digest=?", row)
            connection.commit()
        finally:
            connection.close()

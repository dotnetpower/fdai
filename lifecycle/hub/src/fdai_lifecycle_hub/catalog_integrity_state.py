"""Durable anti-rollback state for TUF catalog roles.

The table is an optional-feature table: it is created by the explicit `bind-catalog` command when
a Hub is bound with `catalog.trust` mode `tuf`, it never moves the Hub schema revision, and an
older binary simply never reads it. Legacy single-key Hubs do not use it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fdai_deployment_cli.lifecycle_catalog_roles import root_from_wire, root_to_wire
from sqlalchemy import Column, Integer, LargeBinary, MetaData, String, Table, Text, inspect, select
from sqlalchemy.engine import Connection, RowMapping

from fdai_lifecycle_hub.catalog_integrity import (
    IntegrityAssessment,
    IntegrityFloors,
    advanced_floors,
    verified_records,
)

metadata = MetaData()
integrity_state = Table(
    "catalog_integrity_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("root_version", Integer, nullable=False),
    Column("root_digest", String(64)),
    Column("root_payload", LargeBinary),
    Column("snapshot_version", Integer, nullable=False),
    Column("snapshot_digest", String(64)),
    Column("snapshot_expires_at", String(40)),
    Column("timestamp_version", Integer, nullable=False),
    Column("timestamp_digest", String(64)),
    Column("timestamp_expires_at", String(40)),
    Column("max_recall_sequence", Integer, nullable=False),
    Column("channel_versions", Text),
    Column("observed_at", String(40)),
    Column("result", Text),
)


def ensure_integrity_state(connection: Connection) -> None:
    """Create the optional table and its single row. Idempotent."""

    integrity_state.create(connection, checkfirst=True)
    if connection.scalar(select(integrity_state.c.id)) is None:
        connection.execute(
            integrity_state.insert().values(
                id=1,
                root_version=0,
                snapshot_version=0,
                timestamp_version=0,
                max_recall_sequence=0,
            )
        )


def read_integrity(connection: Connection, *, lock: bool = False) -> RowMapping:
    if not inspect(connection).has_table(integrity_state.name):
        raise ValueError("Catalog integrity state is not bound; run explicit bind-catalog.")
    query = select(integrity_state).where(integrity_state.c.id == 1)
    row = connection.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if row is None:
        raise ValueError("Catalog integrity state is not bound; run explicit bind-catalog.")
    return row


def floors_of(row: RowMapping) -> IntegrityFloors:
    return IntegrityFloors(
        root_version=row["root_version"],
        root_digest=row["root_digest"],
        snapshot_version=row["snapshot_version"],
        snapshot_digest=row["snapshot_digest"],
        timestamp_version=row["timestamp_version"],
        timestamp_digest=row["timestamp_digest"],
        max_recall_sequence=row["max_recall_sequence"],
        channel_versions=json.loads(row["channel_versions"] or "{}"),
    )


def accepted_root(row: RowMapping) -> Any:
    """The newest root this Hub accepted, or None before the first verified observation."""

    if row["root_payload"] is None:
        return None
    return root_from_wire(json.loads(row["root_payload"]))


def persist(
    connection: Connection,
    assessment: IntegrityAssessment,
    *,
    now: datetime,
    accept_rotation: bool = False,
) -> None:
    """Advance the floors to a verified assessment inside the caller's transaction.

    A rotation advances the persisted root only when a person reviewed it. The check repeats
    under the row lock, so a concurrent poll can never move any floor backwards.
    """

    row = read_integrity(connection, lock=True)
    current = floors_of(row)
    target = advanced_floors(assessment)
    root, snapshot, timestamp = verified_records(assessment)
    if (
        target.root_version < current.root_version
        or target.snapshot_version < current.snapshot_version
        or target.timestamp_version < current.timestamp_version
        or target.max_recall_sequence < current.max_recall_sequence
    ):
        raise ValueError("Catalog integrity floors moved during the check.")
    if current.root_version and root.version > current.root_version and not accept_rotation:
        raise ValueError("A root rotation needs review before its floors can advance.")
    connection.execute(
        integrity_state.update()
        .where(integrity_state.c.id == 1)
        .values(
            root_version=target.root_version,
            root_digest=target.root_digest,
            root_payload=json.dumps(
                root_to_wire(root), sort_keys=True, separators=(",", ":")
            ).encode(),
            snapshot_version=target.snapshot_version,
            snapshot_digest=target.snapshot_digest,
            snapshot_expires_at=snapshot.expires_at.isoformat(),
            timestamp_version=target.timestamp_version,
            timestamp_digest=target.timestamp_digest,
            timestamp_expires_at=timestamp.expires_at.isoformat(),
            max_recall_sequence=target.max_recall_sequence,
            channel_versions=json.dumps(dict(target.channel_versions), sort_keys=True),
            observed_at=now.isoformat(),
            result=json.dumps(assessment.to_json(), sort_keys=True),
        )
    )


def record_result(connection: Connection, result: dict[str, Any], *, now: datetime) -> None:
    """Remember the latest observation for display without touching any floor."""

    read_integrity(connection, lock=True)
    connection.execute(
        integrity_state.update()
        .where(integrity_state.c.id == 1)
        .values(observed_at=now.isoformat(), result=json.dumps(result, sort_keys=True))
    )


def public_state(row: RowMapping) -> dict[str, Any]:
    """Operator-visible floors and the last observation."""

    return {
        "mode": "tuf",
        "root_version": row["root_version"],
        "snapshot_version": row["snapshot_version"],
        "snapshot_expires_at": row["snapshot_expires_at"],
        "timestamp_version": row["timestamp_version"],
        "timestamp_expires_at": row["timestamp_expires_at"],
        "max_recall_sequence": row["max_recall_sequence"],
        "observed_at": row["observed_at"],
        "last": json.loads(row["result"]) if row["result"] else None,
    }

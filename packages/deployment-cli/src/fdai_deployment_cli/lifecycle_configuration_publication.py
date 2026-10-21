"""Venue-scoped persistence, not Git review, Hub acceptance or a global publisher lease."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.deployment_kit_cache import acquisition_lock, path_present
from fdai_deployment_cli.lifecycle_configuration_artifact import (
    MAX_CONFIGURATION_ARTIFACT_BYTES,
    configuration_artifact_bytes,
    read_configuration_artifact,
)
from fdai_deployment_cli.lifecycle_configuration_package import SignedConfigurationPackage
from fdai_deployment_cli.lifecycle_configuration_sealing import read_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

MAX_PUBLICATIONS = 256
MAX_PUBLICATION_BYTES = 16 * 1024 * 1024
_DATABASE = "publication.sqlite3"
_FORMAT = "fdai.configuration-publication-state.v1"
_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
Build = Callable[[Sequence[SignedConfigurationPackage]], SignedConfigurationPackage]
Verify = Callable[[Sequence[SignedConfigurationPackage], SignedConfigurationPackage], None]


@dataclass(frozen=True, slots=True)
class Publication:
    venue_id: str
    sequence: int
    revision_id: str
    created_at: str
    package: SignedConfigurationPackage
    artifact: bytes

    @property
    def artifact_name(self) -> str:
        return f"{self.package.digest}.json"

    def receipt(self) -> dict[str, object]:
        value: dict[str, object] = {
            "format": "fdai.configuration-publication-receipt.v1",
            "venue_id": self.venue_id,
            "sequence": self.sequence,
            "revision_id": self.revision_id,
            "predecessor_digest": read_object(self.package.payload)["predecessor_digest"],
            "package_digest": self.package.digest,
            "artifact_digest": hashlib.sha256(self.artifact).hexdigest(),
            "artifact_name": self.artifact_name,
            "created_at": self.created_at,
        }
        return {**value, "receipt_digest": hashlib.sha256(canonical_bytes(value)).hexdigest()}


def _revision_id(value: str) -> str:
    if _REVISION.fullmatch(value) is None:
        raise ValueError("publication revision must be 40 lowercase hexadecimal characters")
    return value


@contextmanager
def _connection(
    venue: Path, *, initial: bool = False, readonly: bool = False
) -> Iterator[sqlite3.Connection]:
    database = venue / _DATABASE
    new = not path_present(database)
    if new:
        if readonly or not initial or any(venue.iterdir()):
            raise ValueError("publication state is absent; preserve the venue for review")
        write_private_bytes(database, b"")
    else:
        snapshot = read_private_bytes(database, max_bytes=2 * MAX_PUBLICATION_BYTES)
        if not snapshot.startswith(b"SQLite format 3\0") or snapshot[18:20] != b"\x01\x01":
            raise ValueError("publication journal storage format is corrupt or unsupported")
    if any(path_present(venue / (_DATABASE + suffix)) for suffix in ("-journal", "-wal", "-shm")):
        raise ValueError(
            "retained publication transaction sidecar requires review, not automatic recovery"
        )
    connection = sqlite3.connect(
        database.as_uri() + "?mode=ro" if readonly else str(database),
        uri=readonly,
        timeout=0.1,
        isolation_level=None,
    )
    deadline = time.monotonic() + 10
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        if new:
            connection.executescript(
                "PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; BEGIN IMMEDIATE;"
                "CREATE TABLE metadata (id INTEGER PRIMARY KEY, format TEXT NOT NULL, venue_id TEXT NOT NULL);"
                "CREATE TABLE packages (sequence INTEGER PRIMARY KEY, revision_id TEXT NOT NULL UNIQUE,"
                "receipt BLOB NOT NULL, artifact BLOB NOT NULL);"
            )
            connection.execute("INSERT INTO metadata VALUES (1, ?, ?)", (_FORMAT, uuid4().hex))
            connection.execute("PRAGMA user_version=1")
            connection.commit()
        if connection.execute("PRAGMA user_version").fetchone() != (1,):
            raise ValueError("unsupported publication journal version")
        if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise ValueError("publication journal integrity check failed")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if tables != {"metadata", "packages"}:
            raise ValueError("publication journal schema is incomplete or unknown")
        for table, columns in (
            ("metadata", ("id", "format", "venue_id")),
            ("packages", ("sequence", "revision_id", "receipt", "artifact")),
        ):
            actual = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))  # noqa: S608
            if actual != columns:
                raise ValueError("publication journal columns are invalid")
        if not readonly:
            connection.execute("PRAGMA synchronous=FULL")
        yield connection
    finally:
        connection.close()


def _load(connection: sqlite3.Connection, venue: Path) -> tuple[str, list[Publication]]:
    metadata = connection.execute("SELECT id, format, venue_id FROM metadata").fetchall()
    if (
        len(metadata) != 1
        or metadata[0][0] != 1
        or metadata[0][1] != _FORMAT
        or not isinstance(metadata[0][2], str)
        or re.fullmatch(r"[0-9a-f]{32}", metadata[0][2]) is None
    ):
        raise ValueError("publication venue binding is invalid")
    venue_id = metadata[0][2]
    count, total, receipt_size = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(length(artifact)),0), COALESCE(MAX(length(receipt)),0) FROM packages"
    ).fetchone()
    if count > MAX_PUBLICATIONS or total > MAX_PUBLICATION_BYTES or receipt_size > 4096:
        raise ValueError("retained publication history exceeds its bound")
    result: list[Publication] = []
    previous: str | None = None
    for expected, row in enumerate(
        connection.execute(
            "SELECT sequence, revision_id, receipt, artifact FROM packages ORDER BY sequence"
        ),
        1,
    ):
        sequence, revision, receipt_bytes, artifact = row
        if (
            sequence != expected
            or not isinstance(revision, str)
            or not isinstance(receipt_bytes, bytes)
            or not isinstance(artifact, bytes)
        ):
            raise ValueError("retained publication identity is invalid")
        _revision_id(revision)
        package = read_configuration_artifact(artifact)
        payload = read_object(package.payload)
        if (
            payload.get("revision_id") != revision
            or "predecessor_digest" not in payload
            or payload["predecessor_digest"] != previous
        ):
            raise ValueError("retained publication chain is incomplete or forked")
        receipt = read_object(receipt_bytes)
        created = receipt.get("created_at")
        if not isinstance(created, str) or datetime.fromisoformat(created).utcoffset() is None:
            raise ValueError("publication receipt time is invalid")
        record = Publication(venue_id, sequence, revision, created, package, artifact)
        if receipt != record.receipt() or canonical_bytes(receipt) != receipt_bytes:
            raise ValueError("publication receipt or artifact digest is inconsistent")
        result.append(record)
        _artifact_state(venue, record, materialize=False)
        previous = package.digest
    expected_names = {_DATABASE} | {r.artifact_name for r in result}
    if any(path.name not in expected_names for path in venue.iterdir()):
        raise ValueError("publication venue contains unbound or orphan artifacts")
    return venue_id, result


def _artifact_state(venue: Path, record: Publication, *, materialize: bool) -> str:
    path = venue / record.artifact_name
    if not path_present(path):
        if not materialize:
            return "missing"
        write_private_bytes(path, record.artifact)
    if read_private_bytes(path, max_bytes=MAX_CONFIGURATION_ARTIFACT_BYTES) != record.artifact:
        raise ValueError("retained publication artifact conflicts; it will not be overwritten")
    return "present"


def publish(
    venue: Path,
    revision_id: str,
    build: Build,
    verify: Verify,
    *,
    initial: bool = False,
    expected_head: str | None = None,
) -> Publication:
    """Trusted callbacks verify complete history and output; historical retry never rewinds it."""
    _revision_id(revision_id)
    if not venue.is_absolute() or initial == (expected_head is not None):
        raise ValueError("select explicit initial publication or retained publication head")
    if expected_head is not None and _SHA256.fullmatch(expected_head) is None:
        raise ValueError("publication head must be a SHA-256 digest")
    with acquisition_lock(venue), _connection(venue, initial=initial) as connection:
        connection.execute("BEGIN IMMEDIATE")
        venue_id, records = _load(connection, venue)
        existing = next((r for r in records if r.revision_id == revision_id), None)
        head = records[-1].package.digest if records else None
        predecessor = (
            read_object(existing.package.payload)["predecessor_digest"] if existing else head
        )
        if initial:
            if records and (existing is None or existing.sequence != 1):
                raise ValueError("initial publication cannot advance retained history")
        elif expected_head not in {head, predecessor}:
            raise ValueError("publication head changed; review retained evidence")
        if existing is None and len(records) >= MAX_PUBLICATIONS:
            raise ValueError("new publication exceeds its count bound")
        if existing is not None and existing.sequence < len(records):
            verify(tuple(r.package for r in records[:-1]), records[-1].package)
            selected = records[: existing.sequence]
        else:
            selected = records
        package = build(tuple(r.package for r in selected))
        if read_object(package.payload).get("revision_id") != revision_id:
            raise ValueError("publication input revision changed during validation")
        if existing is not None:
            if package != existing.package:
                raise ValueError("the revision already has different retained publication bytes")
            record = existing
        else:
            artifact = configuration_artifact_bytes(package)
            if (
                sum(len(r.artifact) for r in records) + len(artifact) > MAX_PUBLICATION_BYTES
                or read_object(package.payload).get("predecessor_digest") != head
            ):
                raise ValueError("new publication exceeds history bounds or forks its head")
            record = Publication(
                venue_id,
                len(records) + 1,
                revision_id,
                datetime.now(UTC).isoformat(),
                package,
                artifact,
            )
            connection.execute(
                "INSERT INTO packages VALUES (?, ?, ?, ?)",
                (record.sequence, revision_id, canonical_bytes(record.receipt()), artifact),
            )
        connection.commit()
        _artifact_state(venue, record, materialize=True)
        return record


def inspect_publication(venue: Path, revision_id: str, verify: Verify) -> tuple[Publication, str]:
    """Verify the entire retained chain with public inputs; never repair or create state."""
    _revision_id(revision_id)
    with acquisition_lock(venue), _connection(venue, readonly=True) as connection:
        _, records = _load(connection, venue)
        if not records:
            raise ValueError("publication history is empty")
        verify(tuple(r.package for r in records[:-1]), records[-1].package)
        record = next((r for r in records if r.revision_id == revision_id), None)
        if record is None:
            raise ValueError("the revision has no retained publication")
        return record, _artifact_state(venue, record, materialize=False)

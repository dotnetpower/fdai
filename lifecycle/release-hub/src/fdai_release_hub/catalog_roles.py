"""Vendor-side TUF roles: install a signed root, then serve snapshot and timestamp metadata.

The root is signed offline by a threshold of keys that never enter this process or its database.
Only the snapshot and timestamp keys are online, and they are separate from each other and from
the export key. A root names them, so a root rotation can retire any online key.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from fdai_deployment_cli.lifecycle_catalog_integrity import (
    MAX_ROOT_CHAIN_LENGTH,
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
)
from fdai_deployment_cli.lifecycle_catalog_roles import (
    CatalogRootChainError,
    root_from_wire,
    root_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    timestamp_from_wire,
    timestamp_to_wire,
    verify_root_chain,
)
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError, ProgrammingError

from fdai_lifecycle_hub.catalog_integrity import release_digest
from fdai_lifecycle_hub.catalog_trust import MetadataBundle, OnlineRoleKey, role_verifier
from fdai_release_hub.catalog_serialization import CatalogError
from fdai_release_hub.role_tables import catalog_role_state, catalog_roots, role_metadata

MAX_ROOT_BYTES = 64 * 1024
NOT_INSTALLED = "Catalog roles are not installed."


@dataclass(frozen=True, slots=True)
class CatalogRoleKeys:
    """The online keys and validity windows. Zero-trust defaults: short timestamp, long root."""

    snapshot: OnlineRoleKey
    timestamp: OnlineRoleKey
    timestamp_ttl: timedelta = timedelta(hours=24)
    snapshot_ttl: timedelta = timedelta(days=7)

    def __post_init__(self) -> None:
        if self.snapshot.key_id == self.timestamp.key_id:
            raise ValueError("Snapshot and timestamp keys MUST be different keys.")
        if not timedelta(hours=1) <= self.timestamp_ttl <= timedelta(days=7):
            raise ValueError("The timestamp validity MUST be between one hour and seven days.")
        if not self.timestamp_ttl <= self.snapshot_ttl <= timedelta(days=60):
            raise ValueError("The snapshot validity MUST outlast the timestamp and stay bounded.")


@dataclass(frozen=True, slots=True)
class SnapshotContent:
    """What a snapshot binds. Built only when a new snapshot must be signed."""

    export_digest: str
    export_revision: int
    channel_versions: Mapping[str, int]
    recall_count: int
    release_digests: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SignedMetadata:
    """Exact metadata bytes and their digest, cached by the state that produced them."""

    raw: bytes
    digest: str
    timestamp_version: int


def snapshot_content(raw: bytes, digest: str) -> SnapshotContent:
    """Derive the snapshot binding from the exact export bytes, so they cannot disagree.

    Every channel listing is versioned by the catalog revision that produced it, which only
    ever increases. Recall ordinals count the recall events in the export in order.
    """

    document = json.loads(raw)
    return SnapshotContent(
        export_digest=digest,
        export_revision=document["revision"],
        channel_versions=dict.fromkeys(document["channels"], document["revision"]),
        recall_count=len(document["recalls"]),
        release_digests={
            release_id: release_digest(artifact["manifest"])
            for release_id, artifact in document["releases"].items()
        },
    )


def _begin(db: Connection) -> None:
    if db.dialect.name == "sqlite":
        db.exec_driver_sql("BEGIN IMMEDIATE")


class CatalogRoleService:
    def __init__(
        self,
        engine: Engine,
        keys: CatalogRoleKeys,
        *,
        export_key_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.engine, self.keys, self.export_key_id, self.clock = engine, keys, export_key_id, clock
        self._lock = threading.Lock()
        self._cache: tuple[tuple[str, int, int, int], SignedMetadata] | None = None

    def install_root(self, raw: bytes, *, actor: str) -> dict[str, Any]:
        """Install the next signed root. Rotation needs a threshold of the previous keys.

        The root must authorize this process's online keys and export key, so installing it can
        never leave the Hub unable to sign. Private root keys are never required here.
        """

        if not actor.strip() or len(actor) > 160:
            raise CatalogError("An attributed operator is required.")
        if len(raw) > MAX_ROOT_BYTES:
            raise CatalogError("The signed root is too large.")
        try:
            root = root_from_wire(json.loads(raw))
        except (ValueError, TypeError, RecursionError):
            raise CatalogError("The signed root is malformed.") from None
        self._authorize(root)
        now = self.clock()
        with self.engine.begin() as db:
            _begin(db)
            role_metadata.create_all(db, checkfirst=True)
            installed = self._roots(db)
            if len(installed) >= MAX_ROOT_CHAIN_LENGTH:
                raise CatalogError("The root chain is at its length limit.", 409)
            first = installed[0] if installed else root
            try:
                verify_root_chain(
                    [*installed, root],
                    pinned_root_key_ids=first.root_key_ids,
                    pinned_threshold=first.threshold,
                    make_verifier=role_verifier,
                )
            except CatalogRootChainError as error:
                raise CatalogError(
                    f"The signed root is not acceptable: {error.reason_code}"
                ) from None
            if now >= root.expires_at:
                raise CatalogError("The signed root is already expired.")
            db.execute(
                catalog_roots.insert().values(
                    version=root.version,
                    payload=json.dumps(root_to_wire(root), sort_keys=True, separators=(",", ":")),
                    digest=hashlib.sha256(root.canonical_payload()).hexdigest(),
                    installed_at=now.isoformat(),
                    actor=actor,
                )
            )
            if db.scalar(select(func.count()).select_from(catalog_role_state)):
                db.execute(catalog_role_state.update().values(root_version=root.version))
            else:
                db.execute(
                    catalog_role_state.insert().values(
                        id=1, root_version=root.version, snapshot_version=0, timestamp_version=0
                    )
                )
        self._cache = None
        return {"version": root.version, "expires_at": root.expires_at.isoformat()}

    def _authorize(self, root: CatalogRootRecord) -> None:
        if (
            self.keys.snapshot.key_id not in root.snapshot_key_ids
            or self.keys.timestamp.key_id not in root.timestamp_key_ids
            or self.export_key_id not in root.export_key_ids
        ):
            raise CatalogError(
                "The signed root does not authorize this Hub's snapshot, timestamp or export key.",
                409,
            )

    @staticmethod
    def _roots(db: Connection) -> list[CatalogRootRecord]:
        rows = db.execute(select(catalog_roots.c.payload).order_by(catalog_roots.c.version))
        return [root_from_wire(json.loads(payload)) for (payload,) in rows]

    def _probe(self) -> tuple[int, int, int]:
        try:
            with self.engine.connect() as db:
                row = db.execute(
                    select(
                        catalog_role_state.c.root_version,
                        catalog_role_state.c.snapshot_version,
                        catalog_role_state.c.timestamp_version,
                    )
                ).one_or_none()
        except (OperationalError, ProgrammingError):
            with self.engine.connect() as db:
                if inspect(db).has_table(catalog_role_state.name):
                    raise
            raise CatalogError(NOT_INSTALLED, 503) from None
        if row is None:
            raise CatalogError(NOT_INSTALLED, 503)
        return int(row[0]), int(row[1]), int(row[2])

    def installed(self) -> bool:
        """Whether a signed root exists. Without one the Hub serves only the legacy export."""

        try:
            self._probe()
        except CatalogError as error:
            if str(error) == NOT_INSTALLED:
                return False
            raise
        return True

    def served(self, export_digest: str, content: Callable[[], SnapshotContent]) -> SignedMetadata:
        """Serve the current metadata, signing only when the catalog or the roles changed.

        A request storm costs one small state query. Signing needs a new export digest, a missing
        or mismatched record, or a snapshot close to expiry, and one lock serializes writers.
        """

        probe = self._probe()
        cached = self._cache
        if cached is not None and cached[0] == (export_digest, *probe):
            return cached[1]
        with self._lock:
            # A request that waited here finds the state the previous holder just signed.
            cached = self._cache
            if cached is not None and cached[0] == (export_digest, *self._probe()):
                return cached[1]
            return self._refresh(export_digest, content, renew_within=None)

    def renew_if_due(
        self, export_digest: str, content: Callable[[], SnapshotContent], within: timedelta
    ) -> bool:
        """Re-sign only the timestamp when it expires within `within`. Never touches content."""

        before = self._probe()[2]
        with self._lock:
            signed = self._refresh(export_digest, content, renew_within=within)
        return signed.timestamp_version != before

    def _refresh(
        self,
        export_digest: str,
        content: Callable[[], SnapshotContent],
        *,
        renew_within: timedelta | None,
    ) -> SignedMetadata:
        """Build the current bundle in one transaction. The caller holds the process lock."""

        with self.engine.begin() as db:
            _begin(db)
            roots = self._roots(db)
            state = (
                db.execute(select(catalog_role_state).with_for_update()).mappings().one_or_none()
            )
            if not roots or state is None:
                raise CatalogError(NOT_INSTALLED, 503)
            latest, now, keys = roots[-1], self.clock(), self.keys
            try:
                self._authorize(latest)
            except CatalogError:
                raise CatalogError(
                    "The installed root retired this Hub's role keys.", 503
                ) from None
            if now >= latest.expires_at:
                raise CatalogError("The installed root has expired.", 503)
            snapshot = (
                snapshot_from_wire(json.loads(state["snapshot_payload"]))
                if state["snapshot_payload"]
                else None
            )
            timestamp = (
                timestamp_from_wire(json.loads(state["timestamp_payload"]))
                if state["timestamp_payload"]
                else None
            )
            if snapshot is None or (
                snapshot.export_digest != export_digest
                or snapshot.key_id != keys.snapshot.key_id
                or snapshot.expires_at - now <= keys.snapshot_ttl / 3
            ):
                snapshot = self._sign_snapshot(content(), state["snapshot_version"] + 1, now)
                new_snapshot = True
            else:
                new_snapshot = False
            if (
                new_snapshot
                or timestamp is None
                or timestamp.snapshot_version != snapshot.version
                or timestamp.key_id != keys.timestamp.key_id
                or (renew_within is not None and timestamp.expires_at - now <= renew_within)
            ):
                timestamp = self._sign_timestamp(snapshot, state["timestamp_version"] + 1, now)
                new_timestamp = True
            else:
                new_timestamp = False
            if new_snapshot or new_timestamp:
                db.execute(
                    catalog_role_state.update().values(
                        snapshot_version=snapshot.version,
                        snapshot_payload=json.dumps(snapshot_to_wire(snapshot), sort_keys=True),
                        timestamp_version=timestamp.version,
                        timestamp_payload=json.dumps(timestamp_to_wire(timestamp), sort_keys=True),
                    )
                )
            raw = MetadataBundle(tuple(roots), snapshot, timestamp).to_bytes()
            signed = SignedMetadata(raw, hashlib.sha256(raw).hexdigest(), timestamp.version)
            self._cache = (
                (export_digest, latest.version, snapshot.version, timestamp.version),
                signed,
            )
            return signed

    def _sign_snapshot(
        self, content: SnapshotContent, version: int, now: datetime
    ) -> CatalogSnapshotRecord:
        record = CatalogSnapshotRecord(
            version=version,
            channel_versions=dict(content.channel_versions),
            recall_sequences=tuple(range(1, content.recall_count + 1)),
            release_digests=dict(content.release_digests),
            key_id=self.keys.snapshot.key_id,
            signed_at=now,
            expires_at=now + self.keys.snapshot_ttl,
            export_digest=content.export_digest,
            export_revision=content.export_revision,
        )
        return replace(record, signature=self.keys.snapshot.sign(record.canonical_payload()))

    def _sign_timestamp(
        self, snapshot: CatalogSnapshotRecord, version: int, now: datetime
    ) -> CatalogTimestampRecord:
        record = CatalogTimestampRecord(
            version=version,
            snapshot_version=snapshot.version,
            snapshot_digest=snapshot.digest,
            key_id=self.keys.timestamp.key_id,
            signed_at=now,
            expires_at=now + self.keys.timestamp_ttl,
        )
        return replace(record, signature=self.keys.timestamp.sign(record.canonical_payload()))

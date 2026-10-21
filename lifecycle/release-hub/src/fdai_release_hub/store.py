"""Transactional, local development publication. Artifacts are never uploaded or built."""

from __future__ import annotations

import hashlib
from base64 import b64decode, b64encode
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import (
    LIFECYCLE_RELEASE_SCHEMAS,
    LifecycleRelease,
    NginxAcceptanceRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.runtime_release import is_release_id
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.database import (
    catalog_metadata,
    event_actors,
    events,
    membership,
    metadata,
    releases,
)

CHANNELS = ("DEV", "RELEASE_CANDIDATE", "RELEASE")


class CatalogError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class CatalogConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=0)
    confirmation: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=500)


class Change(CatalogConfirmation):
    channel: str | None = None
    label: str = Field(default="", max_length=160)
    manifest: str | None = Field(default=None, max_length=1024 * 1024)


class ReleaseStore:
    def __init__(
        self,
        path: Path | Engine,
        key: HubSigningKey,
        *,
        clock: Callable[[], datetime] | None = None,
        initialize: bool = True,
    ) -> None:
        self.path = path
        self.key = key
        self.clock = clock or (lambda: datetime.now(UTC))
        self.engine = (
            create_engine(f"sqlite:///{path}", poolclass=NullPool)
            if isinstance(path, Path)
            else path
        )
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
                dbapi_connection.execute("PRAGMA foreign_keys = ON")

        if initialize:
            self.migrate()
        else:
            require_schema(self.engine, "release_hub")

    def migrate(self) -> None:
        def initialize(connection: Connection) -> None:
            metadata.create_all(connection)
            if connection.scalar(select(func.count()).select_from(catalog_metadata)) == 0:
                connection.execute(
                    catalog_metadata.insert().values(created_at=self.clock().isoformat())
                )

        migrate(self.engine, "release_hub", initialize)

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with self.engine.begin() as db:
            yield db

    def _lock_revision(self, db: Connection, expected: int) -> int:
        if self.engine.dialect.name == "sqlite":
            db.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            db.execute(select(catalog_metadata).with_for_update()).all()
        revision = db.scalar(select(func.coalesce(func.max(events.c.revision), 0)))
        if expected != revision:
            raise CatalogError("Catalog changed. Refresh and review before confirming again.", 409)
        return int(revision)

    def _record_event(
        self,
        db: Connection,
        action: str,
        target: str,
        change: CatalogConfirmation,
        actor: str,
        now: str,
        *,
        channel: str | None = None,
    ) -> None:
        next_revision = change.revision + 1
        db.execute(
            events.insert().values(
                revision=next_revision,
                action=action,
                release_id=target,
                channel=channel,
                reason=change.reason.strip(),
                occurred_at=now,
            )
        )
        db.execute(event_actors.insert().values(revision=next_revision, actor=actor))

    def _verify_signature(self, manifest: str, signature: str | None) -> None:
        try:
            if not signature:
                raise ValueError("Missing signature.")
            self.key.public_key.verify(b64decode(signature, validate=True), manifest.encode())
        except (InvalidSignature, ValueError) as error:
            raise CatalogError("Stored Release signature failed verification.", 503) from error

    def renew(
        self, change: CatalogConfirmation, *, actor: str = "local-operator"
    ) -> dict[str, Any]:
        if not actor.strip() or len(actor) > 160:
            raise CatalogError("An attributed operator is required.")
        if change.confirmation != f"renew {change.revision}":
            raise CatalogError("Type renew and the exact catalog revision to confirm.")
        if not change.reason.strip():
            raise CatalogError("A non-blank reason is required.")
        with self.connect() as db:
            revision = self._lock_revision(db, change.revision)
            updated_at = db.execute(
                select(events.c.occurred_at).where(events.c.revision == revision)
                if revision
                else select(catalog_metadata.c.created_at)
            ).scalar_one()
            now = self.clock()
            if now.tzinfo is None or now <= datetime.fromisoformat(updated_at):
                raise CatalogError("Publication clock must advance before renewal.", 409)
            for manifest, signature, published_at, recalled_at in db.execute(
                select(
                    releases.c.manifest,
                    releases.c.signature,
                    releases.c.published_at,
                    releases.c.recalled_at,
                )
            ):
                if published_at is not None or recalled_at is not None or signature:
                    self._verify_signature(manifest, signature)
            self._record_event(db, "renew", "catalog", change, actor, now.isoformat())
        return self.snapshot()

    def change(
        self,
        action: str,
        release_id: str,
        change: Change,
        *,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        if not actor or len(actor) > 160:
            raise CatalogError("An attributed operator is required.")
        if not is_release_id(release_id):
            raise CatalogError("Release id must be canonical SemVer.")
        if change.confirmation != release_id:
            raise CatalogError("Type the exact Release id to confirm.")
        if not change.reason.strip():
            raise CatalogError("A non-blank reason is required.")
        with self.connect() as db:
            self._lock_revision(db, change.revision)
            now = self.clock().isoformat()
            row = db.execute(select(releases).where(releases.c.id == release_id)).mappings().first()
            if action == "register":
                if row:
                    raise CatalogError("Release ids are immutable and cannot be reused.", 409)
                if change.manifest is None:
                    raise CatalogError("A lifecycle Release manifest is required.")
                release = parse_lifecycle_release_manifest(change.manifest.encode())
                if release.schema_version not in LIFECYCLE_RELEASE_SCHEMAS:
                    raise CatalogError("Only supported lifecycle Release manifests are accepted.")
                self._validate_configuration_version(release_id, release)
                db.execute(
                    releases.insert().values(
                        id=release_id,
                        label=change.label.strip(),
                        manifest=change.manifest,
                        digest=release.digest,
                    )
                )
            else:
                if row is None:
                    raise CatalogError("Release not found.", 404)
                if row["recalled_at"]:
                    raise CatalogError("Recalled Releases cannot be changed or re-promoted.", 409)
                if action == "publish":
                    if row["signature"]:
                        raise CatalogError("Release is already published.", 409)
                    # Revalidate persisted draft bytes at the signing boundary, not just ingress.
                    release = parse_lifecycle_release_manifest(row["manifest"].encode())
                    self._validate_configuration_version(release_id, release)
                    if release.digest != row["digest"]:
                        raise CatalogError("Stored Release digest does not match the draft.", 409)
                    signature = b64encode(self.key.sign(row["manifest"].encode())).decode("ascii")
                    db.execute(
                        releases.update()
                        .where(releases.c.id == release_id)
                        .values(
                            signature=signature,
                            published_at=now,
                        )
                    )
                    db.execute(membership.insert().values(channel="DEV", release_id=release_id))
                elif action == "contribute":
                    if not row["signature"]:
                        raise CatalogError(
                            "Publish the Release before adding it to a channel.", 409
                        )
                    if change.channel not in CHANNELS:
                        raise CatalogError("Choose a supported channel.")
                    release = parse_lifecycle_release_manifest(row["manifest"].encode())
                    if isinstance(release, NginxAcceptanceRelease) and change.channel != "DEV":
                        raise CatalogError("Nginx acceptance releases are restricted to DEV.")
                    exists = db.execute(
                        select(membership).where(
                            membership.c.channel == change.channel,
                            membership.c.release_id == release_id,
                        )
                    ).first()
                    if exists:
                        raise CatalogError("Release already belongs to this channel.", 409)
                    db.execute(
                        membership.insert().values(channel=change.channel, release_id=release_id)
                    )
                elif action == "recall":
                    if not row["signature"]:
                        raise CatalogError("Only published Releases can be recalled.", 409)
                    db.execute(
                        releases.update().where(releases.c.id == release_id).values(recalled_at=now)
                    )
                else:
                    raise CatalogError("Unsupported action.")
            self._record_event(db, action, release_id, change, actor, now, channel=change.channel)
        return self.snapshot()

    @staticmethod
    def _validate_configuration_version(release_id: str, release: LifecycleRelease) -> None:
        if isinstance(release, NginxAcceptanceRelease) and release.release_version != release_id:
            raise CatalogError("Acceptance version must match its exact Release id.")
        schema = release.configuration_schema
        if schema is not None and schema.release_version != release_id:
            raise CatalogError("Configuration schema does not match the exact Release version.")

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as db:
            # Hold the same lock as writers so the multi-query snapshot cannot mix revisions.
            if self.engine.dialect.name == "sqlite":
                db.exec_driver_sql("BEGIN")
            else:
                db.execute(select(catalog_metadata).with_for_update()).all()
            rows = db.execute(select(releases).order_by(releases.c.id.desc())).mappings().all()
            history = [
                dict(row)
                for row in db.execute(select(events).order_by(events.c.revision.desc())).mappings()
            ]
            actors = dict(db.execute(select(event_actors)).tuples().all())
            for event_record in history:
                event_record["actor"] = actors.get(event_record["revision"], "legacy-unattributed")
            memberships = (
                db.execute(
                    select(membership).order_by(
                        membership.c.channel,
                        membership.c.release_id,
                    )
                )
                .mappings()
                .all()
            )
            updated_at = (
                history[0]["occurred_at"]
                if history
                else db.execute(select(catalog_metadata.c.created_at)).scalar_one()
            )
        records = []
        for row in rows:
            record = dict(row)
            record["signed_payload_sha256"] = hashlib.sha256(
                record["manifest"].encode()
            ).hexdigest()
            if record["signature"]:
                self._verify_signature(record["manifest"], record["signature"])
            record["channels"] = [m["channel"] for m in memberships if m["release_id"] == row["id"]]
            record["state"] = (
                "recalled" if row["recalled_at"] else "published" if row["signature"] else "draft"
            )
            record["signature_status"] = (
                "development-key-verified" if row["signature"] else "unsigned"
            )
            records.append(record)
        return {
            "revision": history[0]["revision"] if history else 0,
            "updated_at": updated_at,
            "expires_at": (datetime.fromisoformat(updated_at) + timedelta(hours=24)).isoformat(),
            "expired": self.clock() >= datetime.fromisoformat(updated_at) + timedelta(hours=24),
            "mode": "local-development",
            "key_id": self.key.key_id,
            "releases": records,
            "channels": {
                c: [m["release_id"] for m in memberships if m["channel"] == c] for c in CHANNELS
            },
            "events": history,
        }

    def export(self) -> tuple[bytes, str]:
        return self.export_snapshot(self.snapshot())

    @staticmethod
    def export_snapshot(snapshot: dict[str, Any]) -> tuple[bytes, str]:
        recalls = [
            {
                "scope": "release",
                "target": event["release_id"],
                "sequence": event["revision"],
                "notice_digest": hashlib.sha256(
                    canonical_bytes(
                        {name: value for name, value in event.items() if name != "actor"}
                    )
                ).hexdigest(),
                "action": "recall",
                "lifting_release_id": None,
            }
            for event in reversed(snapshot["events"])
            if event["action"] == "recall"
        ]
        body = canonical_bytes(
            {
                "revision": snapshot["revision"],
                "expires_at": snapshot["expires_at"],
                "releases": {
                    r["id"]: {"manifest": r["manifest"], "signature": r["signature"]}
                    for r in snapshot["releases"]
                    if r["signature"]
                },
                "channels": snapshot["channels"],
                "recalls": recalls,
            }
        )
        return body, hashlib.sha256(body).hexdigest()

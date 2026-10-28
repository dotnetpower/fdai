"""Transactional, local development publication. Artifacts are never uploaded or built."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from base64 import b64decode, b64encode
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_promotion import (
    CanaryObservation,
    PromotionStageCriteria,
    PromotionStageInput,
    evaluate_promotion_stage,
)
from fdai_deployment_cli.lifecycle_release import (
    LIFECYCLE_RELEASE_SCHEMAS,
    ApplicationRelease,
    LifecycleRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    evaluate_recall_candidate,
    is_release_id,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from fdai_lifecycle_hub.catalog_import import MAX_EXPORT_BYTES, export_signing_message
from fdai_lifecycle_hub.catalog_trust import key_id_of
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.catalog_roles import (
    CatalogRoleKeys,
    CatalogRoleService,
    SignedMetadata,
    snapshot_content,
)
from fdai_release_hub.catalog_serialization import (
    CATALOG_VIEW_LIMIT_MESSAGE,
    EXPORT_LIMIT_MESSAGE,
    BoundedJson,
    catalog_position,
    ensure_row_bound,
    index_memberships,
    release_channels,
    stream,
    write_channels,
)
from fdai_release_hub.catalog_serialization import (
    CatalogError as CatalogError,
)
from fdai_release_hub.database import (
    catalog_metadata,
    event_actors,
    events,
    membership,
    metadata,
    releases,
)

CHANNELS = ("DEV", "RELEASE_CANDIDATE", "RELEASE")


def _is_custom_channel(value: str | None) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 64
        and re.fullmatch(r"custom-[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None
    )


class CatalogConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=0)
    confirmation: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=500)


class Change(CatalogConfirmation):
    channel: str | None = Field(default=None, max_length=64)
    channel_confirmation: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=160)
    manifest: str | None = Field(default=None, max_length=1024 * 1024)


class CapabilityChange(CatalogConfirmation):
    lifting_release_id: str | None = Field(default=None, max_length=64)


@dataclass(frozen=True, slots=True)
class SignedExport:
    """Exact export bytes, their digest and the Release key's detached signature."""

    revision: int
    raw: bytes
    digest: str
    signature: str
    key_id: str


class ReleaseStore:
    def __init__(
        self,
        path: Path | Engine,
        key: HubSigningKey,
        *,
        clock: Callable[[], datetime] | None = None,
        initialize: bool = True,
        role_keys: CatalogRoleKeys | None = None,
    ) -> None:
        self.path = path
        self.key = key
        self._export_lock = threading.Lock()
        self._signed_export: SignedExport | None = None
        self.clock = clock or (lambda: datetime.now(UTC))
        self.engine = (
            create_engine(f"sqlite:///{path}", poolclass=NullPool)
            if isinstance(path, Path)
            else path
        )
        self.roles = (
            CatalogRoleService(
                self.engine,
                role_keys,
                export_key_id=key_id_of(key.public_key),
                clock=self.clock,
            )
            if role_keys is not None
            else None
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

    def _verify_release_state(
        self,
        manifest: str,
        signature: str | None,
        published_at: str | None,
        recalled_at: str | None,
    ) -> None:
        if (published_at is not None or recalled_at is not None) and not signature:
            self._verify_signature(manifest, signature)
        if signature and published_at is None:
            raise CatalogError("Stored Release publication state is inconsistent.", 503)
        if signature:
            self._verify_signature(manifest, signature)

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
                self._verify_release_state(manifest, signature, published_at, recalled_at)
            self._record_event(db, "renew", "catalog", change, actor, now.isoformat())
            snapshot = self._snapshot_locked(db)
            self.export_snapshot(snapshot)
        return snapshot

    def change(
        self,
        action: str,
        release_id: str,
        change: Change,
        *,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        if not actor.strip() or len(actor) > 160:
            raise CatalogError("An attributed operator is required.")
        if not is_release_id(release_id):
            raise CatalogError("Release id must be canonical SemVer.")
        if change.confirmation != release_id:
            raise CatalogError("Type the exact Release id to confirm.")
        if not change.reason.strip():
            raise CatalogError("A non-blank reason is required.")
        if action == "contribute":
            if change.channel not in CHANNELS and not _is_custom_channel(change.channel):
                raise CatalogError("Choose a built-in channel or a custom- channel name.")
            if _is_custom_channel(change.channel):
                if change.channel_confirmation != change.channel:
                    raise CatalogError("Type the exact custom channel name to confirm.")
            elif change.channel_confirmation is not None:
                raise CatalogError(
                    "Custom channel confirmation is not valid for a built-in channel."
                )
        elif change.channel_confirmation is not None:
            raise CatalogError("Custom channel confirmation is only valid for contribution.")
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
                self._verify_release_state(
                    row["manifest"],
                    row["signature"],
                    row["published_at"],
                    row["recalled_at"],
                )
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
                    release = parse_lifecycle_release_manifest(row["manifest"].encode())
                    prior_events = [
                        dict(event_row)
                        for event_row in db.execute(
                            select(events).order_by(events.c.revision.asc())
                        ).mappings()
                    ]
                    decision = evaluate_recall_candidate(
                        release_id=release_id,
                        capability_ids=tuple(sorted(release.capability_maximums)),
                        recall_records=self._recall_records_from_events(prior_events),
                    )
                    if not decision.allowed:
                        raise CatalogError(
                            "Releases with an active recalled capability cannot be promoted.", 409
                        )
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
            snapshot = self._snapshot_locked(db)
            self.export_snapshot(snapshot)
        return snapshot

    def change_capability(
        self,
        action: str,
        capability_id: str,
        change: CapabilityChange,
        *,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        if not actor.strip() or len(actor) > 160:
            raise CatalogError("An attributed operator is required.")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", capability_id) is None:
            raise CatalogError("Capability id is invalid.")
        if change.confirmation != capability_id:
            raise CatalogError("Type the exact capability id to confirm.")
        if not change.reason.strip():
            raise CatalogError("A non-blank reason is required.")
        with self.connect() as db:
            self._lock_revision(db, change.revision)
            now = self.clock().isoformat()
            prior_events = [
                dict(event_row)
                for event_row in db.execute(
                    select(events)
                    .where(
                        events.c.release_id == capability_id,
                        events.c.action.in_(("recall_capability", "lift_capability")),
                    )
                    .order_by(events.c.revision.asc())
                ).mappings()
            ]
            active_recall = bool(prior_events and prior_events[-1]["action"] == "recall_capability")
            if action == "recall":
                if change.lifting_release_id is not None:
                    raise CatalogError("A capability recall cannot name a lifting Release.")
                if active_recall:
                    raise CatalogError("Capability is already actively recalled.", 409)
                self._record_event(db, "recall_capability", capability_id, change, actor, now)
            elif action == "lift":
                if change.lifting_release_id is None or not is_release_id(
                    change.lifting_release_id
                ):
                    raise CatalogError("Lifting Release id must be canonical SemVer.")
                if not active_recall:
                    raise CatalogError("Capability is not actively recalled.", 409)
                lifting_row = (
                    db.execute(select(releases).where(releases.c.id == change.lifting_release_id))
                    .mappings()
                    .first()
                )
                if (
                    lifting_row is None
                    or not lifting_row["signature"]
                    or lifting_row["recalled_at"]
                ):
                    raise CatalogError("Lifting Release must be published and not recalled.", 409)
                self._verify_release_state(
                    lifting_row["manifest"],
                    lifting_row["signature"],
                    lifting_row["published_at"],
                    lifting_row["recalled_at"],
                )
                self._record_event(
                    db,
                    "lift_capability",
                    capability_id,
                    change,
                    actor,
                    now,
                    channel=change.lifting_release_id,
                )
            else:
                raise CatalogError("Unsupported capability action.")
            snapshot = self._snapshot_locked(db)
            self.export_snapshot(snapshot)
        return snapshot

    def promote_stage(
        self,
        release_id: str,
        criteria: PromotionStageCriteria,
        change: Change,
        *,
        labels: frozenset[str] = frozenset(),
        canary_observations: tuple[CanaryObservation, ...] = (),
        elapsed_stage_seconds: int = 0,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        """Promote ``release_id`` to ``criteria.target_channel`` only when pipeline checks pass."""

        current = self.snapshot()
        release_entries = {item["id"]: item for item in current["releases"]}
        if release_id not in release_entries:
            raise CatalogError("Release was not found.", 404)
        release = parse_lifecycle_release_manifest(release_entries[release_id]["manifest"].encode())
        present_in_source = release_id in current["channels"].get(criteria.source_channel, [])
        events_asc = list(reversed(current["events"]))
        stage_input = PromotionStageInput(
            release_id=release_id,
            present_in_source_channel=present_in_source,
            labels=labels,
            canary_observations=canary_observations,
            elapsed_stage_seconds=elapsed_stage_seconds,
            capability_ids=tuple(sorted(release.capability_maximums)),
            recall_records=self._recall_records_from_events(events_asc),
        )
        decision = evaluate_promotion_stage(criteria, stage_input)
        if not decision.allowed:
            raise CatalogError(f"Promotion stage blocked ({decision.reason_code}).", 409)
        return self.change(
            "contribute",
            release_id,
            Change(
                revision=change.revision,
                confirmation=change.confirmation,
                reason=change.reason,
                channel=criteria.target_channel,
                channel_confirmation=change.channel_confirmation,
            ),
            actor=actor,
        )

    @staticmethod
    def _validate_configuration_version(release_id: str, release: LifecycleRelease) -> None:
        if isinstance(release, ApplicationRelease) and release.release_version != release_id:
            raise CatalogError("Application version must match its exact Release id.")
        schema = release.configuration_schema
        if schema is not None and schema.release_version != release_id:
            raise CatalogError("Configuration schema does not match the exact Release version.")

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as db:
            self._lock_snapshot(db)
            return self._snapshot_locked(db)

    def _lock_snapshot(self, db: Connection) -> None:
        # Hold the same lock as writers so a multi-query read cannot mix revisions.
        if self.engine.dialect.name == "sqlite":
            db.exec_driver_sql("BEGIN")
        else:
            db.execute(select(catalog_metadata).with_for_update()).all()

    def _snapshot_locked(self, db: Connection) -> dict[str, Any]:
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
        channel_names, channels_by_release, releases_by_channel = index_memberships(
            memberships, is_custom_channel=_is_custom_channel
        )
        records = []
        for row in rows:
            record = dict(row)
            self._verify_release_state(
                record["manifest"],
                record["signature"],
                record["published_at"],
                record["recalled_at"],
            )
            record["signed_payload_sha256"] = hashlib.sha256(
                record["manifest"].encode()
            ).hexdigest()
            record["channels"] = channels_by_release.get(row["id"], [])
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
                c: releases_by_channel.get(c, [])
                for c in (*CHANNELS, *sorted(channel_names - set(CHANNELS)))
            },
            "events": history,
        }

    def catalog_view(self, maximum: int) -> bytes:
        with self.connect() as db:
            self._lock_snapshot(db)
            ensure_row_bound(
                db,
                maximum=maximum,
                message=CATALOG_VIEW_LIMIT_MESSAGE,
                export_only=False,
            )
            _, export_digest = self._export_locked(db, MAX_EXPORT_BYTES)
            revision, updated_at = catalog_position(db)
            expires_at = (datetime.fromisoformat(updated_at) + timedelta(hours=24)).isoformat()
            writer = BoundedJson(maximum, CATALOG_VIEW_LIMIT_MESSAGE)
            writer.write(b'{"channels":')
            write_channels(db, writer, is_custom_channel=_is_custom_channel)
            writer.write(b',"events":[')
            first = True
            event_rows = stream(
                db,
                select(
                    events,
                    event_actors.c.actor,
                )
                .select_from(events.outerjoin(event_actors))
                .order_by(events.c.revision.desc()),
            )
            for row in event_rows:
                record = dict(row)
                if record["actor"] is None:
                    record["actor"] = "legacy-unattributed"
                if not first:
                    writer.write(b",")
                first = False
                writer.value(record)
            writer.write(b'],"expired":')
            writer.value(self.clock() >= datetime.fromisoformat(expires_at))
            writer.write(b',"expires_at":')
            writer.value(expires_at)
            writer.write(b',"export_sha256":')
            writer.value(export_digest)
            writer.write(b',"key_id":')
            writer.value(self.key.key_id)
            writer.write(b',"mode":"local-development","releases":[')
            first = True
            for row in stream(db, select(releases).order_by(releases.c.id.desc())):
                record = dict(row)
                self._verify_release_state(
                    record["manifest"],
                    record["signature"],
                    record["published_at"],
                    record["recalled_at"],
                )
                record["signed_payload_sha256"] = hashlib.sha256(
                    record["manifest"].encode()
                ).hexdigest()
                record["channels"] = release_channels(db, record["id"], writer.remaining)
                record["state"] = (
                    "recalled"
                    if record["recalled_at"]
                    else "published"
                    if record["signature"]
                    else "draft"
                )
                record["signature_status"] = (
                    "development-key-verified" if record["signature"] else "unsigned"
                )
                if not first:
                    writer.write(b",")
                first = False
                writer.value(record)
            writer.write(b'],"revision":')
            writer.value(revision)
            writer.write(b',"updated_at":')
            writer.value(updated_at)
            writer.write(b"}")
            return writer.finish()

    def export(self, *, maximum: int = MAX_EXPORT_BYTES) -> tuple[bytes, str]:
        with self.connect() as db:
            self._lock_snapshot(db)
            return self._export_locked(db, maximum)

    def renew_if_due(
        self,
        *,
        min_remaining: timedelta | None = None,
        actor: str = "system:timestamp-renewal",
    ) -> bool:
        """Re-assert already published content when its validity is running out.

        With signed roles this re-signs only the timestamp: no event is appended, the export
        and its revision stay byte-identical, and versions only increase. Without roles it is
        the legacy renewal, which appends an attributed event and moves the export expiry. In
        both forms it cannot add, change or recall a Release or channel.
        """

        if self.roles is not None and self.roles.installed():
            signed = self.signed_export()
            within = (
                min_remaining if min_remaining is not None else self.roles.keys.timestamp_ttl / 2
            )
            return self.roles.renew_if_due(
                signed.digest, lambda: snapshot_content(signed.raw, signed.digest), within
            )
        min_remaining = min_remaining if min_remaining is not None else timedelta(hours=12)
        with self.engine.connect() as db:
            revision, updated_at = catalog_position(db)
        remaining = datetime.fromisoformat(updated_at) + timedelta(hours=24) - self.clock()
        if remaining > min_remaining:
            return False
        try:
            self.renew(
                CatalogConfirmation(
                    revision=revision,
                    confirmation=f"renew {revision}",
                    reason="Automatic freshness renewal of reviewed content",
                ),
                actor=actor,
            )
        except CatalogError as error:
            if error.status == 409:
                return False
            raise
        return True

    def signed_metadata(self) -> SignedMetadata:
        """Signed root chain, snapshot and timestamp for the current export."""

        if self.roles is None:
            raise CatalogError("Signed catalog roles are not configured.", 404)
        signed = self.signed_export()
        return self.roles.served(signed.digest, lambda: snapshot_content(signed.raw, signed.digest))

    def install_root(self, raw: bytes, *, actor: str) -> dict[str, Any]:
        """Install the next offline-signed root. Private root keys never reach this process."""

        if self.roles is None:
            raise CatalogError("Signed catalog roles are not configured.", 404)
        return self.roles.install_root(raw, actor=actor)

    def signed_export(self) -> SignedExport:
        """Serve the signed export from a one-entry cache keyed by catalog revision.

        Each change appends an event, so one revision names exactly one export. A request storm
        therefore costs one position query, and at most one export is built at a time.
        """

        with self.engine.connect() as db:
            revision = catalog_position(db)[0]
        with self._export_lock:
            cached = self._signed_export
            if cached is not None and cached.revision == revision:
                return cached
            raw, digest = self.export()
            built_revision = json.loads(raw)["revision"]
            signed = SignedExport(
                revision=built_revision,
                raw=raw,
                digest=digest,
                signature=b64encode(self.key.sign(export_signing_message(raw))).decode("ascii"),
                key_id=self.key.key_id,
            )
            self._signed_export = signed
            return signed

    def _export_locked(self, db: Connection, maximum: int) -> tuple[bytes, str]:
        ensure_row_bound(
            db,
            maximum=maximum,
            message=EXPORT_LIMIT_MESSAGE,
            export_only=True,
        )
        revision, updated_at = catalog_position(db)
        expires_at = (datetime.fromisoformat(updated_at) + timedelta(hours=24)).isoformat()
        writer = BoundedJson(maximum, EXPORT_LIMIT_MESSAGE)
        writer.write(b'{"channels":')
        write_channels(db, writer, is_custom_channel=_is_custom_channel)
        writer.write(b',"expires_at":')
        writer.value(expires_at)
        writer.write(b',"recalls":[')
        first = True
        recall_rows = stream(
            db,
            select(events)
            .where(events.c.action.in_(("recall", "recall_capability", "lift_capability")))
            .order_by(events.c.revision),
        )
        for row in recall_rows:
            if not first:
                writer.write(b",")
            first = False
            writer.value(self._recall_dicts([dict(row)])[0])
        writer.write(b'],"releases":{')
        first = True
        for row in stream(db, select(releases).order_by(releases.c.id)):
            record = dict(row)
            self._verify_release_state(
                record["manifest"],
                record["signature"],
                record["published_at"],
                record["recalled_at"],
            )
            if not record["signature"]:
                continue
            if not first:
                writer.write(b",")
            first = False
            writer.value(record["id"])
            writer.write(b":")
            writer.value(
                {
                    "manifest": record["manifest"],
                    "signature": record["signature"],
                }
            )
        writer.write(b'},"revision":')
        writer.value(revision)
        writer.write(b"}")
        body = writer.finish()
        return body, hashlib.sha256(body).hexdigest()

    @staticmethod
    def _recall_dicts(events_asc: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recalls: list[dict[str, Any]] = []
        for entry in events_asc:
            action = entry["action"]
            if action not in ("recall", "recall_capability", "lift_capability"):
                continue
            recalls.append(
                {
                    "scope": "release" if action == "recall" else "capability",
                    "target": entry["release_id"],
                    "sequence": entry["revision"],
                    "notice_digest": hashlib.sha256(
                        canonical_bytes(
                            {name: value for name, value in entry.items() if name != "actor"}
                        )
                    ).hexdigest(),
                    "action": "lift" if action == "lift_capability" else "recall",
                    "lifting_release_id": entry["channel"] if action == "lift_capability" else None,
                }
            )
        return recalls

    @classmethod
    def _recall_records_from_events(
        cls, events_asc: list[dict[str, Any]]
    ) -> tuple[RecallRecord, ...]:
        return tuple(RecallRecord(**item) for item in cls._recall_dicts(events_asc))

    @classmethod
    def export_snapshot(cls, snapshot: dict[str, Any]) -> tuple[bytes, str]:
        recalls = cls._recall_dicts(list(reversed(snapshot["events"])))
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
        if len(body) > MAX_EXPORT_BYTES:
            raise CatalogError(EXPORT_LIMIT_MESSAGE, 503)
        return body, hashlib.sha256(body).hexdigest()

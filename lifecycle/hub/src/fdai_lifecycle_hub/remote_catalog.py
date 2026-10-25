"""Operator-approved exact-pin imports, with durable rollback protection and bounded transport."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from azure.core.exceptions import AzureError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Engine, Integer, LargeBinary, MetaData, String, Table, Text, select
from sqlalchemy.engine import Connection, RowMapping

from fdai_lifecycle_hub import catalog_integrity_state as integrity_store
from fdai_lifecycle_hub import local_channels as local_channel_store
from fdai_lifecycle_hub.adoption_policy import AdoptionConfig
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import (
    MAX_EXPORT_BYTES,
    load_pinned_export,
    verify_export_signature,
)
from fdai_lifecycle_hub.catalog_integrity import (
    IntegrityAssessment,
    IntegrityFloors,
    assess_roles,
    bind_export,
    export_keys,
    export_signature_verified,
)
from fdai_lifecycle_hub.catalog_trust import CatalogTrust, MetadataBundle
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import PlanOutcome
from fdai_lifecycle_hub.migrations import begin_sqlite_write, require_writable_schema
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

logger = logging.getLogger(__name__)
metadata = MetaData()
trust_state = Table(
    "catalog_trust_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("approval_revision", Integer, nullable=False),
    Column("approval_digest", String(64)),
    Column("floor", Integer, nullable=False),
    Column("previous_digest", String(64)),
    Column("payload", LargeBinary),
    Column("key_digest", String(64), nullable=False),
)
trust_events = Table(
    "catalog_trust_event",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("action", String(40), nullable=False),
    Column("actor", String(160), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("reason", Text, nullable=False),
    Column("recorded_at", String(40), nullable=False),
)


class CatalogSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    url: str
    access: Literal["managed-identity", "anonymous"] = "managed-identity"
    token_scope: str | None = Field(default=None, min_length=1)
    managed_identity_client_id: str | None = Field(default=None, min_length=1)
    # Legacy trust is one development Release key. `trust` replaces it with TUF-style roles.
    release_public_key: str | None = None
    trust: CatalogTrust | None = None
    # Zero disables the periodic check. Otherwise the Hub polls no faster than every 5 minutes.
    check_interval_seconds: int = Field(default=3600, ge=0, le=86400)
    adoption: AdoptionConfig = AdoptionConfig()

    @model_validator(mode="after")
    def validate_source(self) -> CatalogSource:
        url = urlsplit(self.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or url.path != "/v1/catalog/export"
        ):
            raise ValueError("Catalog source must be one approved HTTPS export URL.")
        if self.access == "managed-identity":
            if not self.token_scope or not self.managed_identity_client_id:
                raise ValueError("Catalog access by Managed Identity needs a scope and client.")
            if not self.token_scope.endswith("/.default"):
                raise ValueError("Catalog service scope must name the Release Hub application.")
        elif self.token_scope is not None or self.managed_identity_client_id is not None:
            raise ValueError("Anonymous catalog access must not name an identity.")
        if 0 < self.check_interval_seconds < 300:
            raise ValueError("Catalog checks run at most every five minutes.")
        if (self.release_public_key is None) == (self.trust is None):
            raise ValueError("Name exactly one catalog trust: a release public key or tuf roles.")
        if self.release_public_key is not None:
            self.public_key()
        return self

    @property
    def tuf(self) -> bool:
        return self.trust is not None

    @property
    def metadata_url(self) -> str:
        return self.url.removesuffix("/export") + "/metadata"

    def public_key(self) -> Ed25519PublicKey:
        if self.release_public_key is None:
            raise ValueError("Catalog trust uses signed roles, not one release key.")
        key = serialization.load_pem_public_key(self.release_public_key.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Catalog trust key must be Ed25519.")
        return key

    @property
    def key_digest(self) -> str:
        if self.trust is not None:
            return self.trust.key_digest
        return hashlib.sha256(
            self.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).hexdigest()


class PinApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: str
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def confirmed(self) -> PinApproval:
        if self.confirmation != f"approve {self.revision} {self.sha256}" or not self.reason.strip():
            raise ValueError("Confirm the exact independently approved revision and digest.")
        return self


@dataclass(frozen=True, slots=True)
class FetchedExport:
    """Export bytes with the detached signature that arrived on the same response."""

    raw: bytes
    signature: str | None
    key_id: str | None


def _bearer(source: CatalogSource, deadline: float) -> str | None:
    if source.access == "anonymous":
        return None
    # Only ManagedIdentityCredential is used: no CLI/developer credential fallback in a remote Hub.
    from azure.identity import ManagedIdentityCredential

    try:
        with ManagedIdentityCredential(
            client_id=source.managed_identity_client_id,
            connection_timeout=5,
            read_timeout=5,
            retry_total=0,
        ) as credential:
            token = credential.get_token(source.token_scope)
    except AzureError:
        raise ValueError("Catalog service identity unavailable; import stopped.") from None
    if time.monotonic() >= deadline:
        raise ValueError("Catalog service identity exceeded the import deadline.")
    return str(token.token)


def _download(
    source: CatalogSource, *, url: str | None = None, if_none_match: str | None = None
) -> tuple[int, bytes, Mapping[str, str]]:
    deadline = time.monotonic() + 15
    bearer = _bearer(source, deadline)
    headers = {"Accept-Encoding": "identity"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if if_none_match is not None:
        headers["If-None-Match"] = f'"{if_none_match}"'
    raw = bytearray()
    try:
        with httpx.stream(
            "GET",
            url or source.url,
            headers=headers,
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as response:
            if response.status_code == 304 and if_none_match is not None:
                return 304, b"", {}
            if response.status_code != 200:
                raise ValueError(
                    "Catalog source did not return a successful export; import stopped."
                )
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Compressed catalog exports are not accepted.")
            for chunk in response.iter_raw(chunk_size=64 * 1024):
                raw.extend(chunk)
                if len(raw) > MAX_EXPORT_BYTES or time.monotonic() >= deadline:
                    raise ValueError("Catalog export exceeded its size or time bound.")
            received = {
                name: response.headers[name]
                for name in ("x-fdai-export-signature", "x-fdai-export-key-id")
                if name in response.headers
            }
    except httpx.HTTPError as error:
        raise ValueError("Catalog transport failed; no trust state was changed.") from error
    if time.monotonic() >= deadline:
        raise ValueError("Catalog download exceeded the import deadline.")
    return 200, bytes(raw), received


def fetch_export(source: CatalogSource) -> bytes:
    return _download(source)[1]


def fetch_metadata(source: CatalogSource) -> bytes:
    """One bounded request for the signed roles that accompany the export."""

    return _download(source, url=source.metadata_url)[1]


def fetch_signed_export(
    source: CatalogSource, *, accepted_digest: str | None = None
) -> FetchedExport | None:
    """One bounded poll. None means the source reports the accepted digest is still current."""

    status, raw, headers = _download(source, if_none_match=accepted_digest)
    if status == 304:
        return None
    return FetchedExport(
        raw=raw,
        signature=headers.get("x-fdai-export-signature"),
        key_id=headers.get("x-fdai-export-key-id"),
    )


class CandidateChangedError(ValueError):
    """The accepted catalog or the source moved after a candidate was assessed."""


class CatalogNotImportedError(ValueError):
    """The trust binding exists but no pinned export has been approved and imported yet."""


class RemoteCatalog:
    def __init__(
        self,
        engine: Engine,
        source: CatalogSource,
        *,
        fetch: Callable[[CatalogSource], bytes] = fetch_export,
        fetch_signed: Callable[..., FetchedExport | None] = fetch_signed_export,
        fetch_roles: Callable[[CatalogSource], bytes] = fetch_metadata,
    ) -> None:
        self.engine, self.source, self.fetch = engine, source, fetch
        self.fetch_signed = fetch_signed
        self.fetch_roles = fetch_roles

    def _unavailable_in_tuf(self) -> None:
        if self.source.tuf:
            raise ValueError("Manual pin approval is not available with signed catalog roles.")

    def _locked(self, connection: Connection) -> RowMapping:
        begin_sqlite_write(connection)
        row = (
            connection.execute(select(trust_state).where(trust_state.c.id == 1).with_for_update())
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError(
                "Catalog trust is not bound; run explicit bind-catalog before serving."
            )
        if row["key_digest"] != self.source.key_digest:
            raise ValueError(
                "Catalog key differs from persisted trust; explicit key rotation is required."
            )
        return row

    def approve(self, pin: PinApproval, *, actor: str, now: datetime) -> None:
        """A customer operator supplies a pin from a separately approved channel, never an ETag."""
        self._unavailable_in_tuf()
        with self.engine.begin() as connection:
            require_writable_schema(connection)
            row = self._locked(connection)
            if pin.revision < max(row["floor"], row["approval_revision"]):
                raise ValueError("Catalog approval revision moved backwards.")
            if (
                pin.revision == row["approval_revision"]
                and row["approval_digest"] is not None
                and pin.sha256 != row["approval_digest"]
            ):
                raise ValueError("Catalog approval changed without a new revision.")
            if pin.revision == row["floor"] and row["previous_digest"] not in (None, pin.sha256):
                raise ValueError("Catalog approval conflicts with the accepted revision.")
            connection.execute(
                trust_state.update()
                .where(trust_state.c.id == 1)
                .values(
                    approval_revision=pin.revision,
                    approval_digest=pin.sha256,
                )
            )
            self._audit(
                connection, "pin.approved", actor, pin.revision, pin.sha256, pin.reason, now
            )

    def import_once(self, *, actor: str, now: datetime) -> dict[str, Any]:
        self._unavailable_in_tuf()
        started = time.monotonic()
        with self.engine.connect() as connection:
            require_writable_schema(connection)
        # Do not make a network request without an approved trust-channel input.
        before = self.status()
        if before["approved_sha256"] is None:
            raise ValueError("Approve an independently obtained exact pin before importing.")
        raw = self.fetch(self.source)
        with self.engine.begin() as connection:
            require_writable_schema(connection)
            row = self._locked(connection)
            if (
                before["approved_revision"] != row["approval_revision"]
                or before["approved_sha256"] != row["approval_digest"]
            ):
                raise ValueError(
                    "Catalog approval changed during download; review before importing."
                )
            now += timedelta(seconds=time.monotonic() - started)
            self._verify(raw, row, now)
            revision = json.loads(raw)["revision"]
            if revision != row["approval_revision"]:
                raise ValueError("Catalog export does not match the approved revision.")
            connection.execute(
                trust_state.update()
                .where(trust_state.c.id == 1)
                .values(
                    floor=revision,
                    previous_digest=row["approval_digest"],
                    payload=raw,
                )
            )
            self._audit(
                connection,
                "catalog.imported",
                actor,
                revision,
                row["approval_digest"],
                "bounded_import",
                now,
            )
        return self.status()

    def adopt(
        self,
        fetched: FetchedExport,
        *,
        expected_previous_digest: str | None,
        actor: str,
        reason: str,
        now: datetime,
        roles: MetadataBundle | None = None,
        allow_root_rotation: bool = False,
    ) -> dict[str, Any]:
        """Replace the accepted catalog with exact bytes the pinned Release key signed.

        The signature, the manifests, the revision floor and the write share one transaction, so
        a concurrent import, approval or recompute cannot interleave with the replacement. The
        caller names the accepted digest its policy decision was computed against, so a change
        that was never assessed cannot ride along after the baseline moved. With signed roles the
        same transaction re-verifies the roles against the persisted floors and advances them; a
        root rotation advances only when `allow_root_rotation` records a person's review.
        """

        started = time.monotonic()
        digest = hashlib.sha256(fetched.raw).hexdigest()
        with self.engine.begin() as connection:
            require_writable_schema(connection)
            row = self._locked(connection)
            assessment, keys = self._trusted_export(
                connection, fetched, roles, now, started, allow_root_rotation
            )
            if row["previous_digest"] == digest:
                if assessment is not None:
                    integrity_store.persist(
                        connection, assessment, now=now, accept_rotation=allow_root_rotation
                    )
                return {"adopted": False, "revision": row["floor"], "sha256": digest}
            if row["previous_digest"] != expected_previous_digest:
                raise CandidateChangedError("The accepted catalog changed after assessment.")
            if (
                row["approval_digest"] not in (None, digest)
                and revision_of(fetched.raw) == row["approval_revision"]
            ):
                raise ValueError("Catalog adoption conflicts with an operator-approved pin.")
            effective = now + timedelta(seconds=time.monotonic() - started)
            self._verify(
                fetched.raw,
                dict(row) | {"approval_digest": digest},
                effective,
                keys=keys,
                enforce_expiry=assessment is None,
            )
            revision = json.loads(fetched.raw)["revision"]
            if revision < max(row["floor"], row["approval_revision"]):
                raise ValueError("Catalog adoption revision moved backwards.")
            connection.execute(
                trust_state.update()
                .where(trust_state.c.id == 1)
                .values(
                    approval_revision=revision,
                    approval_digest=digest,
                    floor=revision,
                    previous_digest=digest,
                    payload=fetched.raw,
                )
            )
            if assessment is not None:
                integrity_store.persist(
                    connection, assessment, now=now, accept_rotation=allow_root_rotation
                )
            self._audit(connection, "pin.approved", actor, revision, digest, reason, now)
            self._audit(
                connection, "catalog.imported", actor, revision, digest, "signed_adoption", now
            )
        return {"adopted": True, "revision": revision, "sha256": digest}

    def _trusted_export(
        self,
        connection: Connection,
        fetched: FetchedExport,
        roles: MetadataBundle | None,
        now: datetime,
        started: float,
        allow_root_rotation: bool,
    ) -> tuple[IntegrityAssessment | None, Ed25519PublicKey | tuple[Ed25519PublicKey, ...]]:
        """Authenticate the export bytes under the configured trust, inside the caller's lock."""

        trust = self.source.trust
        if trust is None:
            if not verify_export_signature(
                fetched.raw, fetched.signature, self.source.public_key()
            ):
                raise ValueError("Catalog export signature does not verify.")
            return None, self.source.public_key()
        if roles is None:
            raise ValueError("Signed catalog roles are required to adopt a catalog.")
        floors = integrity_store.floors_of(integrity_store.read_integrity(connection, lock=True))
        assessment = assess_roles(
            roles,
            trust=trust,
            floors=floors,
            now=now + timedelta(seconds=time.monotonic() - started),
        )
        if not assessment.verified or assessment.root is None:
            raise ValueError("Catalog integrity does not verify.")
        if assessment.root_rotation and not allow_root_rotation:
            raise ValueError("A root rotation needs review before adoption.")
        if not export_signature_verified(fetched.raw, fetched.signature, assessment.root):
            raise ValueError("Catalog export signature does not verify.")
        if bind_export(assessment, raw=fetched.raw, floors=floors) is not None:
            raise ValueError("Catalog roles do not describe this export.")
        return assessment, export_keys(assessment.root)

    def integrity_floors(self) -> IntegrityFloors:
        """The persisted anti-rollback floors. Only meaningful with signed roles."""

        with self.engine.connect() as connection:
            return integrity_store.floors_of(integrity_store.read_integrity(connection))

    def integrity_status(self) -> dict[str, Any] | None:
        """Floors and the last observation for display, or None with legacy trust."""

        if not self.source.tuf:
            return None
        with self.engine.connect() as connection:
            return integrity_store.public_state(integrity_store.read_integrity(connection))

    def observe_integrity(self, assessment: IntegrityAssessment, *, now: datetime) -> None:
        """Remember a verified observation, advancing floors unless a rotation awaits review."""

        with self.engine.begin() as connection:
            require_writable_schema(connection)
            if assessment.verified and not assessment.root_rotation:
                integrity_store.persist(connection, assessment, now=now)
            else:
                integrity_store.record_result(connection, assessment.to_json(), now=now)

    def accepted_baseline(self) -> tuple[ReleaseCatalog | None, str | None, str | None]:
        """The accepted catalog, its expiry and digest, even when expired, for diffing only."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(select(trust_state).where(trust_state.c.id == 1))
                .mappings()
                .one_or_none()
            )
        if row is None or row["payload"] is None:
            return None, None, None
        with self.engine.connect() as connection:
            keys = self._accepted_keys(connection)
        previous = load_pinned_export(
            row["payload"],
            expected_sha256=row["previous_digest"],
            public_key=keys,
            now=datetime(1970, 1, 1, tzinfo=UTC),
            minimum_revision=0,
            previous_sha256=None,
        )
        return previous, json.loads(row["payload"])["expires_at"], row["previous_digest"]

    def _accepted_keys(
        self, connection: Connection
    ) -> Ed25519PublicKey | tuple[Ed25519PublicKey, ...]:
        """Keys that vouch for the accepted bytes: the pinned key, or the accepted root's."""

        if self.source.trust is None:
            return self.source.public_key()
        root = integrity_store.accepted_root(integrity_store.read_integrity(connection))
        if root is None:
            raise CatalogNotImportedError("No verified catalog root has been accepted.")
        return export_keys(root)

    def record_review_needed(
        self, *, revision: int, digest: str, reason: str, now: datetime
    ) -> None:
        """Record one review request per candidate digest, so repeated polls add no rows."""

        with self.engine.begin() as connection:
            require_writable_schema(connection)
            latest = connection.execute(
                select(trust_events.c.digest)
                .where(trust_events.c.action == "check.review_required")
                .order_by(trust_events.c.sequence.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest != digest:
                self._audit(
                    connection,
                    "check.review_required",
                    "policy:catalog-adoption",
                    revision,
                    digest,
                    reason,
                    now,
                )

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(trust_events).order_by(trust_events.c.sequence.desc()).limit(limit)
            ).mappings()
            return [
                {
                    "action": row["action"],
                    "actor": row["actor"],
                    "revision": row["revision"],
                    "sha256": row["digest"],
                    "reason": row["reason"],
                    "recorded_at": row["recorded_at"],
                }
                for row in rows
            ]

    def catalog(self, now: datetime) -> ReleaseCatalog:
        started = time.monotonic()
        with self.engine.begin() as connection:
            row = self._locked(connection)
            return self._curated(
                connection, row, now + timedelta(seconds=time.monotonic() - started)
            )[0]

    def signed_release(
        self,
        release_id: str,
        digest: str,
        *,
        now: datetime,
    ) -> tuple[bytes, bytes]:
        """Return original signed Release bytes after revalidating accepted catalog trust."""

        with self.engine.begin() as connection:
            row = self._locked(connection)
            admitted = self._accepted(row, now, connection)
            release = admitted.releases.get(release_id)
            if release is None or release.digest != digest:
                raise ValueError("Accepted catalog Release differs from the requested artifact.")
            document = json.loads(row["payload"])
            record = document.get("releases", {}).get(release_id)
            if (
                not isinstance(record, dict)
                or set(record) != {"manifest", "signature"}
                or not isinstance(record["manifest"], str)
                or not isinstance(record["signature"], str)
            ):
                raise ValueError("Accepted catalog Release artifact is invalid.")
            try:
                signature = base64.b64decode(record["signature"], validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("Accepted catalog Release signature is invalid.") from None
            if len(signature) != 64:
                raise ValueError("Accepted catalog Release signature is invalid.")
            return record["manifest"].encode(), signature

    def _accepted(
        self, row: RowMapping, now: datetime, connection: Connection | None = None
    ) -> ReleaseCatalog:
        if row["payload"] is None:
            raise CatalogNotImportedError("No verified catalog has been imported.")
        if self.source.tuf and connection is None:
            with self.engine.connect() as own:
                return self._accepted(row, now, own)
        # A new approval does not replace accepted bytes until explicit import.
        keys = (
            self._accepted_keys(connection)
            if connection is not None
            else (self.source.public_key())
        )
        catalog = load_pinned_export(
            row["payload"],
            expected_sha256=row["previous_digest"],
            public_key=keys,
            now=now,
            minimum_revision=row["floor"],
            previous_sha256=row["previous_digest"],
            enforce_expiry=not self.source.tuf,
        )
        if connection is None or not self.source.tuf:
            return catalog
        state = integrity_store.read_integrity(connection)
        fresh_until = [
            datetime.fromisoformat(value)
            for value in (state["timestamp_expires_at"], state["snapshot_expires_at"])
            if value
        ]
        if len(fresh_until) < 2 or now >= min(fresh_until):
            # A stale signed timestamp leaves recall roll-off as the only safe plan type.
            return replace(catalog, plan_types=frozenset({"recall-rolloff"}))
        return catalog

    def _curated(
        self, connection: Connection, row: RowMapping, now: datetime
    ) -> tuple[ReleaseCatalog, dict[str, Any]]:
        return local_channel_store.view(
            connection,
            self._accepted(row, now, connection),
            accepted_sha256=row["previous_digest"],
            source_revision=row["floor"],
            key_digest=row["key_digest"],
        )

    def local_channels(self, *, now: datetime) -> dict[str, Any]:
        started = time.monotonic()
        with self.engine.begin() as connection:
            row = self._local_locked(connection)
            return self._curated(
                connection, row, now + timedelta(seconds=time.monotonic() - started)
            )[1]

    def _local_locked(self, connection: Connection) -> RowMapping:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
        return self._locked(connection)

    def add_local_channel(
        self, request: local_channel_store.LocalChannelRequest, *, actor: str, now: datetime
    ) -> dict[str, Any]:
        started = time.monotonic()
        with self.engine.begin() as connection:
            require_writable_schema(connection)
            row = self._local_locked(connection)
            effective_now = now + timedelta(seconds=time.monotonic() - started)
            admitted = self._accepted(row, effective_now, connection)
            local_channel_store.add(
                connection,
                request,
                admitted,
                accepted_sha256=row["previous_digest"],
                source_revision=row["floor"],
                key_digest=row["key_digest"],
                actor=actor,
                now=effective_now,
            )
            return self._curated(
                connection, row, now + timedelta(seconds=time.monotonic() - started)
            )[1]

    def recompute(
        self,
        store: HubStore,
        installation_id: str,
        key: HubSigningKey,
        *,
        now: datetime,
        configuration_revision: ConfigurationRevisionCandidate | None = None,
        configuration_key_version: int | None = None,
    ) -> PlanOutcome:
        """Serialize catalog replacement with planning, so recall cannot race a stale snapshot."""

        def evaluate(
            admitted: ReleaseCatalog, now: datetime, connection: Connection
        ) -> PlanOutcome:
            bound = (
                store.with_connection(connection) if store.engine.url == self.engine.url else store
            )
            if configuration_revision is not None:
                if configuration_key_version is None:
                    raise ValueError("Configuration planning requires an approved binding version.")
                return bound.recompute_configuration(
                    installation_id,
                    configuration_revision,
                    binding_version=configuration_key_version,
                    catalog=admitted,
                    key=key,
                    now=now,
                )
            return bound.recompute_persisted(
                installation_id,
                catalog=admitted,
                key=key,
                now=now,
            )

        return self.configuration_operation(evaluate, now=now)

    def configuration_operation[T](
        self,
        operation: Callable[[ReleaseCatalog, datetime, Connection], T],
        *,
        now: datetime,
    ) -> T:
        """Keep exact pinned catalog replacement serialized with import/approval/activation."""
        started = time.monotonic()
        failure: KeyBindingError | None = None
        result: T | None = None
        with self.engine.begin() as connection:
            require_writable_schema(connection)
            row = self._locked(connection)
            effective_now = now + timedelta(seconds=time.monotonic() - started)
            admitted = self._curated(connection, row, effective_now)[0]
            try:
                result = operation(admitted, effective_now, connection)
                if admitted.local_curation is not None:
                    self._accepted(
                        row, now + timedelta(seconds=time.monotonic() - started), connection
                    )
            except KeyBindingError as error:
                failure = error
        if failure is not None:
            raise failure
        if result is None:
            raise ValueError("Configuration operation produced no outcome.")
        return result

    def status(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(trust_state).where(trust_state.c.id == 1))
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError(
                    "Catalog trust is not bound; run explicit bind-catalog before serving."
                )
            if row["key_digest"] != self.source.key_digest:
                raise ValueError("Catalog key differs from persisted trust.")
            if self.source.tuf:
                integrity_store.read_integrity(connection)
            return {
                "approved_revision": row["approval_revision"],
                "approved_sha256": row["approval_digest"],
                "minimum_revision": row["floor"],
                "accepted_sha256": row["previous_digest"],
                "imported": row["payload"] is not None,
                "mode": "tuf-catalog-roles" if self.source.tuf else "development-pinned-export",
            }

    def _verify(
        self,
        raw: bytes,
        row: Mapping[str, Any] | RowMapping,
        now: datetime,
        *,
        keys: Ed25519PublicKey | tuple[Ed25519PublicKey, ...] | None = None,
        enforce_expiry: bool = True,
    ) -> ReleaseCatalog:
        return load_pinned_export(
            raw,
            expected_sha256=row["approval_digest"],
            public_key=keys if keys is not None else self.source.public_key(),
            now=now,
            minimum_revision=row["floor"],
            previous_sha256=row["previous_digest"],
            enforce_expiry=enforce_expiry,
        )

    @staticmethod
    def _audit(
        connection: Connection,
        action: str,
        actor: str,
        revision: int,
        digest: str,
        reason: str,
        now: datetime,
    ) -> None:
        connection.execute(
            trust_events.insert().values(
                action=action,
                actor=actor,
                revision=revision,
                digest=digest,
                reason=reason,
                recorded_at=now.isoformat(),
            )
        )


def revision_of(raw: bytes) -> int:
    return int(json.loads(raw)["revision"])


def initialize_trust(connection: Connection, source: CatalogSource) -> None:
    metadata.create_all(connection)
    if connection.scalar(select(trust_state.c.id)) is None:
        connection.execute(
            trust_state.insert().values(
                id=1,
                approval_revision=0,
                floor=0,
                key_digest=source.key_digest,
            )
        )
    if source.tuf:
        integrity_store.ensure_integrity_state(connection)


def bind_catalog(engine: Engine, source: CatalogSource, *, actor: str, reason: str) -> None:
    """Bind an independently approved source key after standalone migration; never import bytes."""
    if not actor.strip() or len(actor) > 160 or not reason.strip() or len(reason) > 500:
        raise ValueError("Catalog binding requires a bounded actor and reason.")
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text

            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('lifecycle_hub'))"))
        elif engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        require_writable_schema(connection)
        row = connection.execute(select(trust_state).with_for_update()).mappings().one_or_none()
        if row is not None:
            if row["key_digest"] != source.key_digest:
                raise ValueError("Catalog key differs; explicit key rotation is required.")
            if source.tuf:
                integrity_store.ensure_integrity_state(connection)
            return
        initialize_trust(connection, source)
        connection.execute(
            trust_events.insert().values(
                action="source.bound",
                actor=actor,
                revision=0,
                digest=source.key_digest,
                reason=reason,
                recorded_at=datetime.now(UTC).isoformat(),
            )
        )

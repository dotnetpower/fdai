"""Operator-approved exact-pin imports, with durable rollback protection and bounded transport."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from azure.core.exceptions import AzureError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Engine, Integer, LargeBinary, MetaData, String, Table, Text, select
from sqlalchemy.engine import Connection, RowMapping

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import MAX_EXPORT_BYTES, load_pinned_export
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import PlanOutcome
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
    token_scope: str = Field(min_length=1)
    managed_identity_client_id: str = Field(min_length=1)
    release_public_key: str

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
        if not self.token_scope.endswith("/.default"):
            raise ValueError("Catalog service scope must name the Release Hub application.")
        self.public_key()
        return self

    def public_key(self) -> Ed25519PublicKey:
        key = serialization.load_pem_public_key(self.release_public_key.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Catalog trust key must be Ed25519.")
        return key

    @property
    def key_digest(self) -> str:
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


def fetch_export(source: CatalogSource) -> bytes:
    # Only ManagedIdentityCredential is used: no CLI/developer credential fallback in a remote Hub.
    from azure.identity import ManagedIdentityCredential

    deadline = time.monotonic() + 15
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
    raw = bytearray()
    try:
        with httpx.stream(
            "GET",
            source.url,
            headers={"Authorization": f"Bearer {token.token}", "Accept-Encoding": "identity"},
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as response:
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
    except httpx.HTTPError as error:
        raise ValueError("Catalog transport failed; no trust state was changed.") from error
    if time.monotonic() >= deadline:
        raise ValueError("Catalog download exceeded the import deadline.")
    return bytes(raw)


class RemoteCatalog:
    def __init__(
        self,
        engine: Engine,
        source: CatalogSource,
        *,
        fetch: Callable[[CatalogSource], bytes] = fetch_export,
    ) -> None:
        self.engine, self.source, self.fetch = engine, source, fetch

    def _locked(self, connection: Connection) -> RowMapping:
        if self.engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
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
        with self.engine.begin() as connection:
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
        started = time.monotonic()
        # Do not make a network request without an approved trust-channel input.
        before = self.status()
        if before["approved_sha256"] is None:
            raise ValueError("Approve an independently obtained exact pin before importing.")
        raw = self.fetch(self.source)
        with self.engine.begin() as connection:
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

    def catalog(self, now: datetime) -> ReleaseCatalog:
        with self.engine.begin() as connection:
            row = self._locked(connection)
            if row["payload"] is None:
                raise ValueError("No verified catalog has been imported.")
            # New pin approval does not authorize old bytes. Planning uses the accepted pin.
            return load_pinned_export(
                row["payload"],
                expected_sha256=row["previous_digest"],
                public_key=self.source.public_key(),
                now=now,
                minimum_revision=row["floor"],
                previous_sha256=row["previous_digest"],
            )

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
            row = self._locked(connection)
            effective_now = now + timedelta(seconds=time.monotonic() - started)
            if row["payload"] is None:
                raise ValueError("No verified catalog has been imported.")
            admitted = load_pinned_export(
                row["payload"],
                expected_sha256=row["previous_digest"],
                public_key=self.source.public_key(),
                now=effective_now,
                minimum_revision=row["floor"],
                previous_sha256=row["previous_digest"],
            )
            try:
                result = operation(admitted, effective_now, connection)
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
            return {
                "approved_revision": row["approval_revision"],
                "approved_sha256": row["approval_digest"],
                "minimum_revision": row["floor"],
                "accepted_sha256": row["previous_digest"],
                "imported": row["payload"] is not None,
                "mode": "development-pinned-export",
            }

    def _verify(self, raw: bytes, row: RowMapping, now: datetime) -> ReleaseCatalog:
        return load_pinned_export(
            raw,
            expected_sha256=row["approval_digest"],
            public_key=self.source.public_key(),
            now=now,
            minimum_revision=row["floor"],
            previous_sha256=row["previous_digest"],
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
        row = connection.execute(select(trust_state).with_for_update()).mappings().one_or_none()
        if row is not None:
            if row["key_digest"] != source.key_digest:
                raise ValueError("Catalog key differs; explicit key rotation is required.")
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

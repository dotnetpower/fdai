"""Add-only customer curation narrows a verified catalog; it never changes vendor bytes."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.runtime_release import evaluate_recall_candidate, is_release_id
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, select
from sqlalchemy.engine import Connection

from fdai_lifecycle_hub.catalog import LocalCurationEvidence, ReleaseCatalog

MAX_LOCAL_MEMBERS = 1024
metadata = MetaData()
entries = Table(
    "catalog_local_channel_entry",
    metadata,
    Column("revision", Integer, primary_key=True),
    Column("channel", String(64), nullable=False),
    Column("release_id", String(160), nullable=False),
    Column("release_digest", String(64), nullable=False),
    Column("accepted_sha256", String(64), nullable=False),
    Column("source_revision", Integer, nullable=False),
    Column("key_digest", String(64), nullable=False),
    Column("actor", String(160), nullable=False),
    Column("reason", Text, nullable=False),
    Column("recorded_at", String(40), nullable=False),
    Column("entry_digest", String(64), nullable=False),
    UniqueConstraint("channel", "release_id"),
)


class LocalChannelError(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class LocalChannelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    revision: int = Field(ge=0)
    channel: str = Field(min_length=7, max_length=64, pattern=r"^local-[a-z0-9]+(?:-[a-z0-9]+)*$")
    release_id: str = Field(min_length=1, max_length=160)
    release_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def confirmed(self) -> LocalChannelRequest:
        if (
            not is_release_id(self.release_id)
            or self.channel != self.channel.strip()
            or not self.reason.strip()
            or self.confirmation != f"add {self.release_id} to {self.channel}"
        ):
            raise ValueError("Review and confirm the exact Release and local channel.")
        return self


def _rows(connection: Connection) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in connection.execute(
            select(entries).order_by(entries.c.revision).limit(MAX_LOCAL_MEMBERS + 1)
        ).mappings()
    ]
    if len(rows) > MAX_LOCAL_MEMBERS:
        raise LocalChannelError("Local curation exceeds the supported development bound.", 503)
    for expected, row in enumerate(rows, 1):
        material = {k: v for k, v in row.items() if k != "entry_digest"}
        if (
            row["revision"] != expected
            or hashlib.sha256(canonical_bytes(material)).hexdigest() != row["entry_digest"]
            or not isinstance(row["actor"], str)
            or not row["actor"].strip()
            or len(row["actor"]) > 160
        ):
            raise LocalChannelError("Retained local curation evidence is inconsistent.", 503)
        try:
            LocalChannelRequest(
                revision=expected - 1,
                channel=row["channel"],
                release_id=row["release_id"],
                release_digest=row["release_digest"],
                accepted_sha256=row["accepted_sha256"],
                reason=row["reason"],
                confirmation=f"add {row['release_id']} to {row['channel']}",
            )
            recorded = datetime.fromisoformat(row["recorded_at"])
            if recorded.utcoffset() is None:
                raise ValueError("Local curation time must be timezone-aware.")
        except ValueError as error:
            raise LocalChannelError("Retained local curation evidence is invalid.", 503) from error
    return rows


def _hold_reason(
    catalog: ReleaseCatalog,
    release_id: str,
    release_digest: str,
    key_digest: str,
    *,
    current_key_digest: str,
) -> str | None:
    release = catalog.releases.get(release_id)
    if key_digest != current_key_digest:
        return "source_key_changed"
    if release is None:
        return "release_unknown"
    if release.digest != release_digest:
        return "release_digest_changed"
    if release_id not in catalog.channels.get("RELEASE", frozenset()):
        return "release_not_in_source_release_channel"
    recall = evaluate_recall_candidate(
        release_id=release_id, capability_ids=(), recall_records=catalog.recalls
    )
    return None if recall.allowed else recall.reason_code


def view(
    connection: Connection,
    catalog: ReleaseCatalog,
    *,
    accepted_sha256: str,
    source_revision: int,
    key_digest: str,
) -> tuple[ReleaseCatalog, dict[str, Any]]:
    """Recheck every retained membership against the current independently accepted source."""
    rows = _rows(connection)
    channels = dict(catalog.channels)
    for row in rows:
        if row["channel"] in catalog.channels:
            raise LocalChannelError("Vendor and local channel namespaces collide.", 503)
        channels.setdefault(row["channel"], frozenset())
    records = []
    for row in rows:
        reason = _hold_reason(
            catalog,
            row["release_id"],
            row["release_digest"],
            row["key_digest"],
            current_key_digest=key_digest,
        )
        if reason is None:
            channels[row["channel"]] |= {row["release_id"]}
        records.append({**row, "eligible": reason is None, "hold_reason": reason})
    digest = hashlib.sha256(
        canonical_bytes(
            {
                "accepted_sha256": accepted_sha256,
                "key_digest": key_digest,
                "entries": records,
            }
        )
    ).hexdigest()
    evidence = LocalCurationEvidence(
        len(rows), digest, accepted_sha256, source_revision, key_digest
    )
    effective = replace(catalog, channels=channels, local_curation=evidence) if rows else catalog
    available = [
        {"release_id": release_id, "release_digest": catalog.releases[release_id].digest}
        for release_id in sorted(catalog.channels.get("RELEASE", frozenset()))
        if _hold_reason(
            catalog,
            release_id,
            catalog.releases[release_id].digest,
            key_digest,
            current_key_digest=key_digest,
        )
        is None
    ]
    return effective, {
        "revision": len(rows),
        "digest": digest,
        "accepted_sha256": accepted_sha256,
        "source_revision": source_revision,
        "entries": records,
        "available_releases": available,
        "execution_authority": False,
    }


def add(
    connection: Connection,
    request: LocalChannelRequest,
    catalog: ReleaseCatalog,
    *,
    accepted_sha256: str,
    source_revision: int,
    key_digest: str,
    actor: str,
    now: datetime,
) -> None:
    """The caller holds the catalog lock; membership and its evidence are one insert."""
    if not actor.strip() or len(actor) > 160 or now.utcoffset() is None:
        raise LocalChannelError("An attributed operator and timezone-aware time are required.", 422)
    rows = _rows(connection)
    if request.revision != len(rows) or request.accepted_sha256 != accepted_sha256:
        raise LocalChannelError("Catalog or local revision changed; refresh and review.")
    if len(rows) == MAX_LOCAL_MEMBERS:
        raise LocalChannelError("Local curation reached the supported development bound.", 422)
    if request.channel in catalog.channels:
        raise LocalChannelError("A local channel cannot replace a vendor channel.", 422)
    if any(r["channel"] == request.channel and r["release_id"] == request.release_id for r in rows):
        raise LocalChannelError("Release already belongs to this local channel.")
    if (
        _hold_reason(
            catalog,
            request.release_id,
            request.release_digest,
            key_digest,
            current_key_digest=key_digest,
        )
        is not None
    ):
        raise LocalChannelError("Release is not eligible in the accepted RELEASE channel.", 422)
    material = {
        "revision": len(rows) + 1,
        "channel": request.channel,
        "release_id": request.release_id,
        "release_digest": request.release_digest,
        "accepted_sha256": accepted_sha256,
        "source_revision": source_revision,
        "key_digest": key_digest,
        "actor": actor,
        "reason": request.reason,
        "recorded_at": now.isoformat(),
    }
    connection.execute(
        entries.insert().values(
            **material, entry_digest=hashlib.sha256(canonical_bytes(material)).hexdigest()
        )
    )

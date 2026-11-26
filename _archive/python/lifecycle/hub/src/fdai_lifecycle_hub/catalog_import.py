"""Opt-in local Release Hub export admission, not a production catalog trust protocol."""

from __future__ import annotations

import hashlib
from base64 import b64decode
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.lifecycle_release import (
    LIFECYCLE_RELEASE_SCHEMAS,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.runtime_release import RecallRecord
from pydantic import BaseModel, ConfigDict, Field

from fdai_lifecycle_hub.catalog import ReleaseCatalog

MAX_EXPORT_BYTES = 8 * 1024 * 1024
EXPORT_SIGNATURE_DOMAIN = b"fdai.catalog-export.v1\n"
MAX_EXPORT_SIGNATURE_CHARS = 128


def export_signing_message(raw: bytes) -> bytes:
    """Domain-separate the export signature from manifest signatures made by the same key."""

    return EXPORT_SIGNATURE_DOMAIN + raw


def verify_export_signature(
    raw: bytes, signature: str | None, public_key: Ed25519PublicKey
) -> bool:
    """Whether the pinned Release key signed these exact export bytes."""

    if not signature or len(signature) > MAX_EXPORT_SIGNATURE_CHARS:
        return False
    try:
        public_key.verify(b64decode(signature, validate=True), export_signing_message(raw))
    except (InvalidSignature, ValueError):
        return False
    return True


class _Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    manifest: str
    signature: str


class _Export(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: Annotated[int, Field(ge=0)]
    expires_at: str
    releases: dict[str, _Artifact]
    channels: dict[str, list[str]]
    recalls: list[RecallRecord]


def _typed_recalls(document: dict[str, object]) -> None:
    recalls = document.get("recalls")
    if not isinstance(recalls, list):
        raise ValueError("Release Hub export recalls are invalid")
    try:
        records = []
        for record in recalls:
            if not isinstance(record, dict):
                raise ValueError
            records.append(RecallRecord(**record))
        document["recalls"] = records
    except (TypeError, ValueError) as error:
        raise ValueError("Release Hub export recalls are invalid") from error


def _manifest_signed(payload: bytes, signature: str, keys: Sequence[Ed25519PublicKey]) -> bool:
    try:
        decoded = b64decode(signature, validate=True)
    except ValueError:
        return False
    for key in keys:
        try:
            key.verify(decoded, payload)
        except InvalidSignature:
            continue
        return True
    return False


def load_pinned_export(
    raw: bytes,
    *,
    expected_sha256: str,
    public_key: Ed25519PublicKey | Sequence[Ed25519PublicKey],
    now: datetime,
    minimum_revision: int = 0,
    previous_sha256: str | None = None,
    enforce_expiry: bool = True,
) -> ReleaseCatalog:
    """Verify a locally transported export against an out-of-band pin and trusted key.

    The caller owns durable pin and revision-floor retention. No network or TOFU is performed.
    A new channel/recall snapshot requires a new operator-supplied pin. Exact pin verification
    binds version labels and membership; individual signatures cover exact manifest bytes.
    Several keys may be given when a signed root names more than one export key. The export's
    own expiry is skipped only when a signed timestamp carries freshness instead.
    """
    keys = (public_key,) if isinstance(public_key, Ed25519PublicKey) else tuple(public_key)
    if minimum_revision < 0:
        raise ValueError("Release Hub minimum revision must be non-negative")
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError("Release Hub export is too large")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise ValueError("Release Hub export digest does not match the trusted pin")
    document = load_json_object(raw, label="local Release Hub export", max_bytes=MAX_EXPORT_BYTES)
    _typed_recalls(document)
    export = _Export.model_validate(document)
    expires_at = datetime.fromisoformat(export.expires_at)
    if now.tzinfo is None or expires_at.tzinfo is None or (enforce_expiry and now >= expires_at):
        raise ValueError("Release Hub export is expired or has no timezone")
    if export.revision < minimum_revision:
        raise ValueError("Release Hub export revision moved backwards")
    if (
        export.revision == minimum_revision
        and previous_sha256 is not None
        and observed != previous_sha256
    ):
        raise ValueError("Release Hub export changed without a new revision")
    releases = {}
    for release_id, artifact in export.releases.items():
        payload = artifact.manifest.encode()
        if not _manifest_signed(payload, artifact.signature, keys):
            raise ValueError("Release Hub manifest signature verification failed")
        release = parse_lifecycle_release_manifest(payload)
        if release.schema_version not in LIFECYCLE_RELEASE_SCHEMAS:
            raise ValueError("Release Hub export requires a supported lifecycle Release")
        schema = release.configuration_schema
        if schema is not None and schema.release_version != release_id:
            raise ValueError("Configuration schema does not match the exact Release version")
        releases[release_id] = release
    return ReleaseCatalog(
        releases=releases,
        channels={name: frozenset(members) for name, members in export.channels.items()},
        recalls=tuple(export.recalls),
    )

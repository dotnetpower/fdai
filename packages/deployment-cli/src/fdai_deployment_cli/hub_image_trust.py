"""Verify a public signed export without importing the dependent lifecycle Hub package."""

from __future__ import annotations

import hashlib
import re
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cmp_to_key
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    compare_release_ids,
    evaluate_recall_candidate,
    is_release_id,
)
from fdai_deployment_cli.source_image_stage import DEPENDENCY_IMAGES, SERVICE_ORDER

MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_SELECTION_BYTES = 12 * 1024 * 1024
EXPORT_DOMAIN = b"fdai.catalog-export.v1\n"
PROVENANCE = "hub-signed-images-with-checkout-support"
INVENTORY = frozenset(SERVICE_ORDER) | DEPENDENCY_IMAGES.keys()


def public_key(pem: bytes) -> Ed25519PublicKey:
    if not 0 < len(pem) <= 4096:
        raise ValueError("Hub trust requires a bounded independently provisioned public PEM")
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Hub trust requires an Ed25519 public key")  # noqa: TRY004
    return key


def key_id(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "hub-" + hashlib.sha256(raw).hexdigest()[:16]


def validate_channel(channel: str) -> None:
    if (
        len(channel) > 64
        or re.fullmatch(r"(?:DEV|RELEASE_CANDIDATE|RELEASE|custom-[a-z0-9][a-z0-9-]*)", channel)
        is None
    ):
        raise ValueError("Hub channel must be DEV, RELEASE_CANDIDATE, RELEASE, or custom-*")


def _signature(key: Ed25519PublicKey, signature: object, payload: bytes) -> None:
    if not isinstance(signature, str) or not 0 < len(signature) <= 128:
        raise ValueError("Hub signature is missing or malformed")
    try:
        key.verify(b64decode(signature, validate=True), payload)
    except (InvalidSignature, ValueError) as error:
        raise ValueError("Hub signature verification failed; no source-build fallback") from error


@dataclass(frozen=True)
class HubImageSelection:
    path: Path
    digest: str
    document: dict[str, Any]
    release_id: str
    source_commit: str
    release_digest: str
    image_sources: dict[str, str]

    def metadata(self) -> dict[str, object]:
        return {
            "provenance": PROVENANCE,
            "artifact_source": "hub-signed-images",
            "hub_selection_digest": self.digest,
            "hub_release_id": self.release_id,
            "hub_channel": self.document["channel"],
            "hub_catalog_digest": self.document["catalog_digest"],
            "hub_catalog_revision": self.document["catalog_revision"],
            "runtime_release_digest": self.release_digest,
            "image_signature_verified": True,
            "release_signature_verified": False,
            "support_artifact_source": "operator-selected-source",
        }


def verify_export(
    raw: bytes,
    *,
    signature: str,
    export_key_id: str,
    trusted_pem: bytes,
    channel: str,
    release_id: str | None = None,
    now: datetime | None = None,
    minimum_revision: int = 0,
    previous_digest: str | None = None,
) -> dict[str, Any]:
    """Authenticate membership, all manifests and recall before selecting one exact Release."""
    if not 0 < len(raw) <= MAX_EXPORT_BYTES:
        raise ValueError("Hub export exceeds its size bound")
    validate_channel(channel)
    key = public_key(trusted_pem)
    if export_key_id != key_id(key):
        raise ValueError("Hub export key id differs from the independent trust key")
    _signature(key, signature, EXPORT_DOMAIN + raw)
    doc = load_json_object(raw, label="Hub signed export", max_bytes=MAX_EXPORT_BYTES, strict=True)
    if set(doc) != {"revision", "expires_at", "releases", "channels", "recalls"}:
        raise ValueError("Hub signed export fields are invalid")
    revision = doc["revision"]
    if type(revision) is not int or not 0 <= revision <= 2**63 - 1:
        raise ValueError("Hub signed export revision is invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if revision < minimum_revision or (
        revision == minimum_revision and previous_digest not in {None, digest}
    ):
        raise ValueError("Hub catalog rollback or same-revision substitution refused")
    now = now or datetime.now(UTC)
    try:
        expires = datetime.fromisoformat(doc["expires_at"])
    except (TypeError, ValueError) as error:
        raise ValueError("Hub catalog expiry is invalid") from error
    if now.tzinfo is None or expires.tzinfo is None or now >= expires:
        raise ValueError("Hub catalog expired; no source-build fallback")
    releases, channels, recalls = doc["releases"], doc["channels"], doc["recalls"]
    if (
        not isinstance(releases, dict)
        or not 1 <= len(releases) <= 4096
        or not isinstance(channels, dict)
        or not 1 <= len(channels) <= 256
        or not isinstance(recalls, list)
        or len(recalls) > 8192
    ):
        raise ValueError("Hub catalog inventory is invalid")
    parsed = {}
    for version, artifact in releases.items():
        if not isinstance(version, str) or len(version) > 64 or not is_release_id(version):
            raise ValueError("Hub release id is invalid")
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"manifest", "signature"}
            or not isinstance(artifact["manifest"], str)
        ):
            raise ValueError("Hub release artifact is invalid")
        manifest = artifact["manifest"].encode("utf-8")
        _signature(key, artifact["signature"], manifest)
        release = parse_lifecycle_release_manifest(manifest)
        if release.to_mapping().get("release_version", version) != version or (
            release.configuration_schema is not None
            and release.configuration_schema.release_version != version
        ):
            raise ValueError("Hub manifest version differs from the catalog release id")
        parsed[version] = release
    for name, members in channels.items():
        validate_channel(name)
        if (
            not isinstance(members, list)
            or len(members) > 4096
            or any(not isinstance(member, str) or member not in parsed for member in members)
            or len(set(members)) != len(members)
        ):
            raise ValueError("Hub channel members are invalid")
    active: dict[tuple[str, str], RecallRecord] = {}
    records: list[RecallRecord] = []
    try:
        for value in recalls:
            if not isinstance(value, dict):
                raise ValueError("Hub recall is invalid")  # noqa: TRY004
            record = RecallRecord(**value)
            identity = record.scope, record.target
            prior = active.get(identity)
            if prior is not None and record.sequence <= prior.sequence:
                raise ValueError("Hub recall sequence did not advance")
            active[identity] = record
            records.append(record)
    except (TypeError, ValueError) as error:
        raise ValueError("Hub recall history is invalid") from error
    members = channels.get(channel, [])
    capabilities = tuple(record.target for record in records if record.scope == "capability")
    eligible = [
        version
        for version in members
        if evaluate_recall_candidate(
            release_id=version, capability_ids=capabilities, recall_records=tuple(records)
        ).allowed
    ]
    if release_id is not None:
        if len(release_id) > 64 or not is_release_id(release_id) or release_id not in eligible:
            raise ValueError("Hub requested Release is absent, outside channel, or recalled")
        selected = release_id
    else:
        if not eligible:
            raise ValueError("Hub channel has no non-recalled Release")
        selected = max(eligible, key=cmp_to_key(compare_release_ids))
    release = parsed[selected]
    manifest_doc = release.to_mapping()
    components = manifest_doc.get("components")
    if (
        release.schema_version != APPLICATION_COMPONENT_RELEASE_SCHEMA
        or release.product != "fdai"
        or release.platform_tag != "linux-x86_64"
        or not isinstance(components, dict)
        or set(components) != INVENTORY
        or any(not isinstance(value.get("image_ref"), str) for value in components.values())
    ):
        raise ValueError(
            "Hub bootstrap requires an fdai linux-x86_64 application-release.v2 with all "
            "five services and two dependencies, each with signed digest-pinned image_ref"
        )
    return {
        "release_id": selected,
        "source_commit": release.source_commit,
        "release_digest": release.digest,
        "image_sources": {name: value["image_ref"] for name, value in components.items()},
        "catalog_digest": digest,
        "catalog_revision": revision,
    }


def load_selection(path: Path, expected_digest: str) -> HubImageSelection:
    raw = read_private_bytes(path, max_bytes=MAX_SELECTION_BYTES)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("Hub immutable selection digest differs")
    doc = load_json_object(raw, label="Hub selection", max_bytes=MAX_SELECTION_BYTES, strict=True)
    if doc.get("schema_version") != "fdai.hub-image-selection.v1":
        raise ValueError("Hub selection schema is invalid")
    result = verify_export(
        b64decode(doc["catalog"], validate=True),
        signature=doc["export_signature"],
        export_key_id=doc["export_key_id"],
        trusted_pem=doc["public_key"].encode("ascii"),
        channel=doc["channel"],
        release_id=doc["release_id"],
        minimum_revision=doc["catalog_revision"],
        previous_digest=doc["catalog_digest"],
    )
    if any(doc.get(name) != value for name, value in result.items()):
        raise ValueError("Hub selection disagrees with its authenticated catalog")
    return HubImageSelection(
        path=path,
        digest=expected_digest,
        document=doc,
        **{
            name: result[name]
            for name in ("release_id", "source_commit", "release_digest", "image_sources")
        },
    )


def selection_bytes(
    *,
    raw: bytes,
    signature: str,
    export_key_id: str,
    pem: bytes,
    hub_url: str,
    channel: str,
    verified: dict[str, Any],
) -> bytes:
    return canonical_bytes(
        {
            "schema_version": "fdai.hub-image-selection.v1",
            "hub_url": hub_url,
            "channel": channel,
            "catalog": b64encode(raw).decode("ascii"),
            "export_signature": signature,
            "export_key_id": export_key_id,
            "public_key": pem.decode("ascii"),
            **verified,
        }
    )

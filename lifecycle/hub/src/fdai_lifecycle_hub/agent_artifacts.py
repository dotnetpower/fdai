"""Serve only the signed artifacts named by one installation's current Plan."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_plan import decode_canonical_plan_payload

from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog
from fdai_lifecycle_hub.store import HubStore

ArtifactKind = Literal["release", "configuration"]
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    kind: ArtifactKind
    digest: str
    payload: bytes
    signature: bytes

    def to_json(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "digest": self.digest,
            "payload": base64.b64encode(self.payload).decode("ascii"),
            "signature": base64.b64encode(self.signature).decode("ascii"),
        }


def artifact_for_plan(
    store: HubStore,
    catalog: RemoteCatalog,
    installation_id: str,
    kind: ArtifactKind,
    digest: str,
    *,
    now: datetime,
) -> AgentArtifact:
    """Return one signed input only when the current eligible Plan names it exactly."""

    if _DIGEST.fullmatch(digest) is None:
        raise ValueError("Agent artifact digest is invalid.")
    plan = store.current_plan(installation_id, now=now)
    if plan is None:
        raise ValueError("Agent artifact requires one current eligible Plan.")
    decoded = decode_canonical_plan_payload(plan.signed_payload, plan.signature)
    if kind == "release":
        if decoded.target_release_digest != digest:
            raise ValueError("Agent artifact differs from the current Plan Release.")
        payload, signature = catalog.signed_release(
            decoded.target_release_id,
            digest,
            now=now,
        )
    elif kind == "configuration":
        if plan.configuration_digest != digest:
            raise ValueError("Agent artifact differs from the current Plan configuration.")
        record = ConfigurationImportStore(store.engine).read(installation_id, digest)
        payload, signature = _configuration_artifact(record["signed_container"], digest)
    else:
        raise ValueError("Agent artifact kind is unsupported.")
    return AgentArtifact(kind=kind, digest=digest, payload=payload, signature=signature)


def _configuration_artifact(container_b64: object, digest: str) -> tuple[bytes, bytes]:
    if not isinstance(container_b64, str):
        raise ValueError("Stored configuration container is invalid.")
    try:
        container = base64.b64decode(container_b64, validate=True)
        document = json.loads(container)
        if (
            not isinstance(document, dict)
            or set(document) != {"format", "payload", "signature"}
            or document["format"] != "fdai.lifecycle-configuration-file.v1"
        ):
            raise ValueError
        payload = base64.b64decode(document["payload"], validate=True)
        signature = base64.b64decode(document["signature"], validate=True)
    except (binascii.Error, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("Stored configuration container is invalid.") from None
    if len(payload) > 1024 * 1024 or len(signature) != 64:
        raise ValueError("Stored configuration artifact size is invalid.")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        raise ValueError("Stored configuration payload is invalid.") from None
    if canonical_digest(parsed) != digest:
        raise ValueError("Stored configuration payload digest differs.")
    return payload, signature


__all__ = ["AgentArtifact", "ArtifactKind", "artifact_for_plan"]

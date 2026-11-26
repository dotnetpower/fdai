"""Deployment-supplied operating ontology instance contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from .ontology_instance import OntologyLinkRecord, OntologyObjectRecord, normalize_json_value

OPERATING_MODEL_TOPIC = "fdai.operating-model"

REQUIRED_OPERATING_INTENT_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        "ArchitectureConstraint",
        "ChangeWindow",
        "CostObjective",
        "Ownership",
        "RecoveryObjective",
        "ServiceObjective",
    }
)
"""The six operating-intent ObjectTypes a deployment-owned intent source MUST supply."""


@dataclass(frozen=True, slots=True)
class OperatingModelSnapshot:
    """One bounded, versioned service/objective/ownership graph snapshot."""

    source_revision: str
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]

    def __post_init__(self) -> None:
        if not self.source_revision.strip():
            raise ValueError("OperatingModelSnapshot.source_revision MUST be non-empty")
        if len(self.objects) > 50_000 or len(self.links) > 200_000:
            raise ValueError("operating model snapshot exceeds object/link bounds")
        object_ids = [item.id for item in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("operating model snapshot object ids MUST be unique")
        link_keys = [(item.from_id, item.link_type, item.to_id) for item in self.links]
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("operating model snapshot link identities MUST be unique")


@dataclass(frozen=True, slots=True)
class OperatingModelUpdate:
    """One ordered complete snapshot delivered by a resumable provider."""

    cursor: str
    sequence: int
    snapshot: OperatingModelSnapshot

    def __post_init__(self) -> None:
        if not self.cursor.strip() or len(self.cursor) > 256:
            raise ValueError("OperatingModelUpdate.cursor MUST be 1..256 characters")
        if isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("OperatingModelUpdate.sequence MUST be a non-negative integer")


@runtime_checkable
class OperatingModelProvider(Protocol):
    async def load(self) -> OperatingModelSnapshot:
        """Load one immutable deployment-approved operating model snapshot."""
        ...


@runtime_checkable
class ContinuousOperatingModelProvider(Protocol):
    def updates(
        self,
        *,
        after_cursor: str | None,
        stop: asyncio.Event,
    ) -> AsyncIterator[OperatingModelUpdate]: ...


@dataclass(frozen=True, slots=True)
class OperatingIntentSourceProvenance:
    """Attribution the deployment-owned operating-intent source MUST self-declare.

    ``resolved_ref`` pins the exact upstream revision the deployment reviewed and
    approved; the runtime binding cross-checks it against the same file's own
    ``source_revision`` and against the operator-configured expected revision so a
    cross-release swap (an approved-looking file from a different release) fails
    closed instead of silently projecting.
    """

    source_url: str
    resolved_ref: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not self.source_url.strip():
            raise ValueError("OperatingIntentSourceProvenance.source_url MUST be non-empty")
        if not self.resolved_ref.strip():
            raise ValueError("OperatingIntentSourceProvenance.resolved_ref MUST be non-empty")
        if self.retrieved_at.tzinfo is None:
            raise ValueError(
                "OperatingIntentSourceProvenance.retrieved_at MUST be timezone-aware (RFC 3339)"
            )


@dataclass(frozen=True, slots=True)
class OperatingIntentSourceDocument:
    """One deployment-owned six-intent-type source file: snapshot plus provenance."""

    snapshot: OperatingModelSnapshot
    provenance: OperatingIntentSourceProvenance


def _snapshot_payload(snapshot: OperatingModelSnapshot) -> dict[str, object]:
    """Return the canonical, order-independent JSON payload of one snapshot."""

    objects = [
        {
            "id": item.id,
            "object_type": item.object_type,
            "properties": normalize_json_value(item.properties, path="operating_model.object"),
            "revision": item.revision,
            "type_ref": (
                item.type_ref.model_dump(mode="json") if item.type_ref is not None else None
            ),
        }
        for item in sorted(snapshot.objects, key=lambda value: value.id)
    ]
    links = [
        {
            "link_type": item.link_type,
            "from_id": item.from_id,
            "to_id": item.to_id,
            "properties": normalize_json_value(item.properties, path="operating_model.link"),
            "type_ref": (
                item.type_ref.model_dump(mode="json") if item.type_ref is not None else None
            ),
        }
        for item in sorted(
            snapshot.links,
            key=lambda value: (value.from_id, value.link_type, value.to_id),
        )
    ]
    return {
        "source_revision": snapshot.source_revision,
        "objects": objects,
        "links": links,
    }


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def operating_model_snapshot_digest(snapshot: OperatingModelSnapshot) -> str:
    """Return the canonical ``sha256:...`` content digest of one complete snapshot.

    The digest covers ``source_revision`` plus every object and link (sorted for order
    independence) and excludes nothing, so any content change - including a swapped,
    edited, or truncated deployment-owned source file - produces a different digest. Used
    by the continuous worker's replay/conflict suppression, where a snapshot arrives
    without a self-declared provenance block.
    """

    return _canonical_sha256(_snapshot_payload(snapshot))


def operating_intent_source_document_digest(document: OperatingIntentSourceDocument) -> str:
    """Return the canonical ``sha256:...`` digest of one *complete* intent source document.

    The deployment-owned operating-intent binding pins this digest, not the snapshot-only
    digest, because provenance is load-bearing evidence rather than decoration: the
    ``retrieved_at`` timestamp anchors every freshness judgement, and ``source_url`` and
    ``resolved_ref`` are the attribution an operator reviewed. Excluding them would leave
    a signed-looking source whose attribution and observation time could be rewritten
    without changing the pinned digest. Covering all three closes that gap, so editing
    any provenance field fails the pin exactly like editing an object does.
    """

    return _canonical_sha256(
        {
            "provenance": {
                "source_url": document.provenance.source_url,
                "resolved_ref": document.provenance.resolved_ref,
                "retrieved_at": document.provenance.retrieved_at.isoformat(),
            },
            "snapshot": _snapshot_payload(document.snapshot),
        }
    )


__all__ = [
    "OPERATING_MODEL_TOPIC",
    "REQUIRED_OPERATING_INTENT_OBJECT_TYPES",
    "ContinuousOperatingModelProvider",
    "OperatingIntentSourceDocument",
    "OperatingIntentSourceProvenance",
    "OperatingModelProvider",
    "OperatingModelSnapshot",
    "OperatingModelUpdate",
    "operating_intent_source_document_digest",
    "operating_model_snapshot_digest",
]

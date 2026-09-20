"""Canonical resource chunks for durable collection without graph authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from itertools import islice
from pathlib import Path
from typing import Any

from fdai.delivery.azure.inventory_redaction import redact_runtime_environment
from fdai.delivery.inventory_sync_models import PromotedInventoryObservation
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryCoverageManifest,
    InventorySnapshotStore,
    InventorySource,
    InventorySyncResult,
)
from fdai.shared.providers.ontology_instance import normalize_json_value

MAX_CHUNK_BYTES = 1024 * 1024
MAX_CHUNK_RESOURCES = 1000
MAX_COLLECTION_CHUNKS = 10000
MAX_COLLECTION_BYTES = 16 * 1024 * 1024
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PREFIX = "inventory-collection:"


class InventoryPromotionObserverError(RuntimeError):
    """The authoritative snapshot advanced but its derived projection failed."""


class InventoryStreamError(RuntimeError):
    """An inventory stream violated its atomic-fence contract."""


async def close_inventory_stream(
    stream: AsyncIterator[InventoryBatch], *, timeout_seconds: float
) -> None:
    aclose = getattr(stream, "aclose", None)
    if not callable(aclose):
        return
    task = asyncio.current_task()
    cancelling = task is not None and task.cancelling() > 0
    try:
        async with asyncio.timeout(min(5.0, timeout_seconds)):
            await aclose()
    except Exception as exc:
        if cancelling:
            raise asyncio.CancelledError from exc
        raise InventoryStreamError(
            "inventory source cleanup failed or exceeded its deadline"
        ) from exc


async def notify_inventory_promotion(
    observer: Callable[[PromotedInventoryObservation], Awaitable[None]] | None,
    observation: PromotedInventoryObservation,
) -> None:
    """A failed derived model never invalidates the already promoted provider generation."""
    if observer is None:
        return
    try:
        await observer(observation)
    except Exception as exc:
        logging.getLogger("fdai.delivery.inventory_sync").exception(
            "inventory_promotion_observer_failed", extra={"generation": observation.generation}
        )
        raise InventoryPromotionObserverError(
            "inventory promotion observer failed after authoritative promotion"
        ) from exc


async def resume_prepared_collection(
    source: InventorySource,
    store: InventorySnapshotStore,
    loader: Callable[
        [InventoryCoverageManifest],
        Awaitable[tuple[InventoryCoverageManifest, PromotedInventoryObservation] | None],
    ],
    observer: Callable[[PromotedInventoryObservation], Awaitable[None]],
) -> InventorySyncResult | None:
    """The caller holds its run lock; promotion independently rechecks the active base."""
    candidate = await loader(source.manifest)
    if candidate is None:
        return None
    manifest, observation = candidate
    await store.promote(observation.generation, manifest)
    await observer(observation)
    return InventorySyncResult(attempt_id=observation.generation, source=source.name, failures=())


def collection_configuration_digest(configuration: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        normalize_json_value(configuration), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def collection_producer_digest(root: Path | None = None) -> str:
    """Pin installed FDAI producer source, including ARM overlays, without retaining source text."""
    source_root = (root or Path(__file__).resolve().parents[1]).resolve()
    paths = sorted(islice(source_root.rglob("*.py"), 10001))
    if not paths or len(paths) > 10000:
        raise ValueError("inventory producer source is missing or exceeds its file bound")
    total_bytes = 0
    files = {}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(source_root):
            raise ValueError("inventory producer source must stay within its package")
        with path.open("rb") as stream:
            content = stream.read(64 * 1024 * 1024 - total_bytes + 1)
        total_bytes += len(content)
        if total_bytes > 64 * 1024 * 1024:
            raise ValueError("inventory producer source exceeds its byte bound")
        files[path.relative_to(source_root).as_posix()] = hashlib.sha256(content).hexdigest()
    return collection_configuration_digest({"schema_version": "1.0.0", "files": files})


def collection_context_digest(manifest: InventoryCoverageManifest) -> str:
    content = normalize_json_value(
        {
            "schema_version": "1.0.0",
            "source": manifest.source,
            "scopes": sorted(manifest.scopes),
            "resource_types": sorted(manifest.resource_types),
            "observation_kind": manifest.observation_kind.value,
            "metadata": manifest.metadata,
        }
    )
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def collection_key(attempt_id: str) -> str:
    if not attempt_id or attempt_id != attempt_id.strip() or len(attempt_id) > 256:
        raise ValueError("inventory chunk attempt identity is invalid")
    return _PREFIX + hashlib.sha256(attempt_id.encode()).hexdigest()


def _resource_content(item: ResourceRecord) -> dict[str, Any]:
    if item.props.get("_truncated") is True or redact_runtime_environment(item) != item:
        raise ValueError("inventory chunk requires complete redacted resources")
    return {
        "resource_id": item.resource_id,
        "type": item.type,
        "props": normalize_json_value(item.props),
        "provider_ref": item.provider_ref,
        "last_seen": item.last_seen,
    }


def resource_chunk(
    *,
    attempt_id: str,
    context_digest: str,
    sequence: int,
    previous_digest: str | None,
    batch: InventoryBatch,
) -> dict[str, Any]:
    """Validate canonical content before storage and bind its exact continuation."""
    collection_key(attempt_id)
    if (
        not isinstance(context_digest, str)
        or _DIGEST.fullmatch(context_digest) is None
        or (
            previous_digest is not None
            and (not isinstance(previous_digest, str) or _DIGEST.fullmatch(previous_digest) is None)
        )
    ):
        raise ValueError("inventory chunk context and predecessor must be exact digests")
    if type(sequence) is not int or not 0 <= sequence < MAX_COLLECTION_CHUNKS:
        raise ValueError("inventory chunk sequence exceeds its bound")
    if (sequence == 0) != (previous_digest is None):
        raise ValueError("inventory chunk predecessor does not match its sequence")
    if (
        batch.final
        or batch.links
        or batch.relationship_drops
        or batch.relationship_reconciliation_after is not None
        or not 1 <= len(batch.resources) <= MAX_CHUNK_RESOURCES
    ):
        raise ValueError("inventory resource chunk must contain only bounded nonterminal resources")
    if batch.cursor is not None and (
        not isinstance(batch.cursor, str) or not batch.cursor or len(batch.cursor) > 8192
    ):
        raise ValueError("inventory chunk cursor is invalid")
    if len({item.resource_id for item in batch.resources}) != len(batch.resources):
        raise ValueError("inventory chunk resource identities must be unique")
    content = {
        "schema_version": "1.0.0",
        "attempt_id": attempt_id,
        "context_digest": context_digest,
        "sequence": sequence,
        "previous_digest": previous_digest,
        "cursor": batch.cursor,
        "resources": [
            _resource_content(item)
            for item in sorted(batch.resources, key=lambda record: record.resource_id)
        ],
    }
    digest = hashlib.sha256()
    size = 0
    for part in json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).iterencode(content):
        encoded = part.encode()
        size += len(encoded)
        if size > MAX_CHUNK_BYTES:
            raise ValueError("inventory chunk payload exceeds its byte bound")
        digest.update(encoded)
    return {**content, "digest": "sha256:" + digest.hexdigest()}


def resource_chunk_batches(batch: InventoryBatch) -> Iterator[InventoryBatch]:
    """Advance a provider cursor only on the final resource chunk of its batch."""
    selected: list[ResourceRecord] = []
    size = 0
    for resource in batch.resources:
        encoded_size = len(
            json.dumps(
                _resource_content(resource), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        )
        if encoded_size > MAX_CHUNK_BYTES - 65536:
            raise ValueError("inventory resource exceeds its chunk capacity")
        if selected and (
            len(selected) >= MAX_CHUNK_RESOURCES or size + encoded_size > MAX_CHUNK_BYTES - 65536
        ):
            yield InventoryBatch(resources=tuple(selected))
            selected = []
            size = 0
        selected.append(resource)
        size += encoded_size
    if selected:
        yield InventoryBatch(resources=tuple(selected), cursor=batch.cursor)

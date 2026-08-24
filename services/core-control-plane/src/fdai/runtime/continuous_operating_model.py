"""Durable continuous operating-model projection worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.core.operational_context import OperatingModelProjectionResult
from fdai.delivery.operating_model.event_bus import (
    EventBusOperatingModelProvider,
    EventBusOperatingModelProviderConfig,
)
from fdai.runtime.operating_model import (
    operating_model_projection_matches,
    project_operating_model_from_env,
    project_operating_model_snapshot,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, normalize_json_value
from fdai.shared.providers.operating_model import (
    ContinuousOperatingModelProvider,
    OperatingModelUpdate,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

OPERATING_MODEL_CURSOR_KEY = "operating-model:continuous-cursor"
OPERATING_MODEL_REJECTION_KEY = "operating-model:continuous-rejection"
OPERATING_MODEL_REVISION_KEY_PREFIX = "operating-model:continuous-revision:"
OPERATING_MODEL_LOCK_KEY = "operating-model:continuous-apply"


class ContinuousOperatingModelWorker:
    """Apply monotonic complete snapshots and durably suppress replay or conflict."""

    def __init__(
        self,
        *,
        provider: ContinuousOperatingModelProvider,
        store: OntologyInstanceStore,
        object_types: Sequence[OntologyObjectType],
        link_types: Sequence[OntologyLinkType],
        state_store: StateStore,
        resource_lock: ResourceLock,
    ) -> None:
        self._provider = provider
        self._store = store
        self._object_types = tuple(object_types)
        self._link_types = tuple(link_types)
        self._state_store = state_store
        self._resource_lock = resource_lock

    async def apply_update(self, update: OperatingModelUpdate) -> bool:
        """Apply one newer immutable revision; return false for a safe no-op or rejection."""

        async with self._resource_lock.acquire(OPERATING_MODEL_LOCK_KEY):
            prior = _decode_cursor(await self._state_store.read_state(OPERATING_MODEL_CURSOR_KEY))
            snapshot_digest = _snapshot_digest(update)
            revision_key = _revision_key(update.snapshot.source_revision)
            revision_claim = await self._state_store.read_state(revision_key)
            if revision_claim is not None:
                claimed_revision = _decode_revision_claim(revision_claim)
                if claimed_revision == (update.cursor, update.sequence, snapshot_digest):
                    if prior is not None and update.sequence <= prior[1]:
                        return False
                    await self._write_cursor(update)
                    return True
                await self._record_rejection(update, "source_revision_reused")
                return False
            if prior is not None and update.cursor == prior[0]:
                return False
            if prior is not None and update.sequence <= prior[1]:
                await self._record_rejection(update, "sequence_not_monotonic")
                return False
            if prior is not None and update.snapshot.source_revision == prior[2]:
                await self._record_rejection(update, "source_revision_reused")
                return False
            if await operating_model_projection_matches(
                status_store=self._state_store,
                source_revision=update.snapshot.source_revision,
                snapshot_digest=snapshot_digest,
            ):
                await self._write_revision_claim(
                    revision_key=revision_key,
                    update=update,
                    snapshot_digest=snapshot_digest,
                )
                await self._write_cursor(update)
                return True
            await project_operating_model_snapshot(
                snapshot=update.snapshot,
                store=self._store,
                object_types=self._object_types,
                link_types=self._link_types,
                status_store=self._state_store,
                snapshot_digest=snapshot_digest,
            )
            await self._write_revision_claim(
                revision_key=revision_key,
                update=update,
                snapshot_digest=snapshot_digest,
            )
            await self._write_cursor(update)
            return True

    async def run(self, stop: asyncio.Event) -> None:
        """Consume updates until supervised shutdown."""

        prior = _decode_cursor(await self._state_store.read_state(OPERATING_MODEL_CURSOR_KEY))
        after_cursor = prior[0] if prior is not None else None
        async for update in self._provider.updates(after_cursor=after_cursor, stop=stop):
            await self.apply_update(update)
            if stop.is_set():
                return

    async def _record_rejection(self, update: OperatingModelUpdate, reason: str) -> None:
        await self._state_store.write_state(
            OPERATING_MODEL_REJECTION_KEY,
            {
                "schema_version": "1.0.0",
                "cursor": update.cursor,
                "sequence": update.sequence,
                "source_revision": update.snapshot.source_revision,
                "reason": reason,
            },
        )

    async def _write_cursor(self, update: OperatingModelUpdate) -> None:
        await self._state_store.write_state(
            OPERATING_MODEL_CURSOR_KEY,
            {
                "schema_version": "1.0.0",
                "cursor": update.cursor,
                "sequence": update.sequence,
                "source_revision": update.snapshot.source_revision,
            },
        )

    async def _write_revision_claim(
        self,
        *,
        revision_key: str,
        update: OperatingModelUpdate,
        snapshot_digest: str,
    ) -> None:
        claim_written = await self._state_store.write_state_if_absent(
            revision_key,
            {
                "schema_version": "1.0.0",
                "cursor": update.cursor,
                "sequence": update.sequence,
                "snapshot_digest": snapshot_digest,
            },
        )
        if not claim_written:
            raise RuntimeError("continuous operating model revision claim raced its lock")


def _decode_cursor(raw: Mapping[str, object] | None) -> tuple[str, int, str] | None:
    if raw is None:
        return None
    cursor = raw.get("cursor")
    sequence = raw.get("sequence")
    source_revision = raw.get("source_revision")
    if (
        not isinstance(cursor, str)
        or not cursor
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or not isinstance(source_revision, str)
        or not source_revision
    ):
        raise RuntimeError("continuous operating model cursor state is malformed")
    return cursor, sequence, source_revision


def _revision_key(source_revision: str) -> str:
    digest = hashlib.sha256(source_revision.encode("utf-8")).hexdigest()
    return f"{OPERATING_MODEL_REVISION_KEY_PREFIX}{digest}"


def _snapshot_digest(update: OperatingModelUpdate) -> str:
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
        for item in sorted(update.snapshot.objects, key=lambda value: value.id)
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
            update.snapshot.links,
            key=lambda value: (value.from_id, value.link_type, value.to_id),
        )
    ]
    encoded = json.dumps(
        {
            "source_revision": update.snapshot.source_revision,
            "objects": objects,
            "links": links,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _decode_revision_claim(raw: Mapping[str, object]) -> tuple[str, int, str]:
    cursor = raw.get("cursor")
    sequence = raw.get("sequence")
    snapshot_digest = raw.get("snapshot_digest")
    if (
        not isinstance(cursor, str)
        or not cursor
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or not isinstance(snapshot_digest, str)
        or not snapshot_digest.startswith("sha256:")
        or len(snapshot_digest) != 71
    ):
        raise RuntimeError("continuous operating model revision claim is malformed")
    return cursor, sequence, snapshot_digest


def build_continuous_operating_model_worker(
    *,
    bus: EventBus,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    state_store: StateStore,
    environment: Mapping[str, str],
    resource_lock: ResourceLock | None = None,
) -> ContinuousOperatingModelWorker | None:
    """Compose the optional event-driven provider without changing graph authority."""

    topic = environment.get("FDAI_OPERATING_MODEL_TOPIC", "").strip()
    if not topic:
        return None
    if store is None:
        raise RuntimeError("FDAI_OPERATING_MODEL_TOPIC requires an ontology instance store")
    group_id = environment.get(
        "FDAI_OPERATING_MODEL_CONSUMER_GROUP_ID",
        "fdai-operating-model",
    ).strip()
    provider = EventBusOperatingModelProvider(
        bus=bus,
        config=EventBusOperatingModelProviderConfig(topic=topic, group_id=group_id),
    )
    if resource_lock is None:
        from fdai.runtime.providers import _build_resource_lock

        resource_lock = _build_resource_lock(environment)

    return ContinuousOperatingModelWorker(
        provider=provider,
        store=store,
        object_types=object_types,
        link_types=link_types,
        state_store=state_store,
        resource_lock=resource_lock,
    )


async def project_initial_operating_model_from_env(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    state_store: StateStore,
    environment: Mapping[str, str],
    resource_lock: ResourceLock,
) -> OperatingModelProjectionResult | None:
    """Project bootstrap state only before the continuous stream has advanced."""

    async with resource_lock.acquire(OPERATING_MODEL_LOCK_KEY):
        prior = _decode_cursor(await state_store.read_state(OPERATING_MODEL_CURSOR_KEY))
        if prior is not None:
            return None
        return await project_operating_model_from_env(
            store=store,
            object_types=object_types,
            link_types=link_types,
            status_store=state_store,
            env=environment,
        )


__all__ = [
    "OPERATING_MODEL_CURSOR_KEY",
    "OPERATING_MODEL_LOCK_KEY",
    "OPERATING_MODEL_REJECTION_KEY",
    "OPERATING_MODEL_REVISION_KEY_PREFIX",
    "ContinuousOperatingModelWorker",
    "build_continuous_operating_model_worker",
    "project_initial_operating_model_from_env",
]

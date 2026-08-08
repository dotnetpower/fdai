"""Runtime startup binding for deployment operating model instances."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from fdai.core.operational_context import (
    OperatingModelProjectionResult,
    OperatingModelProjector,
)
from fdai.delivery.operating_model import (
    JsonOperatingModelProvider,
    JsonOperatingModelProviderConfig,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.state_store import StateStore

OPERATING_MODEL_STATUS_KEY = "operating-model:status"
_OPERATING_MODEL_MANIFEST_KEY = "operating-model:manifest"
_MAX_OBJECTS = 50_000
_MAX_LINKS = 200_000


async def project_operating_model_from_env(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    status_store: StateStore | None = None,
    env: Mapping[str, str] | None = None,
) -> OperatingModelProjectionResult | None:
    values = env if env is not None else os.environ
    raw_path = values.get("FDAI_OPERATING_MODEL_PATH", "").strip()
    previous_object_ids: tuple[str, ...] = ()
    previous_link_keys: tuple[tuple[str, str, str], ...] = ()
    recovering_interrupted_apply = False
    if status_store is not None:
        prior_manifest = await status_store.read_state(_OPERATING_MODEL_MANIFEST_KEY)
        previous_object_ids, previous_link_keys = _decode_manifest(prior_manifest)
        recovering_interrupted_apply = (
            prior_manifest is not None and prior_manifest.get("status") == "applying"
        )
    if not raw_path:
        if store is not None and (previous_object_ids or previous_link_keys):
            await OperatingModelProjector(
                store=store,
                object_types=object_types,
                link_types=link_types,
            ).project(
                OperatingModelSnapshot(source_revision="unconfigured", objects=(), links=()),
                previous_object_ids=previous_object_ids,
                previous_link_keys=previous_link_keys,
            )
        if status_store is not None:
            await status_store.write_state(
                _OPERATING_MODEL_MANIFEST_KEY,
                {
                    "schema_version": "1.0.0",
                    "status": "unconfigured",
                    "source_revision": "unconfigured",
                    "object_ids": [],
                    "link_keys": [],
                },
            )
            await status_store.write_state(
                OPERATING_MODEL_STATUS_KEY,
                {"schema_version": "1.0.0", "status": "unconfigured"},
            )
        return None
    if store is None:
        raise RuntimeError("FDAI_OPERATING_MODEL_PATH requires an ontology instance store")
    if recovering_interrupted_apply:
        await OperatingModelProjector(
            store=store,
            object_types=object_types,
            link_types=link_types,
        ).project(
            OperatingModelSnapshot(source_revision="recovery-cleanup", objects=(), links=()),
            previous_object_ids=previous_object_ids,
            previous_link_keys=previous_link_keys,
        )
        previous_object_ids = ()
        previous_link_keys = ()
    raw_max_bytes = values.get("FDAI_OPERATING_MODEL_MAX_BYTES", "").strip()
    try:
        max_bytes = int(raw_max_bytes) if raw_max_bytes else 16 * 1024 * 1024
    except ValueError as exc:
        raise RuntimeError("FDAI_OPERATING_MODEL_MAX_BYTES MUST be an integer") from exc
    provider = JsonOperatingModelProvider(
        config=JsonOperatingModelProviderConfig(path=Path(raw_path), max_bytes=max_bytes)
    )
    snapshot = await provider.load()
    current_object_ids = tuple(item.id for item in snapshot.objects)
    current_link_keys = tuple((item.from_id, item.link_type, item.to_id) for item in snapshot.links)
    owned_object_ids = tuple(sorted(set(previous_object_ids) | set(current_object_ids)))
    owned_link_keys = tuple(sorted(set(previous_link_keys) | set(current_link_keys)))
    if len(owned_object_ids) > _MAX_OBJECTS * 2 or len(owned_link_keys) > _MAX_LINKS * 2:
        raise RuntimeError("operating model recovery ownership exceeds bounds")
    if status_store is not None:
        await status_store.write_state(
            _OPERATING_MODEL_MANIFEST_KEY,
            {
                "schema_version": "1.0.0",
                "status": "applying",
                "source_revision": snapshot.source_revision,
                "object_ids": list(owned_object_ids),
                "link_keys": [list(key) for key in owned_link_keys],
            },
        )
    result = await OperatingModelProjector(
        store=store,
        object_types=object_types,
        link_types=link_types,
    ).project(
        snapshot,
        previous_object_ids=owned_object_ids,
        previous_link_keys=owned_link_keys,
    )
    if status_store is not None:
        await status_store.write_state(
            _OPERATING_MODEL_MANIFEST_KEY,
            {
                "schema_version": "1.0.0",
                "status": "projected",
                "source_revision": result.source_revision,
                "object_ids": list(current_object_ids),
                "link_keys": [list(key) for key in current_link_keys],
            },
        )
        await status_store.write_state(
            OPERATING_MODEL_STATUS_KEY,
            {
                "schema_version": "1.0.0",
                "status": "projected",
                "source_revision": result.source_revision,
                "object_count": result.object_count,
                "link_count": result.link_count,
            },
        )
    return result


def _decode_manifest(
    raw: Mapping[str, object] | None,
) -> tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    if raw is None:
        return (), ()
    raw_ids = raw.get("object_ids")
    raw_links = raw.get("link_keys")
    if not isinstance(raw_ids, list) or not isinstance(raw_links, list):
        raise RuntimeError("operating model manifest is malformed")
    status = raw.get("status")
    if status not in {"applying", "projected", "unconfigured"}:
        raise RuntimeError("operating model manifest status is malformed")
    recovery_multiplier = 2 if status == "applying" else 1
    if (
        len(raw_ids) > _MAX_OBJECTS * recovery_multiplier
        or len(raw_links) > _MAX_LINKS * recovery_multiplier
    ):
        raise RuntimeError("operating model manifest exceeds object/link bounds")
    if any(not isinstance(item, str) or not item for item in raw_ids):
        raise RuntimeError("operating model manifest object_ids are malformed")
    links: list[tuple[str, str, str]] = []
    for item in raw_links:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or any(not isinstance(value, str) or not value for value in item)
        ):
            raise RuntimeError("operating model manifest link_keys are malformed")
        links.append((item[0], item[1], item[2]))
    return tuple(raw_ids), tuple(links)


__all__ = ["OPERATING_MODEL_STATUS_KEY", "project_operating_model_from_env"]

"""Bounded exact-release replay of the active inventory ontology projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any, Protocol

from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventoryProjectionReplayInput,
    PostgresInventoryObservationJournal,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import resource_type_mapping_digests
from fdai.runtime.inventory_ontology import (
    INVENTORY_ONTOLOGY_MANIFEST_KEY,
    InventoryOntologyProjectionResult,
    InventoryOntologyProjectionStatus,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPLAY_TIMEOUT_SECONDS = 300


class ProjectionReplayProjector(Protocol):
    """Projection method needed by one bounded replay."""

    async def apply(
        self,
        observation: PromotedInventoryObservation,
        *,
        journal_high_watermark: int | None = None,
        projection_high_watermark: int | None = None,
        fail_before_incomplete_status: bool = False,
    ) -> InventoryOntologyProjectionResult: ...


class ProjectionManifestReader(Protocol):
    """Read-only state surface used for independent replay verification."""

    async def read_state(self, key: str) -> Any: ...


async def run_once(
    replay: InventoryProjectionReplayInput,
    *,
    projector: ProjectionReplayProjector,
    state: ProjectionManifestReader,
    source_revision: str,
) -> dict[str, object]:
    """Replay one immutable active generation and verify the committed release."""

    if _SHA40.fullmatch(source_revision) is None:
        raise ValueError("inventory projection replay source revision must be a git SHA")
    before = await state.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    before_objects, before_links, prior_release = _comparable_manifest(before, replay)
    result = await projector.apply(
        replay.observation,
        journal_high_watermark=replay.journal_high_watermark,
        projection_high_watermark=replay.projection_high_watermark,
        fail_before_incomplete_status=True,
    )
    if result.status is not InventoryOntologyProjectionStatus.AVAILABLE or not result.complete:
        raise ValueError("inventory projection replay did not produce complete evidence")
    if result.object_count != before_objects or result.link_count != before_links:
        raise ValueError("inventory projection replay content counts changed")
    manifest = await state.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    if not isinstance(manifest, Mapping):
        raise ValueError("inventory projection replay manifest is unavailable")
    if (
        manifest.get("generation") != replay.observation.generation
        or manifest.get("ontology_release_digest") != result.ontology_release_digest
        or manifest.get("complete") is not True
    ):
        raise ValueError("inventory projection replay manifest verification failed")
    return {
        "schema_version": "1.0.0",
        "source_revision_digest": _text_digest(source_revision),
        "generation_digest": _text_digest(replay.observation.generation),
        "prior_ontology_release_digest": prior_release,
        "ontology_release_digest": result.ontology_release_digest,
        "ontology_release_changed": prior_release != result.ontology_release_digest,
        "object_count": result.object_count,
        "link_count": result.link_count,
        "journal_high_watermark": replay.journal_high_watermark,
        "projection_high_watermark": replay.projection_high_watermark,
        "complete": True,
    }


async def _run_from_env(source_revision: str, environ: Mapping[str, str]) -> dict[str, object]:
    dsn = (
        environ.get("FDAI_STATE_STORE_DSN", "").strip()
        or environ.get("FDAI_DATABASE_URL", "").strip()
    )
    if not dsn:
        raise ValueError("inventory projection replay requires a database URL")
    catalog_root = repo_asset_root() / "rule-catalog"
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=catalog_root / "probes",
    )
    vocabulary = load_resource_type_registry()
    state = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    ontology_store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn=dsn),
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    journal = PostgresInventoryObservationJournal(
        config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
    )
    replay = await journal.load_active_projection_replay()
    await ontology_store.sync_catalog()
    projector = InventoryOntologyProjector(
        store=ontology_store,
        status_store=state,
        ontology_release_digest=catalog.build_release().digest,
        resource_type_mappings=resource_type_mapping_digests(vocabulary),
        freshness_ceiling_seconds=replay.freshness_ceiling_seconds,
        projection_lock=PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn=dsn,
                lock_timeout_ms=30_000,
            )
        ),
        observation_journal=journal,
    )
    return await run_once(
        replay,
        projector=projector,
        state=state,
        source_revision=source_revision,
    )


def main() -> None:
    """Run one deadline-bounded projection replay from a Container Apps Job."""

    if len(sys.argv) != 2:
        raise ValueError("inventory projection replay requires one exact source revision")
    result = asyncio.run(
        asyncio.wait_for(
            _run_from_env(sys.argv[1], os.environ),
            timeout=_REPLAY_TIMEOUT_SECONDS,
        )
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _comparable_manifest(
    value: object,
    replay: InventoryProjectionReplayInput,
) -> tuple[int, int, str]:
    if not isinstance(value, Mapping):
        raise ValueError("inventory projection replay pre-manifest is unavailable")
    object_content = value.get("object_content")
    link_content = value.get("link_content")
    prior_release = value.get("ontology_release_digest")
    if (
        value.get("generation") != replay.observation.generation
        or _DIGEST.fullmatch(str(value.get("manifest_digest", ""))) is None
        or not isinstance(prior_release, str)
        or _DIGEST.fullmatch(prior_release) is None
        or not isinstance(object_content, list)
        or not isinstance(link_content, list)
        or value.get("complete") is not True
        or value.get("journal_high_watermark") != replay.journal_high_watermark
        or value.get("projection_high_watermark") != replay.projection_high_watermark
    ):
        raise ValueError("inventory projection replay pre-manifest is not comparable")
    return len(object_content), len(link_content), prior_release


__all__ = ["ProjectionManifestReader", "ProjectionReplayProjector", "main", "run_once"]

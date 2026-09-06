"""Focused tests for bounded active inventory projection replay."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.inventory_projection_replay_cli import run_once
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventoryProjectionReplayInput,
)
from fdai.runtime.inventory_ontology import (
    INVENTORY_ONTOLOGY_MANIFEST_KEY,
    InventoryOntologyProjectionResult,
    InventoryOntologyProjectionStatus,
)
from fdai.shared.providers.inventory import ResourceRecord

REVISION = "a" * 40
RELEASE = "sha256:" + "b" * 64
NOW = datetime(2026, 9, 6, tzinfo=UTC)


class _Projector:
    def __init__(self, result: InventoryOntologyProjectionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, int | None, int | None]] = []

    async def apply(
        self,
        observation: PromotedInventoryObservation,
        *,
        journal_high_watermark: int | None = None,
        projection_high_watermark: int | None = None,
        fail_before_incomplete_status: bool = False,
    ) -> InventoryOntologyProjectionResult:
        assert fail_before_incomplete_status is True
        self.calls.append(
            (observation.generation, journal_high_watermark, projection_high_watermark)
        )
        return self.result


class _State:
    def __init__(self, manifest: object, after: object | None = None) -> None:
        self.manifest = manifest
        self.after = manifest if after is None else after
        self.reads = 0

    async def read_state(self, key: str) -> object:
        assert key == INVENTORY_ONTOLOGY_MANIFEST_KEY
        self.reads += 1
        return self.manifest if self.reads == 1 else self.after


def _replay() -> InventoryProjectionReplayInput:
    return InventoryProjectionReplayInput(
        observation=PromotedInventoryObservation(
            generation="snapshot-active",
            resources=(
                ResourceRecord(
                    resource_id="resource-a",
                    type="compute.vm",
                    props={"state": "ready"},
                    last_seen=NOW.isoformat(),
                ),
            ),
            links=(),
            complete=True,
            recorded_at=NOW,
        ),
        journal_high_watermark=17,
        projection_high_watermark=17,
        freshness_ceiling_seconds=21_600,
    )


def _result() -> InventoryOntologyProjectionResult:
    return InventoryOntologyProjectionResult(
        generation="snapshot-active",
        ontology_release_digest=RELEASE,
        status=InventoryOntologyProjectionStatus.AVAILABLE,
        object_count=1,
        link_count=0,
        complete=True,
        relationship_complete=True,
        dropped_reasons=(),
        journal_high_watermark=17,
        projection_high_watermark=17,
    )


def _manifest(release: str = RELEASE) -> dict[str, object]:
    return {
        "generation": "snapshot-active",
        "ontology_release_digest": release,
        "manifest_digest": "sha256:" + "d" * 64,
        "complete": True,
        "object_content": [{"id": "resource-a"}],
        "link_content": [],
        "journal_high_watermark": 17,
        "projection_high_watermark": 17,
    }


async def test_replay_verifies_exact_release_and_watermark_fence() -> None:
    replay = _replay()
    projector = _Projector(_result())
    prior_release = "sha256:" + "c" * 64
    state = _State(_manifest(prior_release), _manifest())

    summary = await run_once(
        replay,
        projector=projector,
        state=state,
        source_revision=REVISION,
    )

    assert projector.calls == [("snapshot-active", 17, 17)]
    assert summary["prior_ontology_release_digest"] == prior_release
    assert summary["ontology_release_digest"] == RELEASE
    assert summary["ontology_release_changed"] is True
    assert summary["complete"] is True


async def test_replay_refuses_unverified_manifest_or_source() -> None:
    replay = _replay()
    projector = _Projector(_result())
    with pytest.raises(ValueError, match="source revision"):
        await run_once(
            replay,
            projector=projector,
            state=_State({}),
            source_revision="not-a-revision",
        )
    with pytest.raises(ValueError, match="manifest verification"):
        await run_once(
            replay,
            projector=projector,
            state=_State(_manifest(), _manifest("sha256:" + "c" * 64)),
            source_revision=REVISION,
        )

"""Fail-closed inventory synchronization and fallback tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from fdai.delivery.inventory_sync import InventoryStreamError, InventorySyncCoordinator
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySource,
    InventorySourcesExhaustedError,
)


@dataclass
class _Store:
    batches: dict[str, list[InventoryBatch]] = field(default_factory=dict)
    promoted: list[str] = field(default_factory=list)
    failed: list[tuple[str, InventoryAttemptFailure]] = field(default_factory=list)
    sequence: int = 0

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        self.sequence += 1
        attempt = f"attempt-{self.sequence}"
        self.batches[attempt] = []
        return attempt

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        self.batches[attempt_id].append(batch)

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        self.promoted.append(attempt_id)

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        self.failed.append((attempt_id, failure))


class _Inventory:
    def __init__(self, batches: list[InventoryBatch] | None = None, error: Exception | None = None):
        self._batches = batches or []
        self._error = error

    async def full_snapshot(self, since: str | None = None):
        del since
        for batch in self._batches:
            yield batch
        if self._error is not None:
            raise self._error

    async def delta(self, cursor: str):
        del cursor
        yield InventoryBatch(final=True)


def _source(name: str, inventory: Any) -> InventorySource:
    return InventorySource(
        name=name,
        inventory=inventory,
        manifest=InventoryCoverageManifest(
            source=name,
            scopes=("scope-1",),
            resource_types=("compute.vm",),
        ),
    )


async def test_complete_stream_promotes_terminal_records() -> None:
    store = _Store()
    resource = ResourceRecord(resource_id="vm-1", type="compute.vm")
    result = await InventorySyncCoordinator(store=store).run(
        [_source("arg", _Inventory([InventoryBatch(resources=(resource,), final=True)]))]
    )
    assert result.source == "arg"
    assert store.promoted == ["attempt-1"]
    assert store.batches["attempt-1"][0].resources == (resource,)
    assert store.batches["attempt-1"][0].final is False


async def test_missing_fence_falls_back_without_promotion() -> None:
    store = _Store()
    result = await InventorySyncCoordinator(store=store).run(
        [
            _source("arg", _Inventory([InventoryBatch()])),
            _source("arm", _Inventory([InventoryBatch(final=True)])),
        ]
    )
    assert result.source == "arm"
    assert result.failures[0].code is InventoryFailureCode.PARTIAL
    assert store.promoted == ["attempt-2"]


async def test_data_after_fence_is_rejected() -> None:
    store = _Store()
    with pytest.raises(InventorySourcesExhaustedError) as error:
        await InventorySyncCoordinator(store=store).run(
            [
                _source(
                    "arg",
                    _Inventory([InventoryBatch(final=True), InventoryBatch(resources=())]),
                )
            ]
        )
    assert error.value.failures[0].code is InventoryFailureCode.PARTIAL
    assert isinstance(InventoryStreamError("example"), RuntimeError)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectTimeout("blocked"), InventoryFailureCode.NETWORK_BLOCKED),
        (RuntimeError("ARG returned HTTP 403"), InventoryFailureCode.FORBIDDEN),
        (RuntimeError("ARG returned HTTP 429"), InventoryFailureCode.THROTTLED),
        (RuntimeError("pagination cap exceeded"), InventoryFailureCode.PARTIAL),
    ],
)
async def test_failure_classification_drives_fallback(
    error: Exception, code: InventoryFailureCode
) -> None:
    store = _Store()
    result = await InventorySyncCoordinator(store=store).run(
        [
            _source("arg", _Inventory(error=error)),
            _source("arm", _Inventory([InventoryBatch(final=True)])),
        ]
    )
    assert result.failures[0].code is code

"""Resume durable staging only while a full source replay independently verifies coverage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from fdai.delivery.inventory_collection import (
    InventoryStreamError,
    _resource_content,
    collection_configuration_digest,
)
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventoryCoverageManifest


@dataclass(slots=True)
class ResumedInventoryCollection:
    """A bounded original prefix, not permission to skip provider reads or assert absence."""

    attempt_id: str
    manifest: InventoryCoverageManifest
    checkpoint: Mapping[str, Any]
    resources: dict[str, ResourceRecord]
    seen: set[str] = field(default_factory=set)

    def revalidate(self, batch: InventoryBatch) -> tuple[InventoryBatch, InventoryBatch]:
        observed = []
        additional = []
        for resource in batch.resources:
            previous = self.resources.get(resource.resource_id)
            if previous is None:
                observed.append(resource)
                additional.append(resource)
                continue
            before, after = _resource_content(previous), _resource_content(resource)
            before.pop("last_seen")
            after.pop("last_seen")
            if collection_configuration_digest(before) != collection_configuration_digest(after):
                raise InventoryStreamError("inventory resumed resource content changed")
            if previous.last_seen is not None:
                if resource.last_seen is None or datetime.fromisoformat(
                    resource.last_seen.replace("Z", "+00:00")
                ) < datetime.fromisoformat(previous.last_seen.replace("Z", "+00:00")):
                    raise InventoryStreamError("inventory resumed observation clock regressed")
            self.seen.add(resource.resource_id)
            observed.append(previous)
        if batch.final and self.seen != self.resources.keys():
            raise InventoryStreamError("inventory resumed identity coverage is incomplete")
        return replace(batch, resources=tuple(observed)), InventoryBatch(
            resources=tuple(additional), cursor=batch.cursor
        )

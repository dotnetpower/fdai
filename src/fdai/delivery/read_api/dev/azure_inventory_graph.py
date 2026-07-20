"""Cached local inventory graph backed by the operator's Azure CLI login."""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from fdai.delivery.read_api.routes.architecture_views import project_architecture_graph
from fdai.shared.providers.inventory import Inventory, ResourceRecord

_ROOT_ID = "azure-subscription"


@dataclass(slots=True)
class AzureCliInventoryGraphProvider:
    """Project a complete local Azure CLI snapshot into the console graph wire."""

    inventory: Inventory
    cache_ttl_seconds: float = 60.0
    max_resources: int = 120
    _cached: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _cached_at: float = field(default=0.0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds MUST be >= 0")
        if self.max_resources < 1:
            raise ValueError("max_resources MUST be positive")

    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
    ) -> dict[str, Any]:
        del depth
        graph = await self._graph()
        projection = project_architecture_graph(
            resources=graph["resources"],
            links=graph["links"],
            requested_view=scope,
        )
        payload = {
            **graph,
            **projection,
            "links": [dict(link) for link in projection["links"] if link["type"] in link_types],
        }
        return payload

    async def _graph(self) -> dict[str, Any]:
        now = monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_ttl_seconds:
            return self._cached
        async with self._lock:
            now = monotonic()
            if self._cached is not None and now - self._cached_at < self.cache_ttl_seconds:
                return self._cached
            records: list[ResourceRecord] = []
            final_seen = False
            cursor: str | None = None
            async for batch in self.inventory.full_snapshot():
                cursor = batch.cursor
                if batch.final:
                    final_seen = True
                    continue
                records.extend(batch.resources)
            if not final_seen:
                raise RuntimeError("local Azure inventory ended without a final fence")
            graph = _project_graph(records, max_resources=self.max_resources, cursor=cursor)
            self._cached = graph
            self._cached_at = monotonic()
            return graph


def _project_graph(
    records: list[ResourceRecord],
    *,
    max_resources: int,
    cursor: str | None,
) -> dict[str, Any]:
    ordered = sorted(
        records,
        key=lambda record: (
            record.type != "resource-group",
            str(record.props.get("resourceGroup") or "").lower(),
            str(record.props.get("name") or record.resource_id).lower(),
        ),
    )
    truncated = len(ordered) > max_resources
    selected = ordered[:max_resources]
    groups = [record for record in selected if record.type == "resource-group"]
    group_ids = {
        str(record.props.get("name") or record.resource_id).lower(): record.resource_id
        for record in groups
    }
    children: dict[str, list[ResourceRecord]] = defaultdict(list)
    ungrouped: list[ResourceRecord] = []
    for record in selected:
        if record.type == "resource-group":
            continue
        group_name = str(record.props.get("resourceGroup") or "").lower()
        parent_id = group_ids.get(group_name)
        if parent_id is None:
            ungrouped.append(record)
        else:
            children[parent_id].append(record)

    group_columns = min(6, max(1, math.ceil(math.sqrt(max(1, len(groups))))))
    group_rows = max(1, math.ceil(len(groups) / group_columns))
    root_width = 17.3
    root_height = 11.3
    group_gap = 0.12
    group_width = (root_width - 0.6 - (group_columns - 1) * group_gap) / group_columns
    group_height = (root_height - 0.9 - (group_rows - 1) * group_gap) / group_rows

    resources: list[dict[str, Any]] = [
        {
            "id": _ROOT_ID,
            "type": "subscription",
            "name": "Azure CLI subscription",
            "status": "unknown",
            "x": 0.25,
            "y": 0.25,
            "w": root_width,
            "h": root_height,
            "props": {},
        }
    ]
    links: list[dict[str, str]] = []
    for index, group in enumerate(groups):
        column = index % group_columns
        row = index // group_columns
        x = 0.65 + column * (group_width + group_gap)
        y = 1.0 + row * (group_height + group_gap)
        resources.append(
            _resource_payload(
                group,
                parent_id=_ROOT_ID,
                x=x,
                y=y,
                width=group_width,
                height=group_height,
            )
        )
        links.append({"source": _ROOT_ID, "target": group.resource_id, "type": "contains"})
        group_children = children[group.resource_id]
        child_columns = min(3, max(1, math.ceil(math.sqrt(max(1, len(group_children))))))
        child_rows = max(1, math.ceil(len(group_children) / child_columns))
        child_width = max(0.25, (group_width - 0.3) / child_columns)
        child_height = max(0.2, (group_height - 0.45) / child_rows)
        for child_index, child in enumerate(group_children):
            child_x = x + 0.15 + (child_index % child_columns + 0.5) * child_width
            child_y = y + 0.35 + (child_index // child_columns + 0.5) * child_height
            resources.append(
                _resource_payload(child, parent_id=group.resource_id, x=child_x, y=child_y)
            )
            links.append(
                {"source": group.resource_id, "target": child.resource_id, "type": "contains"}
            )

    for index, resource in enumerate(ungrouped):
        resources.append(
            _resource_payload(
                resource,
                parent_id=_ROOT_ID,
                x=0.8 + (index % 6) * 2.2,
                y=root_height - 0.45,
            )
        )
        links.append({"source": _ROOT_ID, "target": resource.resource_id, "type": "contains"})

    return {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "freshness": "fresh",
        "source": "azure-cli-local",
        "resources": resources,
        "links": links,
        "truncated": truncated,
        "cursor": cursor,
    }


def _resource_payload(
    record: ResourceRecord,
    *,
    parent_id: str,
    x: float,
    y: float,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record.resource_id,
        "type": record.type,
        "name": str(record.props.get("name") or record.resource_id),
        "status": "unknown",
        "parent_id": parent_id,
        "props": dict(record.props),
        "x": x,
        "y": y,
    }
    if width is not None:
        payload["w"] = width
    if height is not None:
        payload["h"] = height
    return payload


__all__ = ["AzureCliInventoryGraphProvider"]

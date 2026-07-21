"""Cached local inventory graph backed by the operator's Azure CLI login."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import stat
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Final, TypeGuard

from fdai.core.views.architecture_graph import project_architecture_graph
from fdai.delivery.inventory_cache_invalidation import (
    inventory_cache_path,
    inventory_invalidation_path,
)
from fdai.shared.providers.inventory import Inventory, ResourceRecord

_ROOT_ID = "azure-subscription"
_LOGGER = logging.getLogger(__name__)
_CACHE_VERSION: Final[int] = 2
_MAX_CACHE_BYTES: Final[int] = 5_000_000
_MAX_CLOCK_SKEW_SECONDS: Final[int] = 300


@dataclass(slots=True)
class AzureCliInventoryGraphProvider:
    """Project a complete local Azure CLI snapshot into the console graph wire."""

    inventory: Inventory
    cache_ttl_seconds: float = 60.0
    refresh_timeout_seconds: float = 240.0
    max_resources: int = 120
    cache_path: Path | None = None
    cache_identity: str | None = None
    invalidation_path: Path | None = None
    _cached: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _cached_at: float = field(default=0.0, init=False, repr=False)
    _cached_at_utc: datetime | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _refresh_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _persistent_loaded: bool = field(default=False, init=False, repr=False)
    _last_refresh_failed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds MUST be >= 0")
        if self.refresh_timeout_seconds <= 0:
            raise ValueError("refresh_timeout_seconds MUST be positive")
        if self.max_resources < 1:
            raise ValueError("max_resources MUST be positive")
        if (self.cache_path is None) != (self.cache_identity is None):
            raise ValueError("cache_path and cache_identity MUST be configured together")

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
        await self._load_persistent_cache()
        now = monotonic()
        invalidated = await asyncio.to_thread(self._cache_invalidated)
        if (
            self._cached is not None
            and not invalidated
            and now - self._cached_at < self.cache_ttl_seconds
        ):
            return self._cache_payload(status="fresh")
        if self._cached is not None:
            self._schedule_refresh()
            return self._cache_payload(
                status="stale" if self._last_refresh_failed else "refreshing"
            )
        return await self._refresh()

    async def _refresh(self, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            now = monotonic()
            if (
                not force
                and self._cached is not None
                and now - self._cached_at < self.cache_ttl_seconds
            ):
                return self._cache_payload(status="fresh")
            refresh_started_at = datetime.now(tz=UTC)
            records: list[ResourceRecord] = []
            final_seen = False
            cursor: str | None = None
            async with asyncio.timeout(self.refresh_timeout_seconds):
                async for batch in self.inventory.full_snapshot():
                    if final_seen:
                        raise RuntimeError(
                            "local Azure inventory emitted data after its final fence"
                        )
                    cursor = batch.cursor
                    if batch.final:
                        final_seen = True
                        continue
                    records.extend(batch.resources)
            if not final_seen:
                raise RuntimeError("local Azure inventory ended without a final fence")
            graph = _project_graph(records, max_resources=self.max_resources, cursor=cursor)
            if not _valid_cached_graph(graph, self.max_resources):
                raise RuntimeError("local Azure inventory projected an invalid graph")
            self._cached = graph
            self._cached_at = monotonic()
            self._cached_at_utc = refresh_started_at
            self._last_refresh_failed = False
            await self._write_persistent_cache()
            if await asyncio.to_thread(self._cache_invalidated):
                if asyncio.current_task() is not self._refresh_task:
                    self._schedule_refresh()
                return self._cache_payload(status="refreshing")
            return self._cache_payload(status="fresh")

    def _schedule_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(
            self._refresh_in_background(),
            name="azure-cli-inventory-refresh",
        )

    async def _refresh_in_background(self) -> None:
        try:
            refreshed = await self._refresh(force=True)
            if refreshed["cache"]["status"] == "refreshing":
                await self._refresh(force=True)
        except Exception as exc:  # noqa: BLE001 - preserve the last complete snapshot
            self._last_refresh_failed = True
            _LOGGER.warning(
                "azure_cli_inventory_background_refresh_failed",
                extra={"error_type": type(exc).__name__},
            )

    async def wait_for_refresh(self) -> None:
        """Wait for a scheduled refresh; intended for tests and lifecycle hooks."""
        task = self._refresh_task
        if task is not None:
            await task

    async def _load_persistent_cache(self) -> None:
        if self._persistent_loaded:
            return
        async with self._lock:
            if self._persistent_loaded:
                return
            if self.cache_path is not None and self.cache_identity is not None:
                loaded = await asyncio.to_thread(
                    _read_cache_file,
                    self.cache_path,
                    self.cache_identity,
                    self.max_resources,
                )
                if loaded is not None:
                    graph, cached_at = loaded
                    self._cached = graph
                    self._cached_at_utc = cached_at
                    age = max(0.0, (datetime.now(tz=UTC) - cached_at).total_seconds())
                    self._cached_at = monotonic() - age
            self._persistent_loaded = True

    async def _write_persistent_cache(self) -> None:
        if (
            self.cache_path is None
            or self.cache_identity is None
            or self._cached is None
            or self._cached_at_utc is None
        ):
            return
        try:
            await asyncio.to_thread(
                _write_cache_file,
                self.cache_path,
                self.cache_identity,
                self.max_resources,
                self._cached_at_utc,
                self._cached,
            )
        except (OSError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "azure_cli_inventory_cache_write_failed",
                extra={"error_type": type(exc).__name__},
            )

    def _cache_payload(self, *, status: str) -> dict[str, Any]:
        if self._cached is None:
            raise RuntimeError("inventory cache is empty")
        cached_at = self._cached_at_utc or datetime.now(tz=UTC)
        age_seconds = max(0, int((datetime.now(tz=UTC) - cached_at).total_seconds()))
        freshness = self._cached.get("freshness", "unknown")
        if status != "fresh" and freshness == "fresh":
            freshness = "stale"
        return {
            **self._cached,
            "freshness": freshness,
            "cache": {
                "status": status,
                "age_seconds": age_seconds,
                "persistent": self.cache_path is not None,
            },
        }

    def _cache_invalidated(self) -> bool:
        if self.invalidation_path is None or self._cached_at_utc is None:
            return False
        try:
            return self.invalidation_path.stat().st_mtime > self._cached_at_utc.timestamp()
        except FileNotFoundError:
            return False
        except OSError as exc:
            _LOGGER.warning(
                "azure_cli_inventory_invalidation_check_failed",
                extra={"error_type": type(exc).__name__},
            )
            return True


def _read_cache_file(
    path: Path,
    identity: str,
    max_resources: int,
) -> tuple[dict[str, Any], datetime] | None:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o077
            or metadata.st_size > _MAX_CACHE_BYTES
        ):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            encoded = stream.read(_MAX_CACHE_BYTES + 1)
        if len(encoded) > _MAX_CACHE_BYTES:
            return None
        payload = json.loads(encoded)
        if (
            not isinstance(payload, dict)
            or payload.get("version") != _CACHE_VERSION
            or payload.get("identity") != identity
            or payload.get("max_resources") != max_resources
            or not isinstance(payload.get("graph"), dict)
        ):
            return None
        graph = payload["graph"]
        if not _valid_cached_graph(graph, max_resources):
            return None
        cached_at = datetime.fromisoformat(str(payload.get("cached_at")))
        if cached_at.tzinfo is None:
            return None
        cached_at_utc = cached_at.astimezone(UTC)
        if (cached_at_utc - datetime.now(tz=UTC)).total_seconds() > _MAX_CLOCK_SKEW_SECONDS:
            return None
        return graph, cached_at_utc
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_cache_file(
    path: Path,
    identity: str,
    max_resources: int,
    cached_at: datetime,
    graph: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    payload = {
        "version": _CACHE_VERSION,
        "identity": identity,
        "max_resources": max_resources,
        "cached_at": cached_at.isoformat(),
        "graph": graph,
    }
    encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > _MAX_CACHE_BYTES:
        raise ValueError("inventory cache exceeds the maximum serialized size")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _valid_cached_graph(graph: Mapping[str, Any], max_resources: int) -> bool:
    resources = graph.get("resources")
    links = graph.get("links")
    if not isinstance(resources, list) or not isinstance(links, list):
        return False
    if (
        not resources
        or len(resources) > max_resources + 1
        or len(links) > max_resources
        or graph.get("source") != "azure-cli-local"
        or graph.get("freshness") != "fresh"
        or not isinstance(graph.get("truncated"), bool)
        or not _valid_timestamp(graph.get("snapshot_at"))
    ):
        return False
    resource_ids: set[str] = set()
    parent_by_id: dict[str, str] = {}
    root: Mapping[str, Any] | None = None
    for resource in resources:
        if not isinstance(resource, dict) or not _valid_resource(resource):
            return False
        resource_id = resource["id"]
        if resource_id in resource_ids:
            return False
        resource_ids.add(resource_id)
        if resource_id == _ROOT_ID:
            root = resource
        if isinstance(resource.get("parent_id"), str):
            parent_by_id[resource_id] = resource["parent_id"]
    if (
        root is None
        or root.get("type") != "subscription"
        or root.get("parent_id") is not None
        or any(parent not in resource_ids for parent in parent_by_id.values())
        or _has_parent_cycle(resource_ids, parent_by_id)
    ):
        return False
    link_ids: set[tuple[str, str, str]] = set()
    for link in links:
        if not isinstance(link, dict):
            return False
        source = link.get("source")
        target = link.get("target")
        link_type = link.get("type")
        if (
            not isinstance(source, str)
            or not isinstance(target, str)
            or not isinstance(link_type, str)
            or link_type not in {"contains", "attached_to", "depends_on"}
            or source == target
            or source not in resource_ids
            or target not in resource_ids
        ):
            return False
        identity = (source, link_type, target)
        if identity in link_ids:
            return False
        link_ids.add(identity)
    return True


def _valid_resource(resource: Mapping[str, Any]) -> bool:
    if (
        not isinstance(resource.get("id"), str)
        or not resource["id"]
        or not isinstance(resource.get("type"), str)
        or not resource["type"]
        or not isinstance(resource.get("name"), str)
        or not isinstance(resource.get("status"), str)
    ):
        return False
    parent_id = resource.get("parent_id")
    if parent_id is not None and (not isinstance(parent_id, str) or not parent_id):
        return False
    x = resource.get("x")
    y = resource.get("y")
    width = resource.get("w")
    height = resource.get("h")
    if not _finite_number(x) or not 0 <= x <= 18:
        return False
    if not _finite_number(y) or not 0 <= y <= 12:
        return False
    if width is not None and (not _finite_number(width) or not 0 < width <= 18):
        return False
    if height is not None and (not _finite_number(height) or not 0 < height <= 12):
        return False
    if width is not None and x + width > 18:
        return False
    return not (height is not None and y + height > 12)


def _finite_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and (parsed.astimezone(UTC) - datetime.now(tz=UTC)).total_seconds()
        <= _MAX_CLOCK_SKEW_SECONDS
    )


def _has_parent_cycle(resource_ids: set[str], parent_by_id: Mapping[str, str]) -> bool:
    for resource_id in resource_ids:
        visited: set[str] = set()
        current: str | None = resource_id
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            current = parent_by_id.get(current)
    return False


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
    power_state = record.props.get("powerState")
    provisioning_state = record.props.get("provisioningState")
    status = str(power_state or provisioning_state or "unknown")
    payload: dict[str, Any] = {
        "id": record.resource_id,
        "type": record.type,
        "name": str(record.props.get("name") or record.resource_id),
        "status": status,
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


__all__ = [
    "AzureCliInventoryGraphProvider",
    "inventory_cache_path",
    "inventory_invalidation_path",
]

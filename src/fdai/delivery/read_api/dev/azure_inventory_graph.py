"""Cached local inventory graph backed by the operator's Azure CLI login."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Final

from fdai.core.views.architecture_graph import project_architecture_graph
from fdai.shared.providers.inventory import Inventory, ResourceRecord

_ROOT_ID = "azure-subscription"
_LOGGER = logging.getLogger(__name__)
_CACHE_VERSION: Final[int] = 2
_MAX_CACHE_BYTES: Final[int] = 5_000_000
_MAX_CLOCK_SKEW_SECONDS: Final[int] = 300


def inventory_cache_path(
    *,
    repo_root: Path,
    subscription_id: str,
    azure_config_dir: str | None,
) -> tuple[Path, str]:
    """Return a non-identifying cache path and its account-scope fingerprint."""
    normalized_subscription = subscription_id.strip()
    if not normalized_subscription:
        raise ValueError("subscription_id MUST NOT be empty")
    profile = (
        str(Path(azure_config_dir).expanduser().resolve(strict=False))
        if azure_config_dir
        else "<default>"
    )
    fingerprint = hashlib.sha256(f"{profile}\0{normalized_subscription}".encode()).hexdigest()
    return repo_root / ".fdai" / "cache" / "inventory" / f"{fingerprint}.json", fingerprint


def inventory_invalidation_path(cache_path: Path) -> Path:
    """Return the marker path paired with one account-scoped cache file."""
    return cache_path.with_suffix(".invalidated")


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
            return self.invalidation_path.stat().st_mtime >= self._cached_at_utc.timestamp()
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
    try:
        if not path.is_file() or path.stat().st_size > _MAX_CACHE_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != _CACHE_VERSION
            or payload.get("identity") != identity
            or payload.get("max_resources") != max_resources
            or not isinstance(payload.get("graph"), dict)
        ):
            return None
        graph = payload["graph"]
        if not _valid_cached_graph(graph):
            return None
        cached_at = datetime.fromisoformat(str(payload.get("cached_at")))
        if cached_at.tzinfo is None:
            return None
        cached_at_utc = cached_at.astimezone(UTC)
        if (cached_at_utc - datetime.now(tz=UTC)).total_seconds() > _MAX_CLOCK_SKEW_SECONDS:
            return None
        return graph, cached_at_utc
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_cache_file(
    path: Path,
    identity: str,
    max_resources: int,
    cached_at: datetime,
    graph: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "version": _CACHE_VERSION,
        "identity": identity,
        "max_resources": max_resources,
        "cached_at": cached_at.isoformat(),
        "graph": graph,
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _valid_cached_graph(graph: Mapping[str, Any]) -> bool:
    resources = graph.get("resources")
    links = graph.get("links")
    if not isinstance(resources, list) or not isinstance(links, list):
        return False
    if not all(
        isinstance(resource, dict)
        and isinstance(resource.get("id"), str)
        and bool(resource["id"])
        and isinstance(resource.get("type"), str)
        and isinstance(resource.get("name"), str)
        for resource in resources
    ):
        return False
    return all(
        isinstance(link, dict)
        and isinstance(link.get("source"), str)
        and isinstance(link.get("target"), str)
        and link.get("type") in {"contains", "attached_to", "depends_on"}
        for link in links
    )


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

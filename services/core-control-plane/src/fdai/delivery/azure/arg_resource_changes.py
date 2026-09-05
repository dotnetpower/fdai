"""Azure Resource Graph ``resourcechanges`` freshness accelerator.

Polls the ARG ``resourcechanges`` table (Create/Update/Delete change
records) with a durable, opaque, oldest-first cursor and forwards a
bounded, hydrated ``inventory.resource_changed`` event per changed
resource - a low-latency freshness *hint* that runs ahead of the Activity
Log recovery delta and the authoritative ARG full scan.

Design boundaries (identical discipline to
:mod:`fdai.delivery.azure.arg_query` / :mod:`fdai.delivery.azure.activity_log`)
-------------------------------------------------------------------------

- ``core/`` never imports this module. It is bound at the composition
  root (``inventory_sync_cli.py``) through a plain async function.
- Identity flows through the injected
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  Protocol - no ``DefaultAzureCredential``, no ``azure-identity`` import.
- HTTP transport is an injected :class:`httpx.AsyncClient` routed through
  the shared, bounded, quota-aware :func:`~fdai.delivery.azure.arg_transport.
  fetch_arg_row_pages` helper. Tests pass a client backed by
  :class:`httpx.MockTransport`. No live network.
- Mapping reuses the reviewed :mod:`fdai.delivery.azure.arg_projection`
  helpers and the shared resource-type registry
  (:func:`~fdai.rule_catalog.schema.resource_type.resolve_azure_resource_type`).
  Nothing is inferred from a resource's name; an ARM type outside the
  registry is dropped rather than emitted with an unknown type.

Cursor model
------------

The durable cursor is the opaque string ``"<changeTime_iso>\\x1f<change_id>"``
- the ``resourcechanges`` row's own change timestamp plus its stable
``id`` as a tie-breaker for rows sharing one timestamp. An empty cursor
starts at ``now - initial_lookback_seconds``. Every poll queries
strictly *after* the cursor (oldest first) and advances to the maximum
``(changeTime, id)`` seen across the validated page, so a row that was
seen but dropped (unmapped ARM type, race-lost hydration) still moves the
cursor forward and is never reprocessed.

Create/Update rows are hydrated in bounded batches (``<= max_hydration_batch``,
capped at 100) against the ARG ``Resources`` table so the emitted upsert
carries the resource's current, complete property set
(``properties_complete=True``, ``observation_kind="full"``). Delete rows
are never hydrated (the resource is gone); they are published as
unconfirmed tombstones (``kind="delete"``, ``tombstone_confirmed=False``)
that full reconciliation later confirms or refutes.

Safety / cost invariants
------------------------

- **Fail-closed on partial**: any query/hydration HTTP error, malformed
  page, or truncated result without a continuation token raises
  :class:`ArgResourceChangeError` before any event is built, so the
  caller keeps the previous cursor. A resource that legitimately does
  not come back from hydration (e.g. deleted between the change record
  and the hydration read) is a benign skip, not a fetch failure - it
  does not block the cursor or the rest of the batch.
- **Bounded hydration**: at most ``max_hydration_batch`` (<= 100) ARM ids
  per ``Resources`` query.
- **Bounded pages/rows/bytes/time**: every ARG call goes through
  :func:`~fdai.delivery.azure.arg_transport.fetch_arg_row_pages`, which
  enforces page count, response byte, and total byte caps; the caller
  wraps the whole poll in a deadline.
- **No relationship inference**: the only relationship emitted is the
  reviewed, ARM-id-derived ``contains`` edge from
  :func:`~fdai.delivery.azure.arg_projection.extract_rg_contains_links`;
  ``links_complete`` is always ``False``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from fdai.delivery.azure.arg_projection import (
    arm_id_to_type,
    build_arm_to_neutral_map,
    extract_rg_contains_links,
    parent_neutral_id,
    resource_operational_status,
    to_neutral_id,
    truncate_props,
)
from fdai.delivery.azure.arg_transport import (
    DEFAULT_ARG_REQUESTS_PER_SECOND,
    ArgRateLimiter,
    ArgThrottleGate,
    fetch_arg_row_pages,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resolve_azure_resource_type,
)
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PROPS_BYTES: Final[int] = 64 * 1024
_DEFAULT_INITIAL_LOOKBACK_SECONDS: Final[int] = 3600
_DEFAULT_PAGE_SIZE: Final[int] = 200
_DEFAULT_MAX_PAGES: Final[int] = 5
_DEFAULT_MAX_HYDRATION_BATCH: Final[int] = 100
_MAX_HYDRATION_BATCH_CAP: Final[int] = 100
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 10_000_000
_DEFAULT_MAX_TOTAL_RESPONSE_BYTES: Final[int] = 64_000_000
_CURSOR_SEP: Final[str] = "\x1f"  # ASCII unit separator - never in an RFC 3339 ts or a GUID.
_CHANGE_KIND_BY_ARG_VALUE: Final[Mapping[str, str]] = {
    "create": "upsert",
    "update": "upsert",
    "delete": "delete",
}
_OPERATIONAL_STATUS_CHANGE_PATHS: Final[Mapping[str, tuple[str, ...]]] = {
    "properties.powerState.code": ("properties", "powerState", "code"),
    "properties.resourceState": ("properties", "resourceState"),
    "properties.state": ("properties", "state"),
    "properties.status": ("properties", "status"),
    "properties.userVisibleState": ("properties", "userVisibleState"),
}
_SOURCE: Final[str] = "fdai.delivery.azure.arg_resource_changes"
_SIGNAL_KIND: Final[str] = "azure.resource_graph_change_feed"
_CURSOR_PREFIX: Final[str] = "arg_resource_change_cursor:"
DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS: Final[float] = 60.0


class ArgResourceChangeError(RuntimeError):
    """Raised when a ``resourcechanges`` poll or hydration fetch is unusable.

    The message is safe to log - it never carries raw response bodies or
    tenant-identifying values, only a short, bounded reason string.
    """


@dataclass(frozen=True, slots=True)
class AzureResourceChangeFeedConfig:
    """Configuration for the ``resourcechanges`` polling feed."""

    subscription_scope: str
    """The single subscription id the ``resourcechanges`` query runs over.

    The feed is single-scope by design; a multi-subscription fork binds
    one feed (and one cursor) per subscription, mirroring the Activity
    Log delta factory."""

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_props_bytes: int = _DEFAULT_MAX_PROPS_BYTES
    initial_lookback_seconds: int = _DEFAULT_INITIAL_LOOKBACK_SECONDS
    page_size: int = _DEFAULT_PAGE_SIZE
    max_pages: int = _DEFAULT_MAX_PAGES
    max_hydration_batch: int = _DEFAULT_MAX_HYDRATION_BATCH
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    max_total_response_bytes: int = _DEFAULT_MAX_TOTAL_RESPONSE_BYTES
    requests_per_second: float = DEFAULT_ARG_REQUESTS_PER_SECOND

    def __post_init__(self) -> None:
        try:
            canonical_scope = str(UUID(self.subscription_scope))
        except (AttributeError, ValueError) as exc:
            raise ValueError(
                "AzureResourceChangeFeedConfig.subscription_scope MUST be a canonical UUID"
            ) from exc
        if canonical_scope != self.subscription_scope.casefold():
            raise ValueError(
                "AzureResourceChangeFeedConfig.subscription_scope MUST be a canonical UUID"
            )
        parsed_endpoint = urlparse(self.arg_endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise ValueError(
                "AzureResourceChangeFeedConfig.arg_endpoint MUST use https:// "
                "- the bearer token is sent on every request "
                f"(got {self.arg_endpoint!r})"
            )
        if (
            parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.path not in {"", "/"}
            or parsed_endpoint.params
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise ValueError("AzureResourceChangeFeedConfig.arg_endpoint MUST be an origin URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if self.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")
        if self.initial_lookback_seconds < 0:
            raise ValueError("initial_lookback_seconds MUST be >= 0")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if self.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")
        if not 1 <= self.max_hydration_batch <= _MAX_HYDRATION_BATCH_CAP:
            raise ValueError(f"max_hydration_batch MUST be in [1, {_MAX_HYDRATION_BATCH_CAP}]")
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes MUST be >= 1")
        if self.max_total_response_bytes < 1:
            raise ValueError("max_total_response_bytes MUST be >= 1")
        if not 0 < self.requests_per_second <= 100:
            raise ValueError("requests_per_second MUST be in (0, 100]")


@dataclass(frozen=True, slots=True)
class _ChangeRow:
    """One validated ``resourcechanges`` record."""

    change_id: str
    change_time: datetime
    change_kind: str  # "upsert" | "delete"
    arm_id: str
    arm_type: str | None
    neutral_id: str
    operational_status_change: tuple[tuple[str, ...], str] | None


@dataclass(frozen=True, slots=True)
class ResourceChangeFeedResult:
    """One bounded poll result: the events to publish and the next cursor."""

    events: tuple[Event, ...]
    next_cursor: str


class AzureResourceChangeFeed:
    """Poll ``resourcechanges``, hydrate changed resources, and build events."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
        config: AzureResourceChangeFeedConfig,
    ) -> None:
        self._identity: Final[WorkloadIdentity] = identity
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureResourceChangeFeedConfig] = config
        self._resource_types: Final[ResourceTypeRegistry] = resource_types
        # ARM type -> CSP-neutral resource_type reverse map for delete
        # tombstones, which carry no `kind` disambiguator.
        self._arm_to_neutral: Final[Mapping[str, str]] = build_arm_to_neutral_map(resource_types)
        self._throttle_gate: Final[ArgThrottleGate] = ArgThrottleGate()
        self._rate_limiter: Final[ArgRateLimiter] = ArgRateLimiter(
            requests_per_second=config.requests_per_second
        )

    async def poll(self, cursor: str) -> ResourceChangeFeedResult:
        """Fetch one bounded, oldest-first page of changes past ``cursor``."""

        lower_ts, lower_id = _decode_cursor(cursor)
        query = self._build_change_query(lower_ts=lower_ts, lower_id=lower_id)
        rows = await fetch_arg_row_pages(
            identity=self._identity,
            http_client=self._http,
            audience=self._config.audience,
            endpoint=self._config.arg_endpoint,
            api_version=self._config.arg_api_version,
            subscriptions=(self._config.subscription_scope,),
            query=query,
            result_name="resourcechanges",
            page_size=self._config.page_size,
            max_pages=self._config.max_pages,
            timeout_seconds=self._config.timeout_seconds,
            error_type=ArgResourceChangeError,
            throttle_gate=self._throttle_gate,
            rate_limiter=self._rate_limiter,
            max_response_bytes=self._config.max_response_bytes,
            max_total_response_bytes=self._config.max_total_response_bytes,
        )
        if not rows:
            return ResourceChangeFeedResult(events=(), next_cursor=cursor)

        changes = [self._parse_change_row(row) for row in rows]
        newest = max((change.change_time, change.change_id) for change in changes)
        if lower_ts is not None and newest <= (lower_ts, lower_id or ""):
            raise ArgResourceChangeError("resourcechanges cursor did not advance")

        # Dedupe per neutral resource id, keeping the row with the greatest
        # (change_time, change_id) so a resource touched twice in one page
        # upserts (or deletes) exactly once.
        latest_by_resource: dict[str, _ChangeRow] = {}
        for change in changes:
            prior = latest_by_resource.get(change.neutral_id)
            if prior is None or (change.change_time, change.change_id) > (
                prior.change_time,
                prior.change_id,
            ):
                latest_by_resource[change.neutral_id] = change

        upserts = sorted(
            (c for c in latest_by_resource.values() if c.change_kind == "upsert"),
            key=lambda c: c.neutral_id,
        )
        deletes = sorted(
            (c for c in latest_by_resource.values() if c.change_kind == "delete"),
            key=lambda c: c.neutral_id,
        )

        events: list[Event] = []
        for change in deletes:
            resource_type = self._resolve_delete_type(change)
            if resource_type is None:
                continue  # ARM type outside the vocabulary - drop, don't fail closed.
            events.append(self._tombstone_event(change, resource_type=resource_type))

        hydrated = await self._hydrate([change.arm_id for change in upserts])
        for change in upserts:
            record = hydrated.get(change.arm_id.casefold())
            if record is None:
                continue  # Resource vanished (or type unmapped) before hydration - benign skip.
            events.append(self._upsert_event(change, record=record))

        next_cursor = _encode_cursor(newest[0], newest[1])
        return ResourceChangeFeedResult(events=tuple(events), next_cursor=next_cursor)

    # ------------------------------------------------------------------
    # Query construction
    # ------------------------------------------------------------------

    def _build_change_query(self, *, lower_ts: datetime | None, lower_id: str | None) -> str:
        if lower_ts is None:
            lookback = datetime.now(tz=UTC) - timedelta(
                seconds=self._config.initial_lookback_seconds
            )
            predicate = f"| where changeTime > datetime('{lookback.isoformat()}') "
        else:
            assert lower_id is not None  # noqa: S101 - decoded together, never one without the other
            if "'" in lower_id:
                raise ArgResourceChangeError("illegal character in resourcechanges cursor id")
            predicate = (
                f"| where changeTime > datetime('{lower_ts.isoformat()}') "
                "or (changeTime == "
                f"datetime('{lower_ts.isoformat()}') "
                f"and strcmp(tostring(id), '{lower_id}') > 0) "
            )
        return (
            "resourcechanges "
            "| extend changeTime = todatetime(properties.changeAttributes.timestamp), "
            "changeType = tostring(properties.changeType), "
            "targetResourceId = tostring(properties.targetResourceId), "
            "targetResourceType = tostring(properties.targetResourceType), "
            "changes = properties.changes "
            f"{predicate}"
            "| order by changeTime asc, id asc "
            "| project id, changeTime, changeType, targetResourceId, targetResourceType, changes"
        )

    def _build_hydration_query(self, arm_ids: Sequence[str]) -> str:
        for arm_id in arm_ids:
            if "'" in arm_id:
                raise ArgResourceChangeError("illegal character in resourcechanges target id")
        quoted = ", ".join(f"'{arm_id}'" for arm_id in arm_ids)
        return (
            f"Resources | where id in~ ({quoted}) "
            "| project id, type, name, location, kind, sku, identity, tags, properties, "
            "resourceGroup, subscriptionId"
        )

    # ------------------------------------------------------------------
    # Row parsing / mapping
    # ------------------------------------------------------------------

    def _parse_change_row(self, row: Mapping[str, Any]) -> _ChangeRow:
        change_id = row.get("id")
        if not isinstance(change_id, str) or not change_id:
            raise ArgResourceChangeError("resourcechanges row lacks an id")
        change_time = _parse_ts(row.get("changeTime"))
        if change_time is None:
            raise ArgResourceChangeError(
                "resourcechanges row changeTime MUST be a valid RFC 3339 timestamp"
            )
        raw_kind = row.get("changeType")
        if not isinstance(raw_kind, str) or not raw_kind.strip():
            raise ArgResourceChangeError("resourcechanges row changeType MUST be a string")
        change_kind = _CHANGE_KIND_BY_ARG_VALUE.get(raw_kind.strip().casefold())
        if change_kind is None:
            raise ArgResourceChangeError(
                f"resourcechanges row changeType {raw_kind!r} is unsupported"
            )
        arm_id = row.get("targetResourceId")
        if not isinstance(arm_id, str) or not arm_id.startswith("/"):
            raise ArgResourceChangeError("resourcechanges row targetResourceId MUST be an ARM id")
        arm_type = row.get("targetResourceType")
        if arm_type is not None and not isinstance(arm_type, str):
            raise ArgResourceChangeError(
                "resourcechanges row targetResourceType MUST be a string or null"
            )
        raw_changes = row.get("changes")
        if raw_changes is not None and not isinstance(raw_changes, Mapping):
            raise ArgResourceChangeError("resourcechanges row changes MUST be an object or null")
        return _ChangeRow(
            change_id=change_id,
            change_time=change_time,
            change_kind=change_kind,
            arm_id=arm_id,
            arm_type=arm_type,
            neutral_id=to_neutral_id(arm_id),
            operational_status_change=_operational_status_change(raw_changes or {}),
        )

    def _resolve_delete_type(self, change: _ChangeRow) -> str | None:
        arm_type = change.arm_type or arm_id_to_type(change.arm_id)
        if arm_type is None:
            return None
        return self._arm_to_neutral.get(arm_type.casefold())

    async def _hydrate(self, arm_ids: Sequence[str]) -> dict[str, ResourceRecord]:
        if not arm_ids:
            return {}
        ordered_unique = list(dict.fromkeys(arm_ids))
        hydrated: dict[str, ResourceRecord] = {}
        batch_size = self._config.max_hydration_batch
        for start in range(0, len(ordered_unique), batch_size):
            batch = ordered_unique[start : start + batch_size]
            query = self._build_hydration_query(batch)
            rows = await fetch_arg_row_pages(
                identity=self._identity,
                http_client=self._http,
                audience=self._config.audience,
                endpoint=self._config.arg_endpoint,
                api_version=self._config.arg_api_version,
                subscriptions=(self._config.subscription_scope,),
                query=query,
                result_name="resourcechanges-hydration",
                page_size=1000,
                max_pages=1,
                timeout_seconds=self._config.timeout_seconds,
                error_type=ArgResourceChangeError,
                throttle_gate=self._throttle_gate,
                rate_limiter=self._rate_limiter,
                max_response_bytes=self._config.max_response_bytes,
                max_total_response_bytes=self._config.max_total_response_bytes,
            )
            for row in rows:
                mapped = self._map_hydrated_row(row)
                if mapped is None:
                    continue
                arm_id_key, record = mapped
                hydrated[arm_id_key] = record
        return hydrated

    def _map_hydrated_row(self, row: Mapping[str, Any]) -> tuple[str, ResourceRecord] | None:
        arm_id = row.get("id")
        if not isinstance(arm_id, str) or not arm_id:
            raise ArgResourceChangeError("resourcechanges hydration row lacks a provider id")
        arm_type = row.get("type")
        if not isinstance(arm_type, str) or not arm_type.strip():
            raise ArgResourceChangeError("resourcechanges hydration row lacks a provider type")
        resolved_type = resolve_azure_resource_type(
            self._resource_types, arm_type=arm_type, kind=row.get("kind")
        )
        if resolved_type is None:
            return None  # Unmapped or ambiguous ARM type - drop, don't fail closed.

        neutral_id = to_neutral_id(arm_id)
        props: dict[str, Any] = {"providerType": arm_type}
        subscription_id = row.get("subscriptionId")
        if isinstance(subscription_id, str) and subscription_id:
            props["subscriptionId"] = subscription_id
        hydrated_keys = (
            "name",
            "location",
            "kind",
            "sku",
            "identity",
            "tags",
            "properties",
            "resourceGroup",
        )
        for key in hydrated_keys:
            if key in row and row[key] is not None:
                props[key] = row[key]
        if status := resource_operational_status(row):
            props["status"] = status
        props = truncate_props(props, max_bytes=self._config.max_props_bytes)
        if (parent_id := parent_neutral_id(arm_id)) is not None:
            props["parent_id"] = parent_id
        record = ResourceRecord(
            resource_id=neutral_id,
            type=resolved_type,
            props=props,
            provider_ref=arm_id,
            # Placeholder; the caller stamps the change's own observation
            # time via `dataclasses.replace` before emitting the event.
            last_seen=datetime.now(tz=UTC).isoformat(),
        )
        return arm_id.casefold(), record

    # ------------------------------------------------------------------
    # Event construction
    # ------------------------------------------------------------------

    def _upsert_event(self, change: _ChangeRow, *, record: ResourceRecord) -> Event:
        props = dict(record.props)
        if change.operational_status_change is not None:
            path, status = change.operational_status_change
            props = _with_nested_value(props, path, status)
            props["status"] = status
        resource = replace(
            record,
            props=props,
            last_seen=change.change_time.isoformat(),
        )
        resource_payload = {
            "resource_id": resource.resource_id,
            "type": resource.type,
            "props": dict(resource.props),
            "provider_ref": resource.provider_ref,
            "last_seen": resource.last_seen,
        }
        link_payloads = [
            {
                "change_kind": "upsert",
                "from_id": link.from_id,
                "from_type": link.from_type,
                "link_type": link.link_type,
                "to_id": link.to_id,
                "to_type": link.to_type,
                "props": dict(link.link_props),
            }
            for link in extract_rg_contains_links((resource,))
        ]
        return Event(
            schema_version="1.0.0",
            event_id=_event_uuid(self._config.subscription_scope, change.change_id),
            idempotency_key=f"arg-resource-change:{self._config.subscription_scope}:"
            f"{change.change_id}",
            correlation_id=f"inventory:{resource.resource_id}",
            source=_SOURCE,
            event_type="inventory.resource_changed",
            resource_ref=resource.resource_id,
            payload={
                "signal_kind": _SIGNAL_KIND,
                "inventory_change": {
                    "kind": "upsert",
                    "observation_kind": "full",
                    "properties_complete": True,
                    "property_mask": sorted(resource.props),
                    "tombstone_confirmed": False,
                    "scope_ref": self._config.subscription_scope,
                    "resource": resource_payload,
                    "links": link_payloads,
                    "links_complete": False,
                },
            },
            detected_at=change.change_time,
            ingested_at=datetime.now(tz=UTC),
            incident_correlation=IncidentCorrelation.NONE,
            mode=Mode.SHADOW,
        )

    def _tombstone_event(self, change: _ChangeRow, *, resource_type: str) -> Event:
        resource_payload = {
            "resource_id": change.neutral_id,
            "type": resource_type,
            "props": {},
            "provider_ref": change.arm_id,
            "last_seen": change.change_time.isoformat(),
        }
        return Event(
            schema_version="1.0.0",
            event_id=_event_uuid(self._config.subscription_scope, change.change_id),
            idempotency_key=f"arg-resource-change:{self._config.subscription_scope}:"
            f"{change.change_id}",
            correlation_id=f"inventory:{change.neutral_id}",
            source=_SOURCE,
            event_type="inventory.resource_changed",
            resource_ref=change.neutral_id,
            payload={
                "signal_kind": _SIGNAL_KIND,
                "inventory_change": {
                    "kind": "delete",
                    "observation_kind": "tombstone",
                    "properties_complete": False,
                    "property_mask": [],
                    "tombstone_confirmed": False,
                    "scope_ref": self._config.subscription_scope,
                    "resource": resource_payload,
                    "links": [],
                    "links_complete": False,
                },
            },
            detected_at=change.change_time,
            ingested_at=datetime.now(tz=UTC),
            incident_correlation=IncidentCorrelation.NONE,
            mode=Mode.SHADOW,
        )


async def forward_arg_resource_changes(
    *,
    feed: AzureResourceChangeFeed,
    state_store: StateStore,
    event_bus: EventBus,
    topic: str,
    scope: str,
    deadline_seconds: float = DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS,
) -> int:
    """Publish one bounded ``resourcechanges`` poll and advance its cursor.

    The cursor is persisted only after every event in the poll result has
    published successfully - a raised exception (query failure, hydration
    failure, publish failure, or a deadline timeout) leaves the previous
    cursor untouched, so the next poll safely re-reads the same window.
    """

    if deadline_seconds <= 0:
        raise ValueError("resource change feed deadline_seconds MUST be > 0")
    cursor_key = f"{_CURSOR_PREFIX}{scope}"
    saved = await state_store.read_state(cursor_key) or {}
    cursor = str(saved.get("cursor") or "")
    result: ResourceChangeFeedResult | None = None
    try:
        async with asyncio.timeout(deadline_seconds):
            result = await feed.poll(cursor)
            for event in result.events:
                await event_bus.publish(
                    topic,
                    event.resource_ref or scope,
                    event.model_dump(mode="json"),
                )
    except TimeoutError as exc:
        raise RuntimeError("resource change feed poll exceeded its deadline") from exc
    if result is None:
        raise RuntimeError("resource change feed poll produced no result")
    if result.next_cursor != cursor:
        await state_store.write_state(cursor_key, {"cursor": result.next_cursor})
    return len(result.events)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_uuid(scope: str, change_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fdai.arg-resource-change://{scope}/{change_id}")


def _encode_cursor(change_time: datetime, change_id: str) -> str:
    return f"{change_time.astimezone(UTC).isoformat()}{_CURSOR_SEP}{change_id}"


def _decode_cursor(cursor: str) -> tuple[datetime | None, str | None]:
    trimmed = cursor.strip()
    if not trimmed:
        return None, None
    if _CURSOR_SEP not in trimmed:
        raise ArgResourceChangeError("resourcechanges cursor is malformed")
    ts_part, _, id_part = trimmed.partition(_CURSOR_SEP)
    parsed = _parse_ts(ts_part)
    if parsed is None or not id_part:
        raise ArgResourceChangeError("resourcechanges cursor is malformed")
    return parsed, id_part


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00") if raw.strip().endswith("Z") else raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _operational_status_change(
    changes: Mapping[str, Any],
) -> tuple[tuple[str, ...], str] | None:
    for source_path, target_path in _OPERATIONAL_STATUS_CHANGE_PATHS.items():
        raw_change = changes.get(source_path)
        if not isinstance(raw_change, Mapping):
            continue
        raw_value = raw_change.get("newValue")
        candidate = raw_value.get("code") if isinstance(raw_value, Mapping) else raw_value
        if isinstance(candidate, str) and candidate.strip():
            return target_path, candidate.strip()
    return None


def _with_nested_value(
    value: Mapping[str, Any],
    path: tuple[str, ...],
    replacement: str,
) -> dict[str, Any]:
    updated = dict(value)
    cursor = updated
    for component in path[:-1]:
        existing = cursor.get(component)
        child = dict(existing) if isinstance(existing, Mapping) else {}
        cursor[component] = child
        cursor = child
    cursor[path[-1]] = replacement
    return updated


__all__ = [
    "ArgResourceChangeError",
    "AzureResourceChangeFeed",
    "AzureResourceChangeFeedConfig",
    "DEFAULT_RESOURCE_CHANGE_DEADLINE_SECONDS",
    "ResourceChangeFeedResult",
    "forward_arg_resource_changes",
]
